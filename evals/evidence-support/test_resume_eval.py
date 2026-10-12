"""评分量尺的隔离fixture与失败注入；此处数据不是模型优化成绩。"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_resume_eval import construct, sha, build
from resume_eval_score import score

INJECTION_EXITS = []


class ResumeEvalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.assets = Path(self.tmp.name) / 'fixture-assets'
        build(self.assets)
        corpus, inputs, gold, _ = construct()
        self.inputs, self.gold, self.corpus = inputs, gold, corpus
        selected = {'version': inputs['version'], 'questions': [{k: v for k, v in q.items() if k != 'split'} for q in inputs['questions'] if q['split'] == 'development']}
        by_id = {g['id']: g for g in gold['questions']}
        rows = []
        for q in selected['questions']:
            g = by_id[q['id']]
            expected = {c['id']: c['label'] for c in g['candidates']}
            full = next((s for s in q['candidates'] if s['id'] == g['full_source_id']), None)
            sources = [{k: full[k] for k in ('document_id', 'start', 'end', 'quote')}] if full else []
            keep = [s for s in q['candidates'] if expected[s['id']] != 'does_not_answer']
            rows.append({'id': q['id'], 'status': 'success', 'retrieved_sources': sources,
                         'candidates': [{'id': s['id'], 'label': expected[s['id']], 'retain': s in keep, 'score': 1.0 if s in keep else 0.0} for s in q['candidates']],
                         'ranked_ids': sorted([s['id'] for s in keep], key=lambda sid: expected[sid] != 'answers'),
                         'elapsed_ms': 10.0, 'usage': {'input_tokens': 100, 'output_tokens': 10}, 'error_type': None})
        self.obs = {'protocol': 'resume-eval-observations-v1', 'split': 'development',
                    'input_sha256': sha((self.assets / 'inputs-development.json').read_bytes()), 'rows': rows}

    def evaluate(self, value=None):
        return score(self.assets, value or self.obs, 'development')

    def test_fixed_counts_and_synthetic_perfect_fixture(self):
        self.assertEqual(40, len(self.inputs['questions']))
        result = self.evaluate()
        self.assertEqual(24, result['groups'])
        self.assertEqual(1, result['accuracy'])
        self.assertEqual(1, result['macro_f1'])
        self.assertEqual(1, result['retrieval']['5']['annotated_evidence_recall_at_k'])
        self.assertEqual(0, result['retrieval']['10']['no_answer_false_retrieval_rate'])
        self.assertEqual(1, result['mean_candidate_ndcg'])

    def test_k5_and_k10_are_separate(self):
        row = next(r for r in self.obs['rows'] if r['retrieved_sources'])
        full = row['retrieved_sources'][0]
        d = next(d for d in self.corpus['documents'] if d['id'] != full['document_id'])
        row['retrieved_sources'] = [{'document_id': d['id'], 'start': i, 'end': i + 1, 'quote': d['content'][i:i + 1]} for i in range(5)] + [full]
        result = self.evaluate()
        self.assertEqual(False, next(r for r in result['retrieval_results'] if r['id'] == row['id'])['at_k']['5']['hit'])
        self.assertEqual(True, next(r for r in result['retrieval_results'] if r['id'] == row['id'])['at_k']['10']['hit'])

    def test_fragment_does_not_cover_complete_condition(self):
        g = next(g for g in self.gold['questions'] if g['theme'] == 'diarrhea_hypernatremia')
        r = g['requirements'][1]
        doc = next(d for d in self.corpus['documents'] if d['id'] == r['document_id'])
        a = doc['content'].index('≤0.5mmol/L', r['start'])
        row = next(x for x in self.obs['rows'] if x['id'] == g['id'])
        row['retrieved_sources'] = [{'document_id': doc['id'], 'start': a, 'end': a + len('≤0.5mmol/L'), 'quote': '≤0.5mmol/L'}]
        metrics = next(x for x in self.evaluate()['retrieval_results'] if x['id'] == g['id'])['at_k']['5']
        self.assertTrue(metrics['hit'])
        self.assertEqual(0, metrics['annotated_evidence_recall'])
        self.assertFalse(metrics['necessary_claim_coverage'])

    def test_invalid_observations_raise_and_cli_nonzero(self):
        variants = {}
        x = copy.deepcopy(self.obs);x['rows'].pop();variants['missing_result'] = x
        x = copy.deepcopy(self.obs);next(r for r in x['rows'] if r['retrieved_sources'])['retrieved_sources'][0]['quote'] = '错误引文';variants['wrong_quote'] = x
        x = copy.deepcopy(self.obs);x['rows'][0]['expected_label'] = 'answers';variants['gold_leak'] = x
        x = copy.deepcopy(self.obs);x['rows'][0]['candidates'][0]['label'] = 'invalid';variants['illegal_label'] = x
        x = copy.deepcopy(self.obs);x['rows'][0]['candidates'][0]['score'] = float('nan');variants['nan_score'] = x
        x = copy.deepcopy(self.obs);x['rows'][0]['candidates'][0]['score'] = 1.01;variants['out_of_range_score'] = x
        x = copy.deepcopy(self.obs);x['rows'][0]['candidates'].pop();variants['missing_candidate'] = x
        x = copy.deepcopy(self.obs);x['rows'].append(x['rows'][0]);variants['duplicate_result'] = x
        x = copy.deepcopy(self.obs);x['input_sha256'] = 'wrong';variants['wrong_input_hash'] = x
        runner = Path(__file__).with_name('resume_eval_score.py')
        for name, value in variants.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.evaluate(value)
                path = self.assets / (name + '.json')
                path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
                result = subprocess.run([sys.executable, '-X', 'utf8', str(runner), '--assets', str(self.assets), '--observations', str(path), '--split', 'development'], capture_output=True, text=True, encoding='utf-8')
                self.assertNotEqual(0, result.returncode)
                self.assertIn('ValueError', result.stderr)
                INJECTION_EXITS.append({'case': name, 'exit_code': result.returncode})

    def test_unknown_errors_remain_in_denominator_and_stop_cli(self):
        row = self.obs['rows'][0]
        row.update(status='error', error_type='timeout', usage={'input_tokens': None, 'output_tokens': None})
        for c in row['candidates']:
            c.update(label='unknown', retain=True, score=None)
        row['ranked_ids'] = [c['id'] for c in row['candidates']]
        result = self.evaluate()
        self.assertEqual(24, result['groups'])
        self.assertEqual(1, result['execution_errors'])
        self.assertEqual('OBSERVATIONS_WITH_ERRORS', result['status'])
        self.assertLess(result['accuracy'], 1)
        self.assertIsNone(result['usage']['input_tokens'])
        path = self.assets / 'error.json';path.write_text(json.dumps(self.obs), encoding='utf-8')
        cli = subprocess.run([sys.executable, str(Path(__file__).with_name('resume_eval_score.py')), '--assets', str(self.assets), '--observations', str(path), '--split', 'development'], capture_output=True)
        self.assertNotEqual(0, cli.returncode)
        INJECTION_EXITS.append({'case': 'unknown_timeout', 'exit_code': cli.returncode})

    def test_changed_gold_rejected_before_scoring(self):
        path = self.assets / 'gold.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['questions'][0]['candidates'][0]['label'] = 'does_not_answer'
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '冻结文件变化'):
            self.evaluate()

    def test_no_answer_timeout_is_not_successful_rejection(self):
        negative_ids = {g['id'] for g in self.gold['questions'] if not g['answerable']}
        row = next(r for r in self.obs['rows'] if r['id'] in negative_ids)
        row.update(status='error', error_type='timeout', retrieved_sources=[], usage={'input_tokens': None, 'output_tokens': None})
        for c in row['candidates']:
            c.update(label='unknown', retain=True, score=None)
        row['ranked_ids'] = [c['id'] for c in row['candidates']]
        result = self.evaluate()
        self.assertIsNone(result['retrieval']['5']['no_answer_false_retrieval_rate'])
        self.assertEqual(0.25, result['retrieval']['5']['no_answer_gate_failure_rate'])
        self.assertEqual(1, result['retrieval']['10']['no_answer_execution_errors'])
        self.assertEqual(24, result['groups'])

    def test_illegal_json_cli_nonzero(self):
        path = self.assets / 'malformed.json';path.write_text('{broken', encoding='utf-8')
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('resume_eval_score.py')), '--assets', str(self.assets), '--observations', str(path), '--split', 'development'], capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn(b'JSONDecodeError', result.stderr)
        INJECTION_EXITS.append({'case': 'malformed_json', 'exit_code': result.returncode})

    def test_gold_leak_in_input_rejected_even_with_changed_manifest(self):
        path = self.assets / 'inputs-development.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['questions'][0]['expected_label'] = 'answers'
        path.write_text(json.dumps(value), encoding='utf-8')
        manifest_path = self.assets / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['assets_sha256'][path.name] = sha(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '执行集合与冻结母集不一致'):
            self.evaluate()

    def test_candidate_only_cannot_claim_retrieval_metrics(self):
        with self.assertRaisesRegex(ValueError, '不得伪装检索来源'):
            score(self.assets, self.obs, 'development', retrieval_executed=False)
        for row in self.obs['rows']:
            row['retrieved_sources'] = []
        result = score(self.assets, self.obs, 'development', retrieval_executed=False)
        self.assertEqual('given_candidates_only', result['metric_scope'])
        self.assertIsNone(result['retrieval'])
        self.assertIsNone(result['mrr_all_returned'])
        self.assertEqual(1, result['accuracy'])

    def test_smoke_scope_is_explicit_and_cannot_change_full_denominator(self):
        chosen = self.obs['rows'][:6]
        value = copy.deepcopy(self.obs);value['rows'] = chosen
        ids = [r['id'] for r in chosen]
        with self.assertRaisesRegex(ValueError, '拒绝改变分母'):
            self.evaluate(value)
        result = score(self.assets, value, 'development', selected_ids=ids)
        self.assertEqual(6, result['groups'])
        self.assertEqual('explicit_smoke_subset', result['evaluation_scope'])
        with self.assertRaises(ValueError):
            score(self.assets, value, 'development', selected_ids=ids + [ids[0]])

    def test_single_class_subset_reports_unmeasured_rates_as_null(self):
        negative_ids = {g['id'] for g in self.gold['questions'] if not g['answerable']}
        for answerable in (True, False):
            row = next(r for r in self.obs['rows'] if (r['id'] not in negative_ids) == answerable)
            value = copy.deepcopy(self.obs);value['rows'] = [row]
            result = score(self.assets, value, 'development', selected_ids=[row['id']])
            if answerable:
                self.assertIsNone(result['retrieval']['5']['no_answer_false_retrieval_rate'])
            else:
                self.assertIsNone(result['retrieval']['5']['hit_at_k'])
                self.assertIsNone(result['mean_candidate_ndcg'])


if __name__ == '__main__':
    run = unittest.main(verbosity=2, exit=False)
    print(json.dumps({'fixture_only': True, 'failure_injection_exits': INJECTION_EXITS}))
    sys.exit(0 if run.result.wasSuccessful() else 1)
