"""配对评分拒绝漏题、伪造分类和排序，区分部分回答与另一用途。"""
import copy
import json
import unittest
from query_experiment import groups_from_inputs, quality, TASK
from verify import load
from app.services.query_requirements import parse_assessment, rank_assessed


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.dataset = {'cases': [], 'gold_units': []}
        self.sources = []
        checks = [[True, True], [True, False], [False, False]]
        quotes = ['甲条件完整。乙条件完整。', '甲条件完整。', '另一用途原文。']
        for i, label in enumerate(['answers', 'partial_answer', 'does_not_answer']):
            cid = str(i)
            self.dataset['cases'].append({'id': cid, 'family': 'query_specificity', 'query': '甲乙条件',
                                         'expected_label': label, 'candidate_evidence_id': cid})
            self.dataset['gold_units'].append({'id': cid, 'quote': quotes[i]})
            self.sources.append({'id': cid, 'excerpt': quotes[i]})
        raw = {'requirements': ['甲条件', '乙条件'], 'candidates': [
            {'id': str(i), 'checks': [{'covered': bit, 'quote': ('甲条件完整' if j == 0 else '乙条件完整') if bit else None,
                                     'reason': '覆盖' if bit else '不覆盖'} for j, bit in enumerate(bits)]}
            for i, bits in enumerate(checks)]}
        content = json.dumps(raw, ensure_ascii=False)
        assessed = parse_assessment(content, self.sources)
        assessed.update(status='assessed', raw_output=content)
        self.observations = {'groups': [{'id': 'group', 'query': '甲乙条件', 'case_ids': ['0', '1', '2'],
            'before_order': ['2', '1', '0'], 'after_order': rank_assessed(assessed), 'assessment': assessed}]}

    def test_known_correct_and_rank_improvement(self):
        result = quality(self.dataset, self.observations)
        self.assertEqual(3, result['correct'])
        self.assertEqual(1, result['accuracy'])
        self.assertEqual(1, result['macro_f1'])
        self.assertEqual(1, result['after_retained']['partial_answer'])
        self.assertEqual(0, result['after_retained']['does_not_answer'])
        self.assertEqual(1, result['ndcg_after'])
        self.assertLess(result['ndcg_before'], result['ndcg_after'])

    def test_missing_result_rejected(self):
        with self.assertRaises(ValueError): quality(self.dataset, {'groups': []})

    def test_duplicate_group_rejected(self):
        self.observations['groups'] *= 2
        with self.assertRaises(ValueError): quality(self.dataset, self.observations)

    def test_forged_derived_label_rejected(self):
        self.observations['groups'][0]['assessment']['candidates'][1]['label'] = 'answers'
        with self.assertRaises(ValueError): quality(self.dataset, self.observations)

    def test_forged_rank_rejected(self):
        self.observations['groups'][0]['after_order'] = ['0', '2']
        with self.assertRaises(ValueError): quality(self.dataset, self.observations)

    def test_failure_unknown_is_in_denominator(self):
        group = self.observations['groups'][0]
        group['assessment'] = {'status': 'assessment_error', 'candidates': [
            {'id': str(i), 'label': 'unknown', 'retain': True, 'coverage_fraction': None, 'missing_requirements': []}
            for i in range(3)]}
        group['after_order'] = ['0', '1', '2']
        result = quality(self.dataset, self.observations)
        self.assertEqual(3, result['cases'])
        self.assertEqual(0, result['accuracy'])
        self.assertEqual(3, result['unknown_count'])
        self.assertEqual(1, result['assessment_errors'])

    def test_wrong_model_prediction_is_scored_wrong(self):
        group = self.observations['groups'][0]
        raw = json.loads(group['assessment']['raw_output'])
        raw['candidates'][1]['checks'][0] = {'covered': False, 'quote': None, 'reason': '模型错误认为不覆盖'}
        content = json.dumps(raw, ensure_ascii=False)
        group['assessment'] = dict(parse_assessment(content, self.sources), status='assessed', raw_output=content)
        group['after_order'] = rank_assessed(group['assessment'])
        result = quality(self.dataset, self.observations)
        self.assertEqual(2, result['correct'])
        self.assertEqual(0, result['after_retained']['partial_answer'])

    def test_real_inputs_group_without_gold(self):
        groups = groups_from_inputs(load(TASK / 'query-development-v2/inputs.json'))
        self.assertEqual(8, len(groups))
        self.assertTrue(all(len(g['cases']) == 3 for g in groups))
        self.assertTrue(all('expected_label' not in case for g in groups for case in g['cases']))
        old = groups_from_inputs(load(TASK / 'frozen-v4/inputs.json'))
        self.assertEqual(8, len(old))
        self.assertTrue(all(len(g['cases']) == 2 for g in old))


if __name__ == '__main__': unittest.main()
