"""Exploratory paired bid/ask M1 research; cannot validate sub-minute execution."""
import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import tempfile
from backtest import Simulation, Trade
from research import RULES, HOLDS, features_for


def read_bars(path):
    with path.open(newline='') as f:
        rows=[]
        for r in csv.DictReader(f):
            stamp=datetime.fromisoformat(r['Etc/UTC'])
            if stamp.utcoffset() is None:raise ValueError('Timestamps need an explicit timezone')
            b=dict(time=int(stamp.timestamp()), **{k.lower():float(r[k]) for k in ('Open','High','Low','Close')})
            if not all(math.isfinite(v) for v in b.values()) or not 0<b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']:
                raise ValueError('Invalid OHLC')
            rows.append(b)
    if any(x['time']>=y['time'] for x,y in zip(rows,rows[1:])):raise ValueError('Bars must be unique and chronological')
    return rows


def evaluate(bids,asks,features,rule,hold,slippage=.02):
    sim=Simulation(rule,100,slippage=slippage)
    for i,(b,a) in enumerate(zip(bids,asks)):
        t=b['time'];started_open=sim.position is not None
        p=sim.position
        if p and t-p.started>=hold:
            sim.close(t,b['open'],a['open'],'timeout')
        # A signal on candle i-1 becomes available only at candle i's open.
        if not started_open and not sim.position and i>0 and features[i-1] is not None and t-bids[i-1]['time']==60:
            feature=features[i-1];side=feature[rule];atr=feature['atr'];spread=a['open']-b['open']
            if side and atr>0 and 0<=spread<=atr*.15 and atr>=4*(spread+2*slippage):
                entry=a['open']+slippage if side==1 else b['open']-slippage
                sim.position=Trade(side,entry,t,atr,1.5*atr)
        p=sim.position
        if not p:continue
        stop=p.entry-p.side*p.stop;target=p.entry+p.side*p.target
        quotes=b if p.side==1 else a
        hit_stop=quotes['low']<=stop if p.side==1 else quotes['high']>=stop
        hit_target=quotes['high']>=target if p.side==1 else quotes['low']<=target
        if hit_stop:
            # If both levels occur in a candle, assume the stop was reached first.
            price=min(stop,quotes['open']) if p.side==1 else max(stop,quotes['open'])
            sim.close(t+60,price,price,'stop_or_ambiguous')
        elif hit_target:
            sim.close(t+60,target,target,'target')
    if sim.position:
        sim.close(bids[-1]['time']+60,bids[-1]['close'],asks[-1]['close'],'data_end')
    return sim


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('bid',type=Path);p.add_argument('ask',type=Path)
    p.add_argument('--output',type=Path,default=Path('candle-results'))
    args=p.parse_args()
    bids=read_bars(args.bid);asks=read_bars(args.ask)
    if not bids or [b['time'] for b in bids]!=[a['time'] for a in asks]:raise ValueError('Bid and ask timestamps must match exactly')
    args.output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'bars.csv'
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['time','open','high','low','close']);w.writeheader();w.writerows(bids)
        _,features=features_for(path)
    results={}
    for rule in RULES:
        for hold in HOLDS:
            name=f'{rule}_{hold}s';sim=evaluate(bids,asks,features,rule,hold);results[name]=sim.stats()
            with (args.output/f'{name}.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['time','pnl','reason']);w.writeheader();w.writerows(sim.results)
    report=dict(candles=len(bids),start_epoch=bids[0]['time'],end_epoch=bids[-1]['time']+60,
                results=results,lot=.01,contract=100,slippage=.02,commission=0,
                conclusion='Single-day exploratory test only; no candidate selected for deployment',
                limitations=['Bid and ask OHLC are not synchronized tick quotes; opening differences only approximate entry spread',
                             'Unknown intrabar path: stop first if both stop and target touched',
                             'Broker-held hypothetical stop/target fills with fixed slippage; no latency or rejection model',
                             'Different provider from Exness; results are not comparable to live execution',
                             'One position; 60/300-second limits; no sub-minute validation or financing model',
                             'All rules screened on one day; no training/independent validation split'])
    (args.output/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
