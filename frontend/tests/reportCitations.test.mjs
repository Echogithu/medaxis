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

test('问题覆盖排序保留编号，部分覆盖不冒充完整或报告支持', () => {
  const rows = [
    { citation_id: 'S7', relevance_method: 'query_requirements', relevance: .5, relevance_query_fingerprint: 'q',
      query_coverage: { status: 'partial_answer' }, excerpt: '甲条件。', url: 'https://example.org/source' },
    { citation_id: 'S9', relevance_method: 'query_requirements', relevance: 1, relevance_query_fingerprint: 'q',
      query_coverage: { status: 'answers' }, excerpt: '甲乙条件。' },
    { citation_id: 'S3', relevance_method: 'query_requirements', relevance: null, relevance_query_fingerprint: 'q',
      query_coverage: { status: 'unknown' } },
  ];
  assert.deepEqual(citationState.sortReportCitations(rows).map(row => row.citation_id), ['S9', 'S7', 'S3']);
  assert.equal(citationState.citationRelevanceLabel(rows[0]), '模型判断：部分覆盖问题要点');
  assert.equal(citationState.citationRelevanceLabel(rows[2]), '问题覆盖情况待核对');
  assert.equal(rows[0].excerpt, '甲条件。');
  assert.equal(citationEvidenceLabel([], rows[0]), '尚无逐条核对记录');
  const mixed = [rows[0], { citation_id: 'S1', relevance_method: 'keyword', relevance: .9 }];
  assert.deepEqual(citationState.sortReportCitations(mixed).map(row => row.citation_id), ['S7', 'S1']);
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

test('补充前后文提示核对锚点和完整摘录，坏的旧元信息不崩溃', () => {
  const source = { citation_id: 'S1', source_type: 'internal', title: '合成资料', document_id: 'doc', chunk_id: 'a',
    excerpt: '🩺完整原文。', context_metadata: { document_id: 'doc', anchor_chunk_id: 'a', chunk_ids: ['a', 'b'],
      start: 10, end: 16, method: 'anchor_neighbors' } };
  assert.equal(citationState.citationHasExpandedContext(source), true);
  assert.equal(citationState.citationHasExpandedContext({ ...source, context_metadata: { method: 'anchor_neighbors' } }), false);
  assert.equal(citationState.citationHasExpandedContext({ ...source, context_metadata: { ...source.context_metadata, anchor_chunk_id: 'wrong' } }), false);
  const report = { primary_diagnosis: '待核对[S1]', knowledge_retrieval_count: 1 };
  const recovered = citationState.recoverReportSources(report, [{ workflowSteps: [{ type: 'tool_result', toolName: 'search_medical_knowledge', toolResult: { sources: [source] } }] }]);
  assert.deepEqual(recovered.knowledge_citations[0].context_metadata, source.context_metadata);
  assert.equal(recovered.knowledge_citations[0].excerpt, source.excerpt);
});
