"""请求覆盖判别的原文、缺失、失败和输入隔离合同；不连接模型或数据库。"""
import json
import unittest
from app.services.query_requirements import parse_assessment, make_messages, assess_query


class ContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sources = [{'id': 'x', 'title': '资料', 'excerpt': '甲情况需要记录；乙情况需要核对。'},
                        {'id': 'y', 'title': '资料', 'excerpt': '甲情况需要记录。'},
                        {'id': 'z', 'title': '资料', 'excerpt': '另一种用途。'}]
        self.raw = {'requirements': ['甲情况', '乙情况'], 'candidates': [
            {'id': 'x', 'checks': [{'covered': True, 'quote': '甲情况需要记录', 'reason': '覆盖甲'},
                                  {'covered': True, 'quote': '乙情况需要核对', 'reason': '覆盖乙'}]},
            {'id': 'y', 'checks': [{'covered': True, 'quote': '甲情况需要记录', 'reason': '覆盖甲'},
                                  {'covered': False, 'quote': None, 'reason': '未说明乙'}]},
            {'id': 'z', 'checks': [{'covered': False, 'quote': None, 'reason': '另一用途'},
                                  {'covered': False, 'quote': None, 'reason': '另一用途'}]}]}

    def parse(self):
        return parse_assessment(json.dumps(self.raw, ensure_ascii=False), self.sources)

    def test_three_labels_and_partial_retention(self):
        data = self.parse()
        self.assertEqual(['answers', 'partial_answer', 'does_not_answer'], [r['label'] for r in data['candidates']])
        self.assertEqual([True, True, False], [r['retain'] for r in data['candidates']])
        self.assertEqual(['乙情况'], data['candidates'][1]['missing_requirements'])

    def test_unknown_is_retained_and_not_counted_as_answers(self):
        self.raw['candidates'][2]['checks'][0]['covered'] = None
        data = self.parse()['candidates'][2]
        self.assertEqual('unknown', data['label'])
        self.assertTrue(data['retain'])

    def test_quoted_text_must_exist(self):
        self.raw['candidates'][0]['checks'][0]['quote'] = '伪造的条件'
        with self.assertRaises(ValueError): self.parse()

    def test_missing_candidate_rejected(self):
        self.raw['candidates'].pop()
        with self.assertRaises(ValueError): self.parse()

    def test_duplicate_candidate_rejected(self):
        self.raw['candidates'][1]['id'] = 'x'
        with self.assertRaises(ValueError): self.parse()

    def test_missing_requirement_check_rejected(self):
        self.raw['candidates'][1]['checks'].pop()
        with self.assertRaises(ValueError): self.parse()

    def test_extra_model_label_rejected(self):
        self.raw['candidates'][0]['label'] = 'answers'
        with self.assertRaises(ValueError): self.parse()

    def test_boolean_not_numeric(self):
        self.raw['candidates'][0]['checks'][0]['covered'] = 1
        with self.assertRaises(ValueError): self.parse()

    def test_string_null_is_only_normalized_for_uncovered(self):
        self.raw['candidates'][1]['checks'][1]['quote'] = 'null'
        self.assertIsNone(self.parse()['candidates'][1]['checks'][1]['quote'])
        self.raw['candidates'][0]['checks'][0]['quote'] = 'null'
        with self.assertRaises(ValueError): self.parse()

    def test_whitespace_only_quote_normalization(self):
        self.sources[0]['excerpt'] = '甲情况\n需要记录；乙情况需要核对。'
        self.assertEqual('answers', self.parse()['candidates'][0]['label'])
        self.raw['candidates'][0]['checks'][0]['quote'] = '甲情况需要记录!'
        with self.assertRaises(ValueError): self.parse()

    def test_short_requested_term_is_valid_literal_quote(self):
        self.sources[0]['excerpt'] = '甲。乙。'
        self.raw['candidates'][0]['checks'][0]['quote'] = '甲'
        self.raw['candidates'][0]['checks'][1]['quote'] = '乙'
        self.assertEqual('answers', self.parse()['candidates'][0]['label'])
        self.raw['candidates'][0]['checks'][0]['quote'] = ''
        with self.assertRaises(ValueError): self.parse()

    def test_prompt_excludes_gold_and_coordinates(self):
        self.sources[0].update(expected_label='answers', qualifiers=['答案提示'], start=10)
        prompt = json.loads(make_messages('甲乙情况', self.sources)[0]['content'])
        self.assertEqual({'id', 'title', 'excerpt'}, set(prompt['candidates'][0]))
        self.assertNotIn('答案提示', json.dumps(prompt, ensure_ascii=False))

    async def test_invalid_response_retains_all_and_records_failure(self):
        from types import SimpleNamespace
        class Fake:
            provider = 'fake'
            async def chat(self, **kwargs):
                return SimpleNamespace(content='not json', model='fake', provider='fake', finish_reason='stop',
                                       usage_prompt_tokens=10, usage_completion_tokens=3)
        result = await assess_query('甲乙情况', self.sources, Fake())
        self.assertEqual('assessment_error', result['status'])
        self.assertTrue(all(row['retain'] and row['label'] == 'unknown' for row in result['candidates']))

    async def test_timeout_keeps_original_sources(self):
        class Fake:
            async def chat(self, **kwargs): raise TimeoutError()
        result = await assess_query('甲乙情况', self.sources, Fake())
        self.assertEqual('TimeoutError', result['error_type'])
        self.assertEqual(['x', 'y', 'z'], [r['id'] for r in result['candidates']])


if __name__ == '__main__': unittest.main()
