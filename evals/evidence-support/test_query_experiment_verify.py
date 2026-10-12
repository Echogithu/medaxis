"""离线记录篡改反例；只替换读取结果，不改真实冻结资产或归档。"""
import copy
import unittest
from unittest.mock import patch
import query_experiment_verify as verifier
from verify import load as original_load


class VerificationTest(unittest.TestCase):
    def reject(self, path_suffix, change):
        def altered(path):
            data = original_load(path)
            if str(path).replace('\\', '/').endswith(path_suffix):
                data = copy.deepcopy(data)
                change(data)
            return data
        with patch.object(verifier, 'load', altered), self.assertRaises(ValueError):
            verifier.verify_all()

    def test_actual_archives_recompute(self):
        result = verifier.verify_all()
        self.assertEqual(24, result['development']['correct'])
        self.assertEqual(15, result['regression']['correct'])
        self.assertEqual([], result['repeat_prediction_differences'])

    def test_changed_score_rejected(self):
        self.reject('query-assessment-v3/dev-full/score.json', lambda d: d.update(accuracy=.9))

    def test_invented_http_zero_rejected(self):
        self.reject('query-assessment-v3/dev-full/observations.json', lambda d: d.update(requests=[]))

    def test_missing_group_rejected(self):
        self.reject('query-assessment-v3/dev-full/observations.json', lambda d: d['groups'].pop())

    def test_invented_clinical_verified_rejected(self):
        self.reject('query-assessment-v3/dev-full/observations.json', lambda d: d.update(clinical_correctness_verified=True))

    def test_gold_injection_into_execution_input_rejected(self):
        self.reject('query-assessment-v3/dev-full/execution-input.json', lambda d: d['groups'][0]['cases'][0].update(expected_label='answers'))

    def test_inherited_prediction_rewrite_rejected(self):
        def change(data): data['groups'][0]['assessment']['candidates'][0]['label'] = 'answers'
        self.reject('query-assessment-v3/dev-full/observations.json', change)


if __name__ == '__main__': unittest.main()
