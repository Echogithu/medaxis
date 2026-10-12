"""开发集的原文排除、三类覆盖与输入隔离验证。"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from build_query_dev import OUT, PARENT, build_data, verify_contract
from score import score
from verify import digest, load
from baseline_verify import summarize


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.data = build_data(load(PARENT / 'corpus.json'), load(PARENT / 'dataset.json'))

    def test_contract_and_label_distribution(self):
        self.assertEqual(24, verify_contract()['cases'])
        self.assertEqual(16, len(self.data['gold_units']))
        for label in ['answers', 'partial_answer', 'does_not_answer']:
            self.assertEqual(8, sum(c['expected_label'] == label for c in self.data['cases']))

    def test_partial_covers_some_but_not_all_requirements(self):
        for c in self.data['cases']:
            if c['expected_label'] == 'partial_answer':
                self.assertTrue(c['covered_requirements'])
                self.assertTrue(c['missing_requirements'])
            elif c['expected_label'] == 'answers':
                self.assertFalse(c['missing_requirements'])
            else:
                self.assertFalse(c['covered_requirements'])

    def test_partial_is_literal_prefix_not_rewritten_summary(self):
        units = {u['id']: u for u in self.data['gold_units']}
        for c in self.data['cases']:
            if c['expected_label'] == 'partial_answer':
                self.assertTrue(units[c['topic_id']]['quote'].startswith(units[c['candidate_evidence_id']]['quote']))

    def test_inputs_have_no_gold_or_coverage_fields(self):
        for item in load(OUT / 'inputs.json')['cases']:
            self.assertNotIn('expected_label', item)
            self.assertNotIn('covered_requirements', item)
            self.assertNotIn('missing_requirements', item)
            self.assertNotIn('display_id', item)
            self.assertRegex(item['candidate_source']['id'], r'^U[0-9a-f]{16}$')

    def test_partial_mislabeled_complete_is_error(self):
        predictions = {'predictions': [{'id': c['id'], 'label': c['expected_label']} for c in self.data['cases']]}
        wrong = next(c for c in self.data['cases'] if c['expected_label'] == 'partial_answer')
        next(p for p in predictions['predictions'] if p['id'] == wrong['id'])['label'] = 'answers'
        result = score(self.data, predictions)
        self.assertEqual(23, result['correct'])
        self.assertEqual(1, result['families']['query_specificity']['false_accepts'])

    def test_deterministic_build_does_not_modify_parent(self):
        parent = load(PARENT / 'dataset.json')
        before = copy.deepcopy(parent)
        self.assertEqual(self.data, build_data(load(PARENT / 'corpus.json'), parent))
        self.assertEqual(before, parent)

    def corrupt(self, name, mutate):
        # 仅在临时副本制造错误，保留原资产不变。
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for source in OUT.iterdir():
                if source.is_file():
                    (folder / source.name).write_bytes(source.read_bytes())
            data = load(folder / name)
            mutate(data)
            (folder / name).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            manifest = load(folder / 'manifest.json')
            manifest['assets_sha256'][name] = digest(folder / name)
            (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_contract(folder)

    def test_omitting_old_exposure_fails_even_after_rehash(self):
        self.corrupt('prior-exposure.json', lambda data: data.pop())

    def test_relabeling_partial_fails_even_after_rehash(self):
        def mutate(data):
            next(c for c in data['cases'] if c['expected_label'] == 'partial_answer')['expected_label'] = 'answers'
        self.corrupt('dataset.json', mutate)

    def test_actual_retention_is_separate_from_semantic_accuracy(self):
        raw = load(OUT.parent / 'query-development-baseline-v2/full/observations.json')
        result = summarize(self.data, load(OUT / 'inputs.json'), raw)
        self.assertIsNone(result['all_cases_semantic_accuracy'])
        self.assertEqual(8, result['query_gate']['partial_answer_total'])
        self.assertEqual(8, result['query_gate']['partial_answer_retained'])
        self.assertEqual(8, result['query_gate']['wrong_topic_retained'])
        raw['rows'][0]['semantic_judgment_verified'] = True
        with self.assertRaises(ValueError):
            summarize(self.data, load(OUT / 'inputs.json'), raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
