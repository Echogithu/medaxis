import type { ChatMessageItem, DiagnosisReport, KnowledgeCitation, KnowledgeEvidence } from '../types/agent.ts';

/** 历史报告的来源可从同一会话已保存的检索结果恢复，不重新请求模型。 */
export function recoverReportSources(report: DiagnosisReport | null, messages: ChatMessageItem[]): DiagnosisReport | null {
  if (!report || report.knowledge_citations?.length || !report.knowledge_retrieval_count) return report;
  const reportSignature = JSON.stringify(report);
  const reportIndex = messages.findLastIndex(message => message.structured && JSON.stringify(message.structured) === reportSignature);
  // 标题可能相同，不能据此把后续总结的检索资料绑定到原报告。
  if (reportIndex < 0 && messages.some(message => message.structured)) return report;
  const sourceMessages = reportIndex >= 0 ? messages.slice(0, reportIndex + 1) : messages;
  const steps = sourceMessages.flatMap(message => message.workflowSteps ?? []);
  for (const step of steps.reverse()) {
    if (step.type !== 'tool_result' || step.toolName !== 'search_medical_knowledge') continue;
    let value = step.toolResult;
    if (!value || typeof value !== 'object') continue;
    if ('result' in value) value = (value as { result: unknown }).result;
    if (!value || typeof value !== 'object' || !('sources' in value) || !Array.isArray(value.sources)) continue;
    const seen = new Set<string>();
    const citations = (value.sources as KnowledgeCitation[]).slice(0, 10).filter(source => {
      if (!source || !isCitationId(source.citation_id) || seen.has(source.citation_id)
        || typeof source.title !== 'string' || !source.title.trim() || typeof source.excerpt !== 'string' || !source.excerpt.trim()) return false;
      if (source.source_type === 'internal' ? !(source.document_id && source.chunk_id)
        : source.source_type !== 'external' || !isSafeCitationUrl(source.url)) return false;
      seen.add(source.citation_id);
      return true;
    });
    if (!citations.length) continue;
    const claims = JSON.stringify({ primary_diagnosis: report.primary_diagnosis, key_findings: report.key_findings,
      recommended_actions: report.recommended_actions, recommended_tests: report.recommended_tests,
      contraindications: report.contraindications, differential_diagnoses: report.differential_diagnoses,
      follow_up_timeline: report.follow_up_timeline, red_flags: report.red_flags });
    const restored = citations.map(source => ({ ...source, used_in_report: claims.includes(`[${source.citation_id}]`) }));
    return { ...report, knowledge_citations: restored, knowledge_sources: restored.map(source => source.title),
      knowledge_retrieval_status: restored.some(source => source.used_in_report) ? 'used' : 'retrieved_not_cited' };
  }
  return report;
}

export type CitationMarkerPart =
  | { type: 'text'; value: string }
  | { type: 'citation'; value: string };

export function splitCitationMarkers(value: string): CitationMarkerPart[] {
  const parts: CitationMarkerPart[] = [];
  const pattern = /\[(S\d+)\]/g;
  let cursor = 0;

  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push({ type: 'text', value: value.slice(cursor, index) });
    parts.push({ type: 'citation', value: match[1] });
    cursor = index + match[0].length;
  }

  if (cursor < value.length || parts.length === 0) {
    parts.push({ type: 'text', value: value.slice(cursor) });
  }
  return parts;
}

export function isCitationId(value: unknown): value is string {
  return typeof value === 'string' && /^S\d+$/.test(value);
}

export function isSafeCitationUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    return (url.protocol === 'http:' || url.protocol === 'https:') && Boolean(url.hostname);
  } catch {
    return false;
  }
}

/** 预览只整理空白与限制长度；完整来源片段由阅读区原样展示。 */
export function citationExcerptPreview(excerpt: string, limit = 160): string {
  const text = excerpt.replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text;
}

/** 后端偏移为Unicode code point；不能按JS UTF-16索引切片。 */
export function evidenceMatchesExcerpt(row: KnowledgeEvidence, citation: KnowledgeCitation): boolean {
  const text = [...citation.excerpt];
  return row.status === 'excerpt_matched' && row.citation_id === citation.citation_id
    && typeof row.quote === 'string' && Boolean(row.quote) && row.claim === row.quote
    && typeof row.start === 'number' && typeof row.end === 'number'
    && Number.isInteger(row.start) && Number.isInteger(row.end)
    && row.start >= 0 && row.end > row.start && row.end <= text.length
    && text.slice(row.start, row.end).join('') === row.quote;
}

export function citationEvidenceLabel(rows: KnowledgeEvidence[], citation: KnowledgeCitation): string {
  if (!rows.length) return '尚无逐条核对记录';
  const matches = rows.filter(row => evidenceMatchesExcerpt(row, citation)).length;
  return `原文一致 ${matches} 条 · 待核对 ${rows.length - matches} 条`;
}

/** 只比较同一评估口径；旧报告的混合分数保持原顺序，编号永不重写。 */
export function sortReportCitations(citations: KnowledgeCitation[]): KnowledgeCitation[] {
  const assessed = citations.filter(row => row.relevance_method === 'reranker' || row.relevance_method === 'keyword' || row.relevance_method === 'query_requirements');
  if (new Set(assessed.map(row => row.relevance_method)).size > 1
    || new Set(assessed.map(row => row.relevance_query_fingerprint ?? '')).size > 1) return [...citations];
  const score = (row: KnowledgeCitation) => row.relevance_method !== 'unassessed'
    && (row.relevance_method === 'reranker' || row.relevance_method === 'keyword' || row.relevance_method === 'query_requirements')
    && typeof row.relevance === 'number' && Number.isFinite(row.relevance)
    && row.relevance >= 0 && row.relevance <= 1 ? row.relevance : -1;
  return [...citations].sort((a, b) => score(b) - score(a));
}

export function citationRelevanceLabel(citation: KnowledgeCitation): string {
  if (citation.relevance_method === 'query_requirements') {
    if (citation.query_coverage?.status === 'answers') return '模型判断：覆盖问题要点';
    if (citation.query_coverage?.status === 'partial_answer') return '模型判断：部分覆盖问题要点';
    return '问题覆盖情况待核对';
  }
  if (citation.relevance_method === 'reranker') return '已按语义相关性排序';
  if (citation.relevance_method === 'keyword') return '主题词匹配';
  return '相关性待核对';
}

/** 旧记录可能缺少字段；只对结构一致的多片段摘录显示前后文提示。 */
export function citationHasExpandedContext(citation: KnowledgeCitation): boolean {
  const meta = citation.context_metadata;
  return Boolean(meta && meta.method === 'anchor_neighbors'
    && meta.document_id === citation.document_id && meta.anchor_chunk_id === citation.chunk_id
    && Array.isArray(meta.chunk_ids) && meta.chunk_ids.length > 1 && meta.chunk_ids.length <= 3
    && meta.chunk_ids.every(id => typeof id === 'string' && Boolean(id))
    && new Set(meta.chunk_ids).size === meta.chunk_ids.length && meta.chunk_ids.includes(citation.chunk_id!)
    && Number.isInteger(meta.start) && Number.isInteger(meta.end) && meta.start >= 0
    && meta.end - meta.start === [...citation.excerpt].length
    && [...citation.excerpt].length <= 1600);
}
