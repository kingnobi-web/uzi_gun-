"""Deliberately in-sample tree fitting. Frozen JSON evaluation never retrains."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from aggressive_research import Batch

FEATURE_NAMES = ['move5_spreads','move10_spreads','move30_spreads','range30_spreads',
                 'tick_balance30','spread','midprice','utc_hour_sin','utc_hour_cos']


def load_ticks(folder):
    meta=json.loads((folder/'metadata.json').read_text())
    if meta['currency']!='USD' or 'XAUUSD' not in meta['symbol'].upper() or float(meta['contract_size'])!=100:
        raise ValueError('Requires USD XAUUSD contract size 100')
    with (folder/'ticks.csv').open() as f:
        rows=[(int(r['time_msc'])/1000,float(r['bid']),float(r['ask'])) for r in csv.DictReader(f)]
    a=np.asarray(rows,dtype=float)
    if len(a)<1000 or not np.isfinite(a).all() or (np.diff(a[:,0])<0).any() or (a[:,1]<=0).any() or (a[:,2]<a[:,1]).any():
        raise ValueError('Need at least 1000 valid chronological bid/ask ticks')
    return a


def samples(ticks):
    t=ticks[:,0];mid=(ticks[:,1]+ticks[:,2])/2
    changes=np.sign(np.diff(mid,prepend=mid[0]));cumulative=np.cumsum(changes)
    indexes=[];rows=[];ready=t[0]+30;next_sample=ready
    for i in range(len(t)):
        if i and t[i]-t[i-1]>30:ready=t[i]+30;next_sample=ready
        if t[i]<ready or t[i]<next_sample:continue
        left=np.searchsorted(t,t[i]-30,side='left');five=np.searchsorted(t,t[i]-5,side='left');ten=np.searchsorted(t,t[i]-10,side='left')
        spread=max(ticks[i,2]-ticks[i,1],.01);window=mid[left:i+1]
        balance=(cumulative[i]-(cumulative[left-1] if left else 0))/max(1,i-left+1)
        angle=2*np.pi*((t[i]%86400)/86400)
        rows.append([(mid[i]-mid[five])/spread,(mid[i]-mid[ten])/spread,
                     (mid[i]-mid[left])/spread,(window.max()-window.min())/spread,
                     balance,spread,mid[i],np.sin(angle),np.cos(angle)])
        indexes.append(i);next_sample=t[i]+5
    return np.asarray(indexes,dtype=int),np.asarray(rows,dtype=float)


def labels(ticks,indexes):
    # Future prices are used ONLY as training labels, never as live features.
    future=np.searchsorted(ticks[:,0],ticks[indexes,0]+30,side='left')
    valid=future<len(ticks);future=np.minimum(future,len(ticks)-1)
    valid&=(ticks[future,0]-ticks[indexes,0]<=31)
    long=ticks[future,1]-ticks[indexes,2]-.04
    short=ticks[indexes,1]-ticks[future,2]-.04
    y=np.where(np.maximum(long,short)>.15,np.where(long>short,1,-1),0)
    return valid,y


def tree_json(model):
    tree=model.tree_;values=tree.value[:,0,:];totals=values.sum(axis=1,keepdims=True)
    return dict(left=tree.children_left.tolist(),right=tree.children_right.tolist(),
                feature=tree.feature.tolist(),threshold=tree.threshold.tolist(),
                probabilities=(values/np.maximum(totals,1e-12)).tolist(),classes=model.classes_.tolist())


def predict(tree,x,confidence):
    signals=[]
    for row in np.asarray(x,dtype=np.float32):
        node=0
        while tree['left'][node]!=-1:
            node=tree['left'][node] if row[tree['feature'][node]]<=tree['threshold'][node] else tree['right'][node]
        probs=tree['probabilities'][node];best=max(range(len(probs)),key=probs.__getitem__)
        signals.append(tree['classes'][best] if probs[best]>=confidence else 0)
    return np.asarray(signals,dtype=int)


def replay(ticks,indexes,signals,start=None):
    sim=Batch('fitted-tree',profit_target=5,loss_limit=5,max_hold=30)
    j=-1;end=ticks[-1,0]
    for i,(t,bid,ask) in enumerate(ticks):
        while j+1<len(indexes) and indexes[j+1]<=i:j+=1
        if start is not None and t<start:continue
        signal=int(signals[j]) if j>=0 and t-ticks[indexes[j],0]<=6 else 0
        sim.tick(t,bid,ask,signal,allow_entry=t<end-90)
    sim.finish();return sim


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['fit','evaluate']);p.add_argument('data',type=Path)
    p.add_argument('--model',type=Path,help='Frozen JSON model for evaluate')
    p.add_argument('--output',type=Path,default=Path('fitted-results'))
    a=p.parse_args();ticks=load_ticks(a.data);indexes,x=samples(ticks)
    if len(indexes)<100:raise ValueError('Not enough feature samples')
    a.output.mkdir(parents=True,exist_ok=False)
    if a.mode=='fit':
        from sklearn.tree import DecisionTreeClassifier
        valid,y=labels(ticks,indexes)
        if valid.sum()<100:raise ValueError('Not enough valid training labels')
        best=None;ranking=[]
        # Predeclared capacity/confidence grid; selection is explicitly in-sample.
        for depth,leaf in [(8,20),(12,10),(20,2)]:
            model=DecisionTreeClassifier(max_depth=depth,min_samples_leaf=leaf,random_state=42)
            model.fit(x[valid],y[valid]);tree=tree_json(model)
            for confidence in [.6,.8]:
                signals=predict(tree,x,confidence);sim=replay(ticks,indexes,signals)
                stats=sim.stats();name=f'depth{depth}-leaf{leaf}-confidence{confidence}'
                ranking.append(dict(name=name,stats=stats))
                print(name,stats,flush=True)
                if stats['batches']>=50 and (best is None or stats['net_usd']>best['training_stats']['net_usd']):
                    best=dict(name=name,tree=tree,confidence=confidence,training_stats=stats,
                              features=FEATURE_NAMES,training_start=float(ticks[0,0]),training_end=float(ticks[-1,0]),
                              settings=dict(positions=10,lot=.01,target=5,loss=5,max_hold=30,latency=.1,slippage=.02,commission=0),
                              warning='SELECTED ON TRAINING DATA. NOT VALIDATED. Future prices were labels only; training scores are optimistic.')
        if best is None:raise ValueError('No candidate produced 50 batches')
        best['training_ticks_sha256']=hashlib.sha256((a.data/'ticks.csv').read_bytes()).hexdigest()
        (a.output/'candidate.json').write_text(json.dumps(best,separators=(',',':')))
        report=dict(mode='in_sample_fit',selected=best['name'],stats=best['training_stats'],ranking=ranking,
                    warning=best['warning'],feature_samples=len(indexes),labeled_samples=int(valid.sum()))
    else:
        if a.model is None:p.error('--model is required for evaluate')
        model=json.loads(a.model.read_text())
        if model['features']!=FEATURE_NAMES:raise ValueError('Feature schema mismatch')
        if ticks[-1,0]<=model['training_end']+30:raise ValueError('No new forward data after training period')
        start=model['training_end']+30
        signals=predict(model['tree'],x,model['confidence']);sim=replay(ticks,indexes,signals,start=start)
        report=dict(mode='frozen_forward_evaluation',stats=sim.stats(),evaluated_after_epoch=start,
                    model_sha256=hashlib.sha256(a.model.read_bytes()).hexdigest(),
                    warning='Model not retrained. Tick simulation still omits margin, liquidity, rejection, variable latency, and financing.')
        with (a.output/'batches.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['time','pnl','reason','opened','closed']);w.writeheader();w.writerows(sim.results)
    (a.output/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
