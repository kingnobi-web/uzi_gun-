import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from backtest import Simulation, load_features


class BacktestTests(unittest.TestCase):
    def test_flat_market_loses_spread_slippage_and_commission_both_sides(self):
        for side in (1, -1):
            sim=Simulation('momentum',100,slippage=.02,commission=7)
            sim.tick(0,100,100.2,1,dict(momentum=side,atr=2))
            sim.tick(60,100,100.2,2,None)
            self.assertAlmostEqual(sim.results[0]['pnl'],-.31)
            self.assertEqual(sim.results[0]['reason'],'timeout')

    def test_target_and_gap_stop_use_actual_quote(self):
        sim=Simulation('momentum',100,slippage=0)
        sim.tick(0,100,100.2,1,dict(momentum=1,atr=1))
        sim.tick(1,102,102.2,1,None)
        self.assertAlmostEqual(sim.results[0]['pnl'],1.8)
        self.assertEqual(sim.results[0]['reason'],'target')
        sim.tick(2,100,100.2,2,dict(momentum=1,atr=1))
        sim.tick(3,97,97.2,2,None)
        self.assertAlmostEqual(sim.results[1]['pnl'],-3.2)
        self.assertEqual(sim.results[1]['reason'],'stop')

    def test_no_same_candle_reentry(self):
        sim=Simulation('momentum',100,slippage=0)
        feature=dict(momentum=1,atr=1)
        sim.tick(0,100,100.2,1,feature)
        sim.tick(1,102,102.2,1,feature)
        sim.tick(2,102,102.2,1,feature)
        self.assertIsNone(sim.position)

    def test_chronological_holdout_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'metadata.json').write_text(json.dumps(dict(symbol='XAUUSDm',currency='USD',contract_size=100)))
            with (root/'bars.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['time','open','high','low','close'])
                for i in range(1000):
                    price=2000+i*.1
                    w.writerow([1700000040+i*60,price,price+.1,price-.1,price+.05])
            times,features=load_features(root/'bars.csv')
            self.assertEqual(times[0],1700000100)
            # Future price changes cannot change an earlier feature.
            self.assertEqual(features[40]['momentum'],1)
            with (root/'ticks.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['time_msc','bid','ask'])
                for i in range(1000):
                    for sec in (0,30,59):
                        price=2000+i*.1+sec*.001
                        w.writerow([(1700000040+i*60+sec)*1000,price,price+.05])
            result=subprocess.run([sys.executable,'backtest.py',str(root),'--output',str(root/'out')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertGreater(report['test_ticks'],0)
            self.assertEqual(report['split_utc_epoch'],times[700])
            with (root/'out'/f"{report['selected']}-holdout.csv").open() as f:
                rows=list(csv.DictReader(f))
            self.assertTrue(rows)
            self.assertTrue(all(float(r['time'])>=times[700] for r in rows))
            self.assertIn('not approved',report['conclusion'])

    def test_export_writes_metadata_bars_and_ticks_without_trading(self):
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        from datetime import datetime, timezone
        import export_data
        now=int(datetime.now(timezone.utc).timestamp())//60*60
        bars=[dict(time=now-60*(201-i),open=2000,high=2001,low=1999,close=2000) for i in range(201)]
        def ticks(symbol,start,end,kind):
            return [dict(time_msc=int(start.timestamp()*1000),bid=2000,ask=2000.1)]
        fake=NS(initialize=lambda:True,account_info=lambda:NS(currency='USD'),
                symbol_select=lambda *a:True,symbol_info=lambda s:NS(trade_contract_size=100),
                copy_rates_range=lambda *a:bars,copy_ticks_range=ticks,
                TIMEFRAME_M1=1,COPY_TICKS_ALL=0,shutdown=lambda:None)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'data'
            with patch.dict(sys.modules,{'MetaTrader5':fake}),patch.object(sys,'argv',['export_data.py','--days','2','--output',str(out)]):
                export_data.main()
            metadata=json.loads((out/'metadata.json').read_text())
            self.assertEqual(metadata['ticks'],8)
            self.assertIn('actual_tick_start_utc', metadata)
            self.assertIn('actual_tick_end_utc', metadata)
            self.assertFalse(metadata['requested_start_missing_over_one_day'])
            self.assertNotIn('account',metadata)
            self.assertEqual(len((out/'bars.csv').read_text().splitlines()),202)
            # A long request returning only recent ticks must flag partial coverage.
            fake.copy_ticks_range = lambda symbol,start,end,kind: ticks(symbol,start,end,kind) if start.timestamp() >= now-3*86400 else []
            partial=Path(tmp)/'partial'
            with patch.dict(sys.modules,{'MetaTrader5':fake}),patch.object(sys,'argv',['export_data.py','--days','7','--output',str(partial)]):
                export_data.main()
            self.assertTrue(json.loads((partial/'metadata.json').read_text())['requested_start_missing_over_one_day'])
