import unittest
from aggressive_research import Batch
from gated_research import allowed, candidates, select


class GatedTests(unittest.TestCase):
    def test_gates_require_move_and_trend_conditions(self):
        self.assertTrue(allowed('impulse',1,.8,1,.2,0))
        self.assertFalse(allowed('impulse',1,.4,1,.2,0))
        self.assertTrue(allowed('range',-1,-.3,1.3,.2,0))
        self.assertFalse(allowed('range',-1,-.1,1.3,.2,0))
        self.assertFalse(allowed('trend',1,.6,1.3,.2,-1))
        self.assertTrue(allowed('trend',1,.6,1.3,.2,1))
        self.assertEqual(len(candidates()),18)

    def test_selection_requires_two_positive_segments_and_sample_size(self):
        a={'one':dict(batches=100,net_usd=100),'two':dict(batches=49,net_usd=100)}
        b={'one':dict(batches=100,net_usd=-1),'two':dict(batches=100,net_usd=100)}
        self.assertIsNone(select([a,b]))
        b['one']['net_usd']=1
        self.assertEqual(select([a,b]),'one')

    def test_higher_target_and_entry_gate_cannot_disable_close(self):
        sim=Batch('test',profit_target=5)
        sim.tick(0,100,100.2,1)
        for i in range(10):sim.tick(i+1,100,100.2,1)
        sim.tick(11,100.5,100.7,1,allow_entry=False)
        self.assertEqual(sim.state,'holding')
        sim.tick(12,101,101.2,1,allow_entry=False)
        self.assertEqual(sim.state,'closing')
        for i in range(10):sim.tick(13+i,101,101.2,1,allow_entry=False)
        self.assertEqual(sim.results[0]['closed'],10)
        self.assertGreater(sim.results[0]['pnl'],5)
