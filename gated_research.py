"""Fixed 18-case ten-position research screen. No live orders."""
import argparse
import bisect
from collections import deque
import csv
import json
import math
from pathlib import Path
from aggressive_research import Batch, RULES
from backtest import load_features

GATES=('impulse','range','trend')
TARGETS=(1.5,5.0)


def allowed(gate,side,move,span,spread,trend):
    if not side or spread<=0:return False
    if gate=='impulse':return abs(move)>=3*spread
    if gate=='range':return span>=6*spread and abs(move)>=spread
    if gate=='trend':return side==trend and abs(move)>=2*spread
    raise ValueError('Unknown gate')


def candidates():
    return {f'{rule}-{gate}-tp{target:g}':(rule,gate,target) for rule in RULES for gate in GATES for target in TARGETS}


def run(path,times,features,start,end,configs,latency=.1,slippage=.02):
    sims={n:Batch(rule,latency,slippage,profit_target=target) for n,(rule,gate,target) in configs.items()}
    recent=deque();balance=0;prev_mid=prev_time=None
    with path.open() as f:
        for row in csv.DictReader(f):
            t=int(row['time_msc'])/1000;bid=float(row['bid']);ask=float(row['ask'])
            if not all(math.isfinite(v) for v in (t,bid,ask)) or not 0<bid<=ask:raise ValueError('Invalid tick')
            if prev_time is not None and t<prev_time:raise ValueError('Unsorted ticks')
            if t<start:continue
            if t>=end:break
            mid=(bid+ask)/2
            if prev_time is not None and t-prev_time>30:recent.clear();balance=0;prev_mid=None
            change=0 if prev_mid is None else (mid>prev_mid)-(mid<prev_mid)
            recent.append((t,mid,change));balance+=change
            while recent and recent[0][0]<t-10:balance-=recent.popleft()[2]
            old5=next((m for ts,m,c in recent if ts>=t-5),mid)
            move=mid-old5;sign=lambda v:(v>0)-(v<0)
            signals=dict(momentum_5s=sign(move),reversal_5s=-sign(move),tick_balance_10s=sign(balance))
            mids=[m for ts,m,c in recent];span=max(mids)-min(mids)
            i=bisect.bisect_right(times,t)-1
            feature=features[i] if i>=0 and t-times[i]<=120 else None
            trend=feature['trend'] if feature else 0
            warm=t-recent[0][0]>=9
            for name,sim in sims.items():
                rule,gate,target=configs[name];side=signals[rule]
                # Gates control entries only; never block a pending close.
                enter=warm and t<end-120 and allowed(gate,side,move,span,ask-bid,trend)
                sim.tick(t,bid,ask,side,allow_entry=enter)
            prev_mid=mid;prev_time=t
    for sim in sims.values():sim.finish()
    return sims


def select(segments):
    names=list(segments[0])
    eligible=[n for n in names if all(segment[n]['batches']>=50 and segment[n]['net_usd']>0 for segment in segments)]
    return max(eligible,key=lambda n:sum(segment[n]['net_usd'] for segment in segments)) if eligible else None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('data',type=Path);p.add_argument('--output',type=Path,default=Path('gated-results'))
    a=p.parse_args();meta=json.loads((a.data/'metadata.json').read_text())
    if meta['currency']!='USD' or 'XAUUSD' not in meta['symbol'].upper() or float(meta['contract_size'])!=100:raise ValueError('Requires USD gold contract size 100')
    times,features=load_features(a.data/'bars.csv');split1=times[len(times)//2];split2=times[int(len(times)*.7)]
    configs=candidates();results={};a.output.mkdir(parents=True,exist_ok=False)
    # Predeclared selection requires profit in BOTH earlier consecutive segments.
    for label,lo,hi in [('development',times[30],split1),('check',split1,split2)]:
        sims=run(a.data/'ticks.csv',times,features,lo,hi,configs)
        results[label]={n:s.stats() for n,s in sims.items()}
        print(label,'finished',flush=True)
    selected=select([results['development'],results['check']])
    print('Locked selection',selected,flush=True)
    later=run(a.data/'ticks.csv',times,features,split2,times[-1],configs)
    results['later']={n:s.stats() for n,s in later.items()}
    report=dict(configurations=configs,results=results,selected=selected,split_epochs=[split1,split2],
                assumptions=dict(batch_positions=10,lot=.01,latency=.1,slippage=.02,commission=0,loss_limit=5,max_hold=60),
                conclusion='No candidate passed positive results and 50 batches in both earlier segments' if selected is None else 'Exploratory candidate only; independent data still required',
                caveat='All periods are from previously examined data. Multiple comparisons; do not treat a positive score as independent validation. Margin, liquidity, rejection, financing, and variable latency are not modeled.')
    (a.output/'summary.json').write_text(json.dumps(report,indent=2))
    with (a.output/'comparison.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['rule','segment','batches','net_usd','profit_factor','win_rate','drawdown','all_ten_positions'])
        for label,segment in results.items():
            for name,s in segment.items():w.writerow([name,label,s['batches'],s['net_usd'],s['profit_factor'],s['win_rate'],s['max_closed_drawdown_usd'],s['all_batches_ten_positions']])
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
