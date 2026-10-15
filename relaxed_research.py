"""Fixed wider-exit research; ten trades per batch, no live orders."""
import argparse
import csv
import json
from pathlib import Path
from aggressive_research import RULES
from backtest import load_features
from gated_research import run, select

# Frozen before evaluating this experiment. No unlimited holds or lot escalation.
PROFILES = ((10,10,300),(15,10,300),(10,20,300),(20,10,900))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('data',type=Path);p.add_argument('--output',type=Path,default=Path('relaxed-results'))
    a=p.parse_args();meta=json.loads((a.data/'metadata.json').read_text())
    if meta['currency']!='USD' or 'XAUUSD' not in meta['symbol'].upper() or float(meta['contract_size'])!=100:raise ValueError('Requires USD XAUUSD contract size 100')
    times,features=load_features(a.data/'bars.csv');split1=times[len(times)//2];split2=times[int(len(times)*.7)]
    segments=[('development',times[30],split1),('check',split1,split2),('later',split2,times[-1])]
    results={n:{} for n,lo,hi in segments};a.output.mkdir(parents=True,exist_ok=False)
    for target,loss,hold in PROFILES:
        configs={f'{r}-tp{target}-sl{loss}-hold{hold}':(r,'range',target) for r in RULES}
        for label,lo,hi in segments:
            sims=run(a.data/'ticks.csv',times,features,lo,hi,configs,loss_limit=loss,max_hold=hold)
            for name,sim in sims.items():
                results[label][name]=sim.stats()
                with (a.output/f'{label}-{name}.csv').open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=['time','pnl','reason','opened','closed']);w.writeheader();w.writerows(sim.results)
        print('Finished profile',target,loss,hold,flush=True)
    selected=select([results['development'],results['check']])
    report=dict(profiles=PROFILES,results=results,selected_using_earlier_segments=selected,
                assumptions=dict(batch_positions=10,lot=.01,latency_per_order=.1,slippage_per_fill=.02,commission=0,
                                 gate='Ten-second range at least 6x spread; five-second move at least 1x spread'),
                conclusion='No candidate passed two positive earlier segments with 50 batches each' if selected is None else 'Exploratory candidate only; independent validation required',
                limitations=['Reused data; multiple comparisons; no untouched validation',
                             'No margin, liquidity, rejection, financing, or floating-drawdown model',
                             'Larger loss thresholds increase per-batch exposure; no lot escalation',
                             'No quotes during gaps means delayed fills; segment end liquidates at last quote'])
    (a.output/'summary.json').write_text(json.dumps(report,indent=2))
    with (a.output/'comparison.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['rule','segment','batches','net_usd','win_rate','profit_factor','drawdown','all_ten'])
        for label,segment in results.items():
            for name,s in segment.items():w.writerow([name,label,s['batches'],s['net_usd'],s['win_rate'],s['profit_factor'],s['max_closed_drawdown_usd'],s['all_batches_ten_positions']])
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
