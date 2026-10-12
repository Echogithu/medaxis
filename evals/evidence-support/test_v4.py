"""验证审核修订不会补造事实、覆盖旧版或混用运行输入。"""
import copy
import unittest

from revise_v4 import OUT, revise, verify_revision
from verify import DEFAULT, load, validate
from baseline_verify import BASELINE, verify, summarize


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.old = load(DEFAULT / 'dataset.json')
        self.before = copy.deepcopy(self.old)
        self.new, self.mapping = revise(self.old)
        self.cases = {c['display_id']: c for c in self.new['cases']}

    def test_original_unchanged_and_counts(self):
        self.assertEqual(self.before, self.old)
        self.assertEqual(53, len(self.new['cases']))
        self.assertEqual(5, sum(r['kind'] == 'revised' for r in self.mapping))
        self.assertEqual(47, sum(r['kind'] == 'unchanged' for r in self.mapping))
        self.assertEqual(self.old['gold_units'], self.new['gold_units'])

    def test_missing_condition_stays_missing_and_unknown(self):
        case = self.cases['E05-A-unknown']
        self.assertEqual('unknown', case['expected_label'])
        self.assertNotIn('other_chronic_resp_disease', case['synthetic_context'])

    def test_complete_case_is_separate_and_not_extra_pair(self):
        case = self.cases['E05-A-complete']
        self.assertEqual('applicable', case['expected_label'])
        self.assertIs(False, case['synthetic_context']['other_chronic_resp_disease'])
        self.assertNotEqual(self.cases['E05-A-unknown']['id'], case['id'])
        self.assertIsNone(case['pair_id'])

    def test_scope_does_not_claim_lactation_or_approve_drug(self):
        purpose = self.cases['E06-A+']['synthetic_context']['purpose']
        self.assertIn('不评价哺乳条件', purpose)
        self.assertIn('不批准用药', purpose)
        self.assertEqual('applicable', self.cases['E06-A+']['expected_label'])

    def test_version_request_is_single_and_gold_change_is_explicit(self):
        for display in ['E05-V', 'E07-V']:
            self.assertNotIn('2025', self.cases[display]['query'])
            self.assertEqual('2028年版', self.cases[display]['required_edition'])
        row = next(r for r in self.mapping if r['old_display_id'] == 'E05-A+')
        self.assertEqual(row['old_id'], row['new_id'])
        self.assertEqual(('applicable', 'unknown'), (row['old_label'], row['new_label']))
        self.assertIs(False, row['input_changed'])

    def test_v4_assets_pass_and_v3_archive_cannot_be_called_v4(self):
        self.assertEqual(53, validate(OUT)['cases'])
        with self.assertRaisesRegex(ValueError, '完整运行输入不是冻结输入'):
            verify(BASELINE, assets_dir=OUT)

    def test_gold_or_mapping_tampering_is_rejected(self):
        self.cases['E05-A-unknown']['expected_label'] = 'applicable'
        with self.assertRaisesRegex(ValueError, '修订合同'):
            verify_revision(data=self.new)
        self.mapping[0]['old_id'] = None
        with self.assertRaisesRegex(ValueError, '映射'):
            verify_revision(mapping=self.mapping)

    def test_v4_run_cannot_fill_17_missing_cases_with_unknown(self):
        raw = load(OUT.parent / 'baseline-v4-authorized/full/observations.json')
        inputs = load(OUT / 'inputs.json')
        result = summarize(self.new, inputs, raw)
        self.assertEqual(53, result['recorded_cases'])
        self.assertEqual(17, result['capability_absent'])
        self.assertIsNone(result['all_cases_semantic_accuracy'])
        next(r for r in raw['rows'] if r['family'] == 'applicability')['label'] = 'unknown'
        with self.assertRaisesRegex(ValueError, '缺能力'):
            summarize(self.new, inputs, raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
