"""Ten-position tick research. Does not connect to MT5 or place orders."""
import argparse
import csv
from collections import deque
import json
import math
from pathlib import Path

RULES = ('momentum_5s', 'reversal_5s', 'tick_balance_10s')


class Batch:
    def __init__(self, rule, latency=.1, slippage=.02, profit_target=1.5, loss_limit=5, max_hold=60):
        self.rule, self.latency, self.slippage = rule, latency, slippage
        self.profit_target, self.loss_limit, self.max_hold = profit_target, loss_limit, max_hold
        self.state='flat';self.entries=[];self.side=0;self.next_action=0
        self.started=0;self.close_index=0;self.realized=0;self.results=[];self.reason=''
        self.check_at=0;self.last_quote=None

    def fill_close(self,bid,ask):
        entry=self.entries[self.close_index]
        price=bid-self.slippage if self.side==1 else ask+self.slippage
        # 0.01 lot * 100 contract units = one ounce per position.
        self.realized+=(price-entry)*self.side
        self.close_index+=1

    def complete(self,t):
        self.results.append(dict(time=t,pnl=self.realized,reason=self.reason,
                                 opened=len(self.entries),closed=self.close_index))
        self.entries=[];self.realized=0;self.close_index=0;self.state='flat'

    def tick(self,t,bid,ask,signal,allow_entry=True):
        self.last_quote=(t,bid,ask)
        if self.state=='flat':
            if allow_entry and signal:
                self.side=signal;self.state='opening';self.next_action=t+self.latency
            return
        if self.state=='opening':
            if t>=self.next_action:
                self.entries.append(ask+self.slippage if self.side==1 else bid-self.slippage)
                self.next_action=t+self.latency
                if len(self.entries)==10:
                    self.started=t;self.state='holding';self.check_at=t
            return
        if self.state=='holding' and t>=self.check_at:
            quote=bid if self.side==1 else ask
            pnl=sum((quote-entry)*self.side for entry in self.entries)
            reason='profit' if pnl>=self.profit_target else 'loss' if pnl<=-self.loss_limit else 'timeout' if t-self.started>=self.max_hold else None
            self.check_at=t+.2
            if reason:
                self.reason=reason;self.state='closing';self.next_action=t+self.latency
            return
        if self.state=='closing' and t>=self.next_action:
            self.fill_close(bid,ask);self.next_action=t+self.latency
            if self.close_index==len(self.entries):self.complete(t)

    def finish(self):
        if self.entries:
            t,bid,ask=self.last_quote
            self.reason='segment_end'
            while self.close_index<len(self.entries):self.fill_close(bid,ask)
            self.complete(t)

    def stats(self):
        vals=[r['pnl'] for r in self.results];wins=sum(x for x in vals if x>0);loss=-sum(x for x in vals if x<0)
        equity=peak=drawdown=0
        for value in vals:
            equity+=value;peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
        return dict(batches=len(vals),positions=sum(r['opened'] for r in self.results),
                    net_usd=round(sum(vals),2),win_rate=round(sum(x>0 for x in vals)/len(vals),4) if vals else 0,
                    profit_factor=round(wins/loss,3) if loss else None,
                    max_closed_drawdown_usd=round(drawdown,2),
                    all_batches_ten_positions=all(r['opened']==10 and r['closed']==10 for r in self.results))


def run(path,start,end,latency=.1,slippage=.02):
    sims={r:Batch(r,latency,slippage) for r in RULES}
    recent=deque();balance=0;previous_mid=None;previous_time=None
    with path.open() as f:
        for row in csv.DictReader(f):
            t=int(row['time_msc'])/1000;bid=float(row['bid']);ask=float(row['ask'])
            if not all(math.isfinite(v) for v in (t,bid,ask)) or not 0<bid<=ask:raise ValueError('Invalid tick')
            if previous_time is not None and t<previous_time:raise ValueError('Unsorted ticks')
            if t<start:continue
            if t>=end:break
            mid=(bid+ask)/2
            if previous_time is not None and t-previous_time>30:
                recent.clear();balance=0;previous_mid=None
            change=0 if previous_mid is None else (mid>previous_mid)-(mid<previous_mid)
            recent.append((t,mid,change));balance+=change
            while recent and recent[0][0]<t-10:
                balance-=recent.popleft()[2]
            old5=next((m for ts,m,c in recent if ts>=t-5),mid)
            sign=lambda x:(x>0)-(x<0)
            signals=dict(momentum_5s=sign(mid-old5),reversal_5s=-sign(mid-old5),tick_balance_10s=sign(balance))
            warm=len(recent)>1 and t-recent[0][0]>=9
            for name,sim in sims.items():sim.tick(t,bid,ask,signals[name],allow_entry=warm and t<end-120)
            previous_mid=mid;previous_time=t
    for sim in sims.values():sim.finish()
    return sims


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('data',type=Path);p.add_argument('--output',type=Path,default=Path('aggressive-results'))
    p.add_argument('--latency',type=float,default=.1,help='Minimum seconds per simulated order')
    p.add_argument('--slippage',type=float,default=.02,help='Adverse gold-price units per fill')
    a=p.parse_args()
    if any(not math.isfinite(v) or v<0 for v in (a.latency,a.slippage)):p.error('Invalid execution assumptions')
    metadata=json.loads((a.data/'metadata.json').read_text())
    if metadata['currency']!='USD' or 'XAUUSD' not in metadata['symbol'].upper() or float(metadata['contract_size'])!=100:raise ValueError('Requires USD gold contract size 100')
    with (a.data/'bars.csv').open() as f:bars=list(csv.DictReader(f))
    split=int(bars[int(len(bars)*.7)]['time'])+60;start=int(bars[0]['time'])+60;end=int(bars[-1]['time'])+60
    report=dict(rules=list(RULES),positions_per_batch=10,lot_per_position=.01,profit_trigger=1.5,loss_trigger=-5,max_hold_seconds=60,
                latency_per_order=a.latency,slippage_per_fill=a.slippage,commission=0,
                split_epoch=split,earlier={},later={},
                limitations=['Already viewed dataset: exploratory only, not independent validation',
                             'Fixed delay and slippage; no rejection, margin, financing, or liquidity model',
                             'Signals use midpoint tick changes, not actual buyer/seller volume',
                             'Same direction for all ten positions; no added diversification',
                             'Stops and profit triggers checked after all ten entries; thresholds can be exceeded',
                             'No quote means no fill; exits across session gaps can be delayed',
                             'Segment end is forced liquidation at last quote'])
    a.output.mkdir(parents=True,exist_ok=False)
    for label,lo,hi in [('earlier',start,split),('later',split,end)]:
        sims=run(a.data/'ticks.csv',lo,hi,a.latency,a.slippage)
        for name,sim in sims.items():
            report[label][name]=sim.stats()
            with (a.output/f'{label}-{name}.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['time','pnl','reason','opened','closed']);w.writeheader();w.writerows(sim.results)
    report['conclusion']='None passed: all three rules lost money in both segments' if all(s['net_usd']<0 for segment in ('earlier','later') for s in report[segment].values()) else 'Exploratory results only; requires new independent validation'
    (a.output/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
