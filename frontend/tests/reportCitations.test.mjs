import assert from 'node:assert/strict';
import { test } from 'node:test';
import { citationExcerptPreview, isSafeCitationUrl, splitCitationMarkers, evidenceMatchesExcerpt, citationEvidenceLabel } from '../src/state/reportCitations.ts';
import * as citationState from '../src/state/reportCitations.ts';

test('splits report text into plain text and exact citation markers', () => {
  assert.deepEqual(splitCitationMarkers('发热需结合病程评估[S1]，不能据此确诊[S2]。'), [
    { type: 'text', value: '发热需结合病程评估' },
    { type: 'citation', value: 'S1' },
    { type: 'text', value: '，不能据此确诊' },
    { type: 'citation', value: 'S2' },
    { type: 'text', value: '。' },
  ]);
});

test('统一评估来源按相关性排序，旧分数不混排且编号不变', () => {
  const sources = [
    { citation_id: 'S1', relevance: 0.4, relevance_method: 'reranker', relevance_query_fingerprint: 'same' },
    { citation_id: 'S2', relevance: 0.9, relevance_method: 'reranker', relevance_query_fingerprint: 'same' },
    { citation_id: 'S3', relevance: 99, relevance_method: 'unassessed' },
  ];
  assert.deepEqual(citationState.sortReportCitations(sources).map(row => row.citation_id), ['S2', 'S1', 'S3']);
  assert.deepEqual(sources.map(row => row.citation_id), ['S1', 'S2', 'S3']);
  assert.equal(citationState.citationRelevanceLabel(sources[2]), '相关性待核对');
});

test('only allows HTTP and HTTPS citation links', () => {
  assert.equal(isSafeCitationUrl('https://www.who.int/example'), true);
  assert.equal(isSafeCitationUrl('http://example.org/source'), true);
  assert.equal(isSafeCitationUrl('javascript:alert(1)'), false);
  assert.equal(isSafeCitationUrl('data:text/html,bad'), false);
  assert.equal(isSafeCitationUrl('not-a-url'), false);
});

test('来源预览整理换行但保留数值、单位与单独数字', () => {
  assert.equal(citationExcerptPreview('  第一段\n体温 38.5°C。\n\n5\n下一段\t内容  '), '第一段 体温 38.5°C。 5 下一段 内容');
});

test('长片段预览明确省略，短片段不增加省略符', () => {
  assert.equal(citationExcerptPreview('第一句。第二句。第三句。', 8), '第一句。第二句。…');
  assert.equal(citationExcerptPreview('第一句。', 8), '第一句。');
});

test('原文核对使用Unicode字符位置，缺失或伪造状态不能显示一致', () => {
  const citation = { citation_id: 'S1', excerpt: '🩺目前没有发热。' };
  const row = { citation_id: 'S1', claim: '目前没有发热。', quote: '目前没有发热。',
    start: 1, end: 8, status: 'excerpt_matched' };
  assert.equal(evidenceMatchesExcerpt(row, citation), true);
  assert.equal(evidenceMatchesExcerpt({ ...row, start: 0 }, citation), false);
  assert.equal(evidenceMatchesExcerpt({ ...row, claim: '发热。' }, citation), false);
  assert.equal(citationEvidenceLabel([], citation), '尚无逐条核对记录');
  assert.equal(citationEvidenceLabel([row, { ...row, status: 'needs_review' }], citation), '原文一致 1 条 · 待核对 1 条');
});
