import unittest
from aggressive_research import Batch


class AggressiveTests(unittest.TestCase):
    def open_ten(self, side=1):
        sim=Batch('test',latency=.1,slippage=.02)
        sim.tick(0,100,100.2,side)
        self.assertFalse(sim.entries)
        for i in range(10):sim.tick(1+i,100,100.2,side)
        self.assertEqual(sim.state,'holding')
        self.assertEqual(len(sim.entries),10)
        return sim

    def test_flat_quotes_costs_on_all_ten_positions_both_directions(self):
        for side in (1,-1):
            sim=self.open_ten(side)
            sim.tick(70,100,100.2,side)
            self.assertEqual(sim.state,'closing')
            for i in range(10):sim.tick(71+i,100,100.2,side)
            self.assertEqual(sim.state,'flat')
            self.assertEqual(len(sim.results),1)
            self.assertAlmostEqual(sim.results[0]['pnl'],-2.4)
            self.assertEqual(sim.results[0]['opened'],10)
            self.assertEqual(sim.results[0]['closed'],10)

    def test_profit_trigger_is_not_guaranteed_realized_profit(self):
        sim=self.open_ten()
        sim.tick(11,100.5,100.7,1)
        self.assertEqual(sim.state,'closing')
        self.assertFalse(sim.results)
        for i in range(10):sim.tick(12+i,99.9,100.1,1)
        self.assertEqual(sim.results[0]['reason'],'profit')
        self.assertLess(sim.results[0]['pnl'],0)

    def test_loss_closes_entire_batch_without_new_entries(self):
        sim=self.open_ten()
        sim.tick(11,99,99.2,1)
        for i in range(10):sim.tick(12+i,99,99.2,1)
        self.assertEqual(sim.results[0]['reason'],'loss')
        self.assertEqual(sim.results[0]['closed'],10)
        self.assertFalse(sim.entries)
