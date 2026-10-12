"""对照器必须分开记录覆盖收益、排名退步与无答案候选。"""
import unittest
from run import changes,cached_timing


def row(cid,coverage=1.,mrr=1.,qualifier=1.,negative=None):
    return {'id':cid,'score':{'complete_evidence':None if negative is not None else bool(coverage),
            'evidence_recall_at_k':coverage,'mrr':mrr,'qualifier_recall':qualifier,
            'unsupported_candidate_returned':negative}}


class ComparisonTests(unittest.TestCase):
    def test_missing_case_rejected(self):
        with self.assertRaises(ValueError):changes({'cases':[row('A')]},{'cases':[]})

    def test_coverage_gain_does_not_hide_other_ranking_loss(self):
        before={'cases':[row('A',0.,0.,0.),row('B')]}
        after={'cases':[row('A'),row('B',mrr=.5)]}
        self.assertEqual((['A'],[],['B'],[]),changes(before,after))

    def test_qualifier_loss_is_regression_even_when_coverage_unchanged(self):
        self.assertEqual(([],['A'],[],[]),changes({'cases':[row('A')]},{'cases':[row('A',qualifier=0.)]}))

    def test_no_answer_candidate_gain_and_loss_separate(self):
        before={'cases':[row('A',negative=True),row('B',negative=False)]}
        after={'cases':[row('A',negative=False),row('B',negative=True)]}
        self.assertEqual(([],['B'],[],['A']),changes(before,after))

    def test_timing_uses_nearest_rank_and_rejects_nan(self):
        result={'cases':[{'retrieval_with_cached_query_vector_ms':v} for v in range(1,21)]}
        timing=cached_timing(result)
        self.assertEqual(10.5,timing['p50_ms']);self.assertEqual(19,timing['p95_ms'])
        result['cases'][0]['retrieval_with_cached_query_vector_ms']=float('nan')
        with self.assertRaises(ValueError):cached_timing(result)


if __name__=='__main__':unittest.main()
