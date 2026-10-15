import unittest
from aggressive_research import Batch
from relaxed_research import PROFILES


class RelaxedTests(unittest.TestCase):
    def open_batch(self):
        sim=Batch('test',profit_target=10,loss_limit=20,max_hold=300)
        sim.tick(0,100,100.2,1)
        for i in range(10):sim.tick(i+1,100,100.2,1)
        return sim

    def test_wider_loss_limit_does_not_close_at_old_limit(self):
        sim=self.open_batch()
        sim.tick(11,99.5,99.7,1)
        self.assertEqual(sim.state,'holding')
        sim.tick(12,98,98.2,1)
        self.assertEqual(sim.state,'closing')
        self.assertEqual(sim.reason,'loss')

    def test_timeout_remains_bounded(self):
        sim=self.open_batch()
        sim.tick(70,100,100.2,1)
        self.assertEqual(sim.state,'holding')
        sim.tick(310,100,100.2,1)
        self.assertEqual(sim.state,'closing')
        self.assertEqual(sim.reason,'timeout')
        self.assertEqual(len(PROFILES),4)
