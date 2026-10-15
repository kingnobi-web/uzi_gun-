"""Tick-driven, chronological train/holdout research; no broker connection."""
import argparse
import bisect
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass
class Trade:
    side: int
    entry: float
    started: float
    stop: float
    target: float


class Simulation:
    def __init__(self, strategy, contract, lot=.01, slippage=.02, commission=0):
        self.strategy, self.contract, self.lot = strategy, contract, lot
        self.slippage, self.commission = slippage, commission
        self.position = None
        self.last_bar = -1
        self.results = []
        self.last_quote = None

    def close(self, timestamp, bid, ask, reason):
        p = self.position
        exit_price = bid - self.slippage if p.side == 1 else ask + self.slippage
        pnl = (exit_price-p.entry)*p.side*self.contract*self.lot - self.commission*self.lot
        self.results.append(dict(time=timestamp, pnl=pnl, reason=reason))
        self.position = None

    def tick(self, timestamp, bid, ask, index, feature, allow_entry=True):
        self.last_quote = (timestamp, bid, ask)
        p = self.position
        if p:
            price = bid if p.side == 1 else ask
            move = (price-p.entry)*p.side
            if move <= -p.stop or move >= p.target or timestamp-p.started >= 60:
                reason = 'stop' if move <= -p.stop else 'target' if move >= p.target else 'timeout'
                self.close(timestamp, bid, ask, reason)
            return
        if not allow_entry or feature is None or index == self.last_bar:
            return
        self.last_bar = index
        side = feature[self.strategy]
        atr = feature['atr']
        # Filters are fixed in advance; baseline preserves unfiltered M1 momentum.
        if not side or atr <= 0:
            return
        if self.strategy != 'momentum' and ask-bid > atr*.15:
            return
        entry = ask+self.slippage if side == 1 else bid-self.slippage
        self.position = Trade(side, entry, timestamp, atr, atr*1.5)

    def finish(self):
        if self.position:
            self.close(*self.last_quote, 'segment_end')

    def stats(self):
        values = [r['pnl'] for r in self.results]
        wins = sum(x for x in values if x > 0)
        losses = -sum(x for x in values if x < 0)
        equity = peak = drawdown = 0
        for x in values:
            equity += x; peak = max(peak, equity); drawdown = max(drawdown, peak-equity)
        return dict(trades=len(values), net_usd=round(sum(values), 2),
                    win_rate=round(sum(x>0 for x in values)/len(values), 4) if values else 0,
                    profit_factor=round(wins/losses, 3) if losses else None,
                    max_closed_drawdown_usd=round(drawdown, 2),
                    average_usd=round(sum(values)/len(values), 4) if values else 0)


def load_features(path):
    with path.open() as f:
        bars = [{k: float(v) for k,v in row.items()} for row in csv.DictReader(f)]
    if len(bars) < 200:
        raise ValueError('Need at least 200 M1 bars')
    if any(not math.isfinite(v) for b in bars for v in b.values()):
        raise ValueError('M1 bars must be finite')
    if any(not 0 < b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high'] for b in bars):
        raise ValueError('Invalid M1 OHLC prices')
    times = [int(b['time'])+60 for b in bars]  # usable only after candle closes
    if any(a >= b for a,b in zip(times, times[1:])):
        raise ValueError('M1 bars must have unique increasing timestamps')
    features = []
    fast = slow = bars[0]['close']; ranges = []
    for i,b in enumerate(bars):
        fast += 2/10*(b['close']-fast); slow += 2/22*(b['close']-slow)
        prev = bars[max(0,i-1)]['close']
        ranges.append(max(b['high']-b['low'], abs(b['high']-prev), abs(b['low']-prev)))
        if i < 30:
            features.append(None); continue
        sign = lambda x: (x>0)-(x<0)
        momentum = sign(b['close']-prev)
        trend = momentum if momentum == sign(fast-slow) else 0
        prior = bars[i-10:i]
        breakout = 1 if b['close'] > max(x['high'] for x in prior) else -1 if b['close'] < min(x['low'] for x in prior) else 0
        features.append(dict(momentum=momentum, trend=trend, breakout=breakout, atr=sum(ranges[-14:])/14))
    return times, features


def evaluate(folder, times, features, start, end, names, config):
    sims = {name: Simulation(name, **config) for name in names}
    previous = -1; ticks = 0
    with (folder/'ticks.csv').open() as f:
        for row in csv.DictReader(f):
            timestamp = int(row['time_msc'])/1000
            bid, ask = float(row['bid']), float(row['ask'])
            if not all(math.isfinite(x) for x in (timestamp,bid,ask)) or not 0<bid<=ask or timestamp<previous:
                raise ValueError('Ticks must be finite, chronological, and have valid bid/ask')
            previous = timestamp
            if timestamp < start: continue
            if timestamp >= end: break
            ticks += 1
            i = bisect.bisect_right(times, timestamp)-1
            feature = features[i] if i>=0 and timestamp-times[i]<=120 else None
            for sim in sims.values():
                sim.tick(timestamp,bid,ask,i,feature,allow_entry=timestamp<end-60)
    if ticks == 0: raise ValueError('No ticks in selected segment')
    for sim in sims.values(): sim.finish()
    return sims, ticks


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('data', type=Path)
    p.add_argument('--slippage', type=float, default=.02, help='Adverse XAUUSD price units per fill')
    p.add_argument('--commission', type=float, default=0, help='USD round-trip commission per 1.0 lot')
    p.add_argument('--output', type=Path, default=Path('research-results'))
    a = p.parse_args()
    if any(not math.isfinite(v) or v<0 for v in (a.slippage,a.commission)):
        p.error('Costs must be finite and nonnegative')
    metadata = json.loads((a.data/'metadata.json').read_text())
    if metadata['currency']!='USD' or 'XAUUSD' not in metadata['symbol'].upper():
        p.error('Only linear XAUUSD contracts in USD are supported')
    if not math.isfinite(float(metadata['contract_size'])) or float(metadata['contract_size']) <= 0:
        p.error('Contract size must be finite and positive')
    times, features = load_features(a.data/'bars.csv')
    split = times[int(len(times)*.7)]
    config = dict(contract=float(metadata['contract_size']),slippage=a.slippage,commission=a.commission)
    train,ntrain = evaluate(a.data,times,features,times[30],split,['momentum','trend','breakout'],config)
    eligible = [name for name,sim in train.items() if sim.stats()['trades']>=30]
    selected = max(eligible,key=lambda name:train[name].stats()['net_usd']) if eligible else 'momentum'
    test,ntest = evaluate(a.data,times,features,split,times[-1],list(dict.fromkeys([selected,'momentum'])),config)
    stats = test[selected].stats()
    report = dict(selected=selected, split_utc_epoch=split, train_ticks=ntrain, test_ticks=ntest,
                  costs=config,train={n:s.stats() for n,s in train.items()},
                  holdout={n:s.stats() for n,s in test.items()},
                  conclusion='Needs more independent testing; not approved for live trading',
                  limitations=['No latency/order-rejection/margin model; fixed adverse slippage only',
                               'No overnight financing; 60-second maximum positions',
                               'Closed-trade drawdown excludes intra-trade floating drawdown',
                               'One position, at most one entry per M1 bar; not the ten-position live bot'])
    if stats['trades']<30: report['conclusion']='Insufficient holdout trades'
    elif stats['net_usd']<=0: report['conclusion']='Selected strategy lost money on holdout; do not deploy'
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'summary.json').write_text(json.dumps(report,indent=2))
    for name,sim in test.items():
        with (a.output/f'{name}-holdout.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['time','pnl','reason']);w.writeheader();w.writerows(sim.results)
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
