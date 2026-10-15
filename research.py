"""Fixed exploratory strategy screen. Previously viewed data is NOT fresh validation."""
import argparse
import bisect
import csv
import json
import math
from pathlib import Path
from backtest import Simulation, Trade, load_features

# Declared before looking at results: six entry rules, two holding limits.
RULES = ('fade_move', 'band_reentry', 'rsi_reentry', 'trend_pullback', 'trend_breakout', 'channel_fade')
HOLDS = (60, 300)


def features_for(path):
    times, base = load_features(path)
    with path.open() as f:
        bars = [{k:float(v) for k,v in r.items()} for r in csv.DictReader(f)]
    ema20 = ema50 = bars[0]['close']
    closes = []; gains=[]; losses=[]
    previous_rsi = 50; previous_z = 0
    for i,b in enumerate(bars):
        c=b['close']; prev=bars[max(0,i-1)]['close']
        ema20 += 2/21*(c-ema20); ema50 += 2/51*(c-ema50)
        closes.append(c); gains.append(max(0,c-prev)); losses.append(max(0,prev-c))
        window=closes[-20:]; mean=sum(window)/len(window)
        sd=math.sqrt(sum((x-mean)**2 for x in window)/len(window))
        z=(c-mean)/sd if sd else 0
        loss=sum(losses[-14:]); gain=sum(gains[-14:])
        rsi=100*gain/(gain+loss) if gain+loss else 50
        if i>=60:
            atr=base[i]['atr']; move=c-prev
            prior=bars[i-10:i]; high=max(x['high'] for x in prior); low=min(x['low'] for x in prior)
            # Signals use completed bars only. Zero means no new entry.
            base[i].update(
                fade_move=-1 if move>atr else 1 if move < -atr else 0,
                band_reentry=1 if previous_z < -2 and z>=-2 else -1 if previous_z>2 and z<=2 else 0,
                rsi_reentry=1 if previous_rsi<30 and rsi>=30 else -1 if previous_rsi>70 and rsi<=70 else 0,
                trend_pullback=1 if ema20>ema50 and prev<ema20 and c>ema20 else -1 if ema20<ema50 and prev>ema20 and c<ema20 else 0,
                trend_breakout=1 if c>high and ema20>ema50 else -1 if c<low and ema20<ema50 else 0,
                channel_fade=-1 if b['high']>high and c<high else 1 if b['low']<low and c>low else 0,
            )
        else:
            base[i]=None
        previous_rsi=rsi;previous_z=z
    return times,base


class ResearchSimulation(Simulation):
    def __init__(self, rule, hold, **kwargs):
        super().__init__(rule, **kwargs)
        self.hold=hold

    def tick(self,timestamp,bid,ask,index,feature,allow_entry=True):
        self.last_quote=(timestamp,bid,ask)
        p=self.position
        if p:
            move=((bid if p.side==1 else ask)-p.entry)*p.side
            if move<=-p.stop or move>=p.target or timestamp-p.started>=self.hold:
                self.close(timestamp,bid,ask,'stop' if move<=-p.stop else 'target' if move>=p.target else 'timeout')
            return
        if not allow_entry or feature is None or index==self.last_bar:return
        self.last_bar=index
        side=feature[self.strategy];atr=feature['atr']
        if not side or atr<=0 or ask-bid>atr*.15:return
        # Require enough room for spread and round-trip assumed slippage.
        if atr<4*(ask-bid+2*self.slippage):return
        entry=ask+self.slippage if side==1 else bid-self.slippage
        self.position=Trade(side,entry,timestamp,atr,atr*1.5)


def evaluate_segment(folder,times,features,start,end,slippage,names):
    sims={name:ResearchSimulation(rule,hold,contract=100,slippage=slippage) for name,(rule,hold) in names.items()}
    previous=-1
    with (folder/'ticks.csv').open() as f:
        for row in csv.DictReader(f):
            ts=int(row['time_msc'])/1000;bid=float(row['bid']);ask=float(row['ask'])
            if not all(math.isfinite(x) for x in (ts,bid,ask)) or not 0<bid<=ask or ts<previous:raise ValueError('Invalid ticks')
            previous=ts
            if ts<start:continue
            if ts>=end:break
            i=bisect.bisect_right(times,ts)-1
            feature=features[i] if i>=0 and ts-times[i]<=120 else None
            for sim in sims.values():sim.tick(ts,bid,ask,i,feature,ts<end-sim.hold)
    for sim in sims.values():sim.finish()
    return sims


def select_candidate(training):
    eligible=[n for n,s in training.items() if s['trades']>=30 and s['net_usd']>0]
    return max(eligible,key=lambda n:training[n]['net_usd']) if eligible else None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('data',type=Path)
    p.add_argument('--output',type=Path,default=Path('strategy-screen'))
    a=p.parse_args()
    metadata=json.loads((a.data/'metadata.json').read_text())
    if metadata['currency']!='USD' or 'XAUUSD' not in metadata['symbol'].upper() or float(metadata['contract_size'])!=100:
        p.error('Requires XAUUSD, USD account, contract size 100')
    times,features=features_for(a.data/'bars.csv');split=times[int(len(times)*.7)]
    names={f'{r}_{h}s':(r,h) for r in RULES for h in HOLDS}
    train=evaluate_segment(a.data,times,features,times[60],split,.02,names)
    training={n:s.stats() for n,s in train.items()}
    selected=select_candidate(training)
    # The choice is frozen using training only. Later data has already been viewed.
    print('Training complete; locked candidate:',selected,flush=True)
    later=evaluate_segment(a.data,times,features,split,times[-1],.02,names)
    stress=evaluate_segment(a.data,times,features,split,times[-1],.05,{selected:names[selected]}) if selected else {}
    result=dict(training=training,selected_using_training_only=selected,
                later_exploratory={n:s.stats() for n,s in later.items()},
                selected_later_stress={n:s.stats() for n,s in stress.items()},
                split_epoch=split,assumptions=dict(lot=.01,contract=100,commission=0,slippage_per_fill=.02,stress_slippage=.05),
                caveat='Later period was previously viewed. This is exploratory research, not independent validation or evidence sufficient for live deployment.')
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2))
    if selected:
        for label,sims in [('training',train),('later',later),('stress',stress)]:
            with (a.output/f'{label}-selected-trades.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['time','pnl','reason']);w.writeheader();w.writerows(sims[selected].results)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
