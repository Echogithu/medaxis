"""用实际基线记录制造缺题/伪造能力等错误，保证复核器不会给虚假通过。"""
import copy
import unittest

from baseline_verify import BASELINE, summarize
from verify import DEFAULT, load
from score import score


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load(DEFAULT / 'dataset.json')
        self.inputs = load(DEFAULT / 'inputs.json')
        self.raw = load(BASELINE / 'full/observations.json')

    def test_all_records_included_without_mixed_overall_grade(self):
        result = summarize(self.dataset, self.inputs, self.raw)
        self.assertEqual(52, result['recorded_cases'])
        self.assertIsNone(result['all_52_semantic_accuracy'])
        self.assertEqual(16, result['capability_absent'])

    def test_missing_record_fails(self):
        self.raw['rows'].pop()
        with self.assertRaises(ValueError): summarize(self.dataset, self.inputs, self.raw)

    def test_duplicate_record_fails(self):
        self.raw['rows'][1] = copy.deepcopy(self.raw['rows'][0])
        with self.assertRaises(ValueError): summarize(self.dataset, self.inputs, self.raw)

    def test_unknown_cannot_fill_missing_capability(self):
        row = next(r for r in self.raw['rows'] if r['family'] == 'applicability')
        row['label'] = 'unknown'
        with self.assertRaises(ValueError): summarize(self.dataset, self.inputs, self.raw)

    def test_execution_error_is_not_scored_as_success(self):
        next(r for r in self.raw['rows'] if r['family'] == 'query_specificity')['status'] = 'execution_error'
        with self.assertRaises(ValueError): summarize(self.dataset, self.inputs, self.raw)

    def test_invented_acceptance_does_not_match_raw(self):
        row = next(r for r in self.raw['rows'] if r['family'] == 'version_scope')
        row['label'] = 'version_match'
        with self.assertRaises(ValueError): summarize(self.dataset, self.inputs, self.raw)

    def test_altered_statement_is_detected(self):
        next(r for r in self.raw['rows'] if r['family'] == 'statement_support')['raw_output'][0]['claim'] = '被修改的陈述'
        with self.assertRaises(ValueError): summarize(self.dataset, self.inputs, self.raw)

    def test_semantic_verification_cannot_be_claimed(self):
        self.raw['rows'][0]['semantic_judgment_verified'] = True
        with self.assertRaises(ValueError): summarize(self.dataset, self.inputs, self.raw)

    def test_36_records_cannot_be_scored_as_full_52(self):
        predictions = {'predictions': [{'id': r['id'], 'label': r['label']} for r in self.raw['rows'] if r['status'] == 'executed']}
        with self.assertRaises(ValueError): score(self.dataset, predictions)


if __name__ == '__main__':
    unittest.main(verbosity=2)
