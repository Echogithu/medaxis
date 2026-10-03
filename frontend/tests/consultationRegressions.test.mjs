import assert from 'node:assert/strict';
import { test } from 'node:test';
import { patientText, patientList } from '../src/state/patientText.ts';
import { recoverReportSources } from '../src/state/reportCitations.ts';

test('截图中的内部维度译为中文，无意义字段隐藏但不改数值单位', () => {
  assert.equal(patientText('adv_stool_pattern'), '大便的性状与次数');
  assert.equal(patientText('adv_epidemic'), '近期饮食及接触情况');
  assert.deepEqual(patientList(['adv_unfamiliar_key', '体温38.5°C，年龄12岁']), ['体温38.5°C，年龄12岁']);
});

test('有检索记录却零引用的旧总结恢复原文与原编号，不伪造已引用状态', () => {
  const report = { primary_diagnosis: '合成总结', confidence: 'low', knowledge_citations: [], knowledge_retrieval_count: 2 };
  const source = { citation_id: 'S4', source_type: 'internal', title: '合成来源', document_id: 'doc', chunk_id: 'chunk', excerpt: '合成完整原文。' };
  const messages = [{ workflowSteps: [{ type: 'tool_result', toolName: 'search_medical_knowledge', toolResult: { sources: [source] } }] }];
  const recovered = recoverReportSources(report, messages);
  assert.deepEqual(recovered.knowledge_citations.map(item => item.citation_id), ['S4']);
  assert.equal(recovered.knowledge_citations[0].excerpt, '合成完整原文。');
  assert.equal(recovered.knowledge_citations[0].used_in_report, false);
  assert.equal(recovered.knowledge_retrieval_status, 'retrieved_not_cited');
  assert.deepEqual(report.knowledge_citations, []);
});

test('历史来源的正文引用编号保持原样，坏链接或没有定位的资料不能恢复', () => {
  const report = { primary_diagnosis: '合成总结[S4]', confidence: 'low', knowledge_retrieval_count: 2 };
  const sources = [
    { citation_id: 'S4', source_type: 'external', title: '外部资料', excerpt: '合成原文。', url: 'https://example.org/ref' },
    { citation_id: 'S9', source_type: 'external', title: '危险来源', excerpt: '合成原文。', url: 'javascript:alert(1)' },
    { citation_id: 'S8', source_type: 'internal', title: '无定位来源', excerpt: '合成原文。' },
  ];
  const recovered = recoverReportSources(report, [{ workflowSteps: [{ type: 'tool_result', toolName: 'search_medical_knowledge', toolResult: { sources } }] }]);
  assert.deepEqual(recovered.knowledge_citations.map(item => item.citation_id), ['S4']);
  assert.equal(recovered.knowledge_citations[0].used_in_report, true);
  assert.equal(recovered.primary_diagnosis, report.primary_diagnosis);
  assert.equal(recoverReportSources(report, []), report);
});

test('历史报告不能绑定生成报告之后另一轮追问的来源', () => {
  const report = { primary_diagnosis: '原总结[S4]', confidence: 'low', knowledge_retrieval_count: 1 };
  const source = title => ({ citation_id: 'S4', source_type: 'internal', title, excerpt: '完整原文。', document_id: title, chunk_id: title });
  const step = title => ({ type: 'tool_result', toolName: 'search_medical_knowledge', toolResult: { sources: [source(title)] } });
  const messages = [{ structured: report, workflowSteps: [step('原报告来源')] }, { workflowSteps: [step('后续追问来源')] }];
  assert.equal(recoverReportSources(report, messages).knowledge_citations[0].title, '原报告来源');
});

test('同名的后续总结不能代替原报告定位，找不到原报告时不借用资料', () => {
  const report = { primary_diagnosis: '同名总结', confidence: 'low', knowledge_retrieval_count: 1, recommended_actions: ['原建议'] };
  const other = { ...report, recommended_actions: ['后续不同建议'] };
  const step = title => ({ type: 'tool_result', toolName: 'search_medical_knowledge', toolResult: { sources: [
    { citation_id: 'S1', source_type: 'internal', title, excerpt: '完整原文。', document_id: title, chunk_id: title },
  ] } });
  const messages = [{ structured: { ...report }, workflowSteps: [step('原来源')] }, { structured: other, workflowSteps: [step('其他来源')] }];
  assert.equal(recoverReportSources(report, messages).knowledge_citations[0].title, '原来源');
  assert.equal(recoverReportSources(report, messages.slice(1)), report);
});
