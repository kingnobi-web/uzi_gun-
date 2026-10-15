import unittest
from candle_research import evaluate


def bar(t,open_,high,low,close):
    return dict(time=t,open=open_,high=high,low=low,close=close)


class CandleTests(unittest.TestCase):
    def test_signal_waits_until_next_candle_and_pays_spread_and_slippage(self):
        bids=[bar(0,100,100,100,100),bar(60,100,100,100,100),bar(120,100,100,100,100)]
        asks=[bar(0,100.1,100.1,100.1,100.1),bar(60,100.1,100.1,100.1,100.1),bar(120,100.1,100.1,100.1,100.1)]
        sim=evaluate(bids,asks,[dict(fade_move=1,atr=2),None,None],'fade_move',60)
        self.assertEqual(len(sim.results),1)
        self.assertEqual(sim.results[0]['time'],120)
        self.assertEqual(sim.results[0]['reason'],'timeout')
        self.assertAlmostEqual(sim.results[0]['pnl'],-.14)

    def test_both_levels_hit_assumes_stop_first_for_buy_and_sell(self):
        for side in (1,-1):
            bids=[bar(0,100,100,100,100),bar(60,100,105,95,100)]
            asks=[bar(0,100.1,100.1,100.1,100.1),bar(60,100.1,105.1,95.1,100.1)]
            sim=evaluate(bids,asks,[dict(fade_move=side,atr=2),None],'fade_move',300)
            self.assertEqual(sim.results[0]['reason'],'stop_or_ambiguous')
            self.assertAlmostEqual(sim.results[0]['pnl'],-2.02)

    def test_entry_skips_session_gap(self):
        bids=[bar(0,100,100,100,100),bar(3600,100,100,100,100)]
        asks=[bar(0,100.1,100.1,100.1,100.1),bar(3600,100.1,100.1,100.1,100.1)]
        self.assertFalse(evaluate(bids,asks,[dict(fade_move=1,atr=2),None],'fade_move',300).results)
