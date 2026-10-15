import unittest
import numpy as np
from fitted_research import samples, labels, tree_json, predict, replay


class FittedTests(unittest.TestCase):
    def test_future_ticks_cannot_change_past_features(self):
        times=np.arange(0,200,dtype=float)
        bids=100+np.sin(times/10)
        original=np.column_stack([times,bids,bids+.2])
        changed=original.copy();changed[151:,1:]+=50
        ia,xa=samples(original);ib,xb=samples(changed)
        mask=original[ia,0]<=150
        np.testing.assert_array_equal(ia,ib)
        np.testing.assert_allclose(xa[mask],xb[mask])

    def test_labels_use_future_only_for_supervision(self):
        ticks=np.array([[0,100,100.2],[30,101,101.2],[60,99,99.2]],dtype=float)
        valid,y=labels(ticks,np.array([0,1,2]))
        np.testing.assert_array_equal(valid,[True,True,False])
        self.assertEqual(y[0],1);self.assertEqual(y[1],-1)

    def test_json_predictions_match_sklearn_and_do_not_fit(self):
        from sklearn.tree import DecisionTreeClassifier
        x=np.array([[0,0],[0,1],[1,0],[1,1],[2,1],[2,0]],dtype=float)
        y=np.array([0,0,1,1,-1,-1])
        model=DecisionTreeClassifier(random_state=42).fit(x,y)
        exported=tree_json(model)
        np.testing.assert_array_equal(predict(exported,x,0),model.predict(x))
        # JSON inference needs no classifier or training labels.
        model=None
        np.testing.assert_array_equal(predict(exported,x,0),y)

    def test_replay_excludes_training_dates(self):
        times=np.arange(0,100,dtype=float)
        ticks=np.column_stack([times,np.full(100,100.),np.full(100,100.2)])
        indexes=np.array([30,35,40,45,50,55,60,65,70,75,80,85,90,95])
        sim=replay(ticks,indexes,np.ones(len(indexes),dtype=int),start=101)
        self.assertFalse(sim.results)

    def test_frozen_evaluation_cli_never_modifies_model(self):
        import csv,json,subprocess,sys,tempfile
        from pathlib import Path
        from fitted_research import FEATURE_NAMES
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'metadata.json').write_text(json.dumps(dict(currency='USD',symbol='XAUUSDm',contract_size=100)))
            with (root/'ticks.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['time_msc','bid','ask'])
                for i in range(1500):w.writerow([(1700000000+i)*1000,100,100.2])
            frozen=dict(features=FEATURE_NAMES,training_end=1699999900,
                        tree=dict(left=[-1],right=[-1],feature=[-2],threshold=[-2],probabilities=[[1]],classes=[1]),confidence=.8)
            model=root/'model.json';model.write_text(json.dumps(frozen));before=model.read_bytes()
            result=subprocess.run([sys.executable,'fitted_research.py','evaluate',str(root),'--model',str(model),'--output',str(root/'out')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertEqual(report['mode'],'frozen_forward_evaluation')
            self.assertGreater(report['stats']['batches'],0)
            self.assertTrue(report['stats']['all_batches_ten_positions'])
            self.assertEqual(model.read_bytes(),before)
