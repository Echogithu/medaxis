"""主动破坏证据和预测，验证门禁确实能发现错误；测试输出不计入生产成绩。"""
import json
import tempfile
import unittest
from pathlib import Path

from score import score
from verify import DEFAULT, digest, load, validate


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load(DEFAULT / 'dataset.json')

    def predictions(self):
        return {'predictions': [{'id': c['id'], 'label': c['expected_label']} for c in self.dataset['cases']]}

    def execution_id(self, display_id):
        return next(c['id'] for c in self.dataset['cases'] if c['display_id'] == display_id)

    def corrupt_and_validate(self, filename, mutate, rehash=False):
        # 临时目录由本轮测试创建，只在其中制造错误，不改冻结原件。
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for path in DEFAULT.iterdir():
                (folder / path.name).write_bytes(path.read_bytes())
            value = load(folder / filename)
            mutate(value)
            (folder / filename).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            if rehash:
                manifest = load(folder / 'manifest.json')
                manifest['assets_sha256'][filename] = digest(folder / filename)
                (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaises(ValueError):
                validate(folder)

    def test_asset_validation(self):
        self.assertEqual(52, validate()['cases'])

    def test_changed_frozen_file_fails(self):
        self.corrupt_and_validate('dataset.json', lambda d: d.update(scope='已改写'))

    def test_wrong_quote_fails_even_after_rehash(self):
        self.corrupt_and_validate('dataset.json', lambda d: d['gold_units'][0].update(quote='不存在的原文'), True)

    def test_wrong_offset_fails_even_after_rehash(self):
        self.corrupt_and_validate('dataset.json', lambda d: d['gold_units'][0].update(start=1), True)

    def test_missing_qualifier_fails(self):
        self.corrupt_and_validate('dataset.json', lambda d: d['gold_units'][0].update(qualifiers=['不存在的限制']), True)

    def test_old_gold_overlap_fails(self):
        unit = self.dataset['gold_units'][0]
        def overlap(previous):
            previous[0]['ranges'].append({k: unit[k] for k in ['document_id', 'start', 'end']})
        self.corrupt_and_validate('prior-exposure.json', overlap, True)

    def test_execution_input_mismatch_fails(self):
        self.corrupt_and_validate('inputs.json', lambda d: d['cases'][0].update(query='另一个问题'), True)

    def test_duplicate_case_fails(self):
        self.corrupt_and_validate('dataset.json', lambda d: d['cases'][1].update(id=d['cases'][0]['id']), True)

    def test_missing_prediction_fails(self):
        p = self.predictions(); p['predictions'].pop()
        with self.assertRaises(ValueError): score(self.dataset, p)

    def test_duplicate_prediction_fails(self):
        p = self.predictions(); p['predictions'].append(p['predictions'][0])
        with self.assertRaises(ValueError): score(self.dataset, p)

    def test_extra_prediction_fails(self):
        p = self.predictions(); p['predictions'].append({'id': 'UNKNOWN', 'label': 'answers'})
        with self.assertRaises(ValueError): score(self.dataset, p)

    def test_invalid_label_fails(self):
        p = self.predictions(); p['predictions'][0]['label'] = 'invented'
        with self.assertRaises(ValueError): score(self.dataset, p)

    def test_false_support_loses_pair_and_adds_false_accept(self):
        p = self.predictions()
        row = next(r for r in p['predictions'] if r['id'] == self.execution_id('E01-S-'))
        row['label'] = 'supported'
        result = score(self.dataset, p)
        self.assertEqual(51, result['correct'])
        self.assertEqual(1, result['families']['statement_support']['false_accepts'])
        self.assertEqual(23, result['contrast_pairs_both_correct'])

    def test_unknown_is_not_counted_as_valid(self):
        p = self.predictions()
        next(r for r in p['predictions'] if r['id'] == self.execution_id('E02-A-'))['label'] = 'applicable'
        self.assertEqual(1, score(self.dataset, p)['families']['applicability']['false_accepts'])

    def test_version_false_accept_is_visible(self):
        p = self.predictions()
        next(r for r in p['predictions'] if r['id'] == self.execution_id('E01-V'))['label'] = 'version_match'
        self.assertEqual(1, score(self.dataset, p)['families']['version_scope']['false_accepts'])

    def test_inputs_have_no_gold_or_sign_id(self):
        inputs = load(DEFAULT / 'inputs.json')['cases']
        for item in inputs:
            self.assertNotIn('expected_label', item)
            self.assertNotIn('display_id', item)
            self.assertRegex(item['id'], r'^T[0-9a-f]{16}$')
        self.assertEqual(sorted(i['id'] for i in inputs), [i['id'] for i in inputs])


if __name__ == '__main__':
    unittest.main(verbosity=2)
