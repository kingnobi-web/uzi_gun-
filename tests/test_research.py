import csv
from pathlib import Path
import tempfile
import unittest
from research import ResearchSimulation, features_for, select_candidate


class ResearchTests(unittest.TestCase):
    def test_no_profitable_training_candidate_means_no_selection(self):
        self.assertIsNone(select_candidate({'a':dict(trades=100,net_usd=-1), 'b':dict(trades=10,net_usd=50)}))
        self.assertEqual(select_candidate({'a':dict(trades=100,net_usd=1), 'b':dict(trades=50,net_usd=2)}),'b')

    def test_longer_hold_does_not_use_one_minute_timeout(self):
        sim=ResearchSimulation('fade_move',300,contract=100,slippage=.02)
        feature=dict(fade_move=1,atr=2)
        sim.tick(0,100,100.1,1,feature)
        sim.tick(60,100,100.1,2,feature)
        self.assertIsNotNone(sim.position)
        sim.tick(300,100,100.1,3,feature)
        self.assertIsNone(sim.position)
        self.assertEqual(sim.results[0]['reason'],'timeout')
        self.assertAlmostEqual(sim.results[0]['pnl'],-.14)

    def test_wide_spread_skips_entry(self):
        sim=ResearchSimulation('fade_move',300,contract=100)
        sim.tick(0,100,101,1,dict(fade_move=1,atr=2))
        self.assertIsNone(sim.position)

    def test_future_candles_cannot_change_earlier_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,changed in [('original',False),('changed',True)]:
                with (root/name).open('w',newline='') as f:
                    w=csv.writer(f);w.writerow(['time','open','high','low','close'])
                    for i in range(220):
                        price=2000+i*.1+(100 if changed and i>150 else 0)
                        w.writerow([1700000040+i*60,price,price+.2,price-.2,price+.1])
            ta,fa=features_for(root/'original');tb,fb=features_for(root/'changed')
            self.assertEqual(fa[:151],fb[:151])
            self.assertEqual(ta[100],1700000040+101*60)
