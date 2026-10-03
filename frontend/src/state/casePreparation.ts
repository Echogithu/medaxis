import type { CasePreparationPackage, PatientContext, PreparationFact } from '../api/patient.ts';
import { patientText } from './patientText.ts';

export interface PreparationDraft {
  version: number;
  revision: number;
  confirmedIds: string[];
  corrections: Record<string, string>;
  checklist: Record<string, 'pending' | 'ready'>;
  questionsText: string;
  summaryText: string;
}

// 仅在当前浏览会话的内存保留草稿；必须成功读取本人病例后才恢复。
const drafts = new Map<string, PreparationDraft>();
export function getPreparationDraft(caseId: string): PreparationDraft | undefined {
  return drafts.get(caseId);
}
export function setPreparationDraft(caseId: string, draft: PreparationDraft | null): void {
  if (draft) drafts.set(caseId, structuredClone(draft));
  else drafts.delete(caseId);
}

export function preparationFactId(fact: PreparationFact): string {
  return fact.id.replace(/^(?:correction\.)+/, '');
}

export function preparationValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  return patientText(typeof value === 'string' ? value : JSON.stringify(value));
}

export function preparationResponse(fact: PreparationFact): string {
  const responses = fact.patient_response_history?.length
    ? fact.patient_response_history : fact.patient_response == null ? [] : [fact.patient_response];
  return responses.length ? `患者原话：${responses.map(preparationValue).join('；')}` : '';
}

const contextLabels: Record<string, string> = {
  non_patient: '家属信息', historical: '既往表述', hypothetical: '条件性表述',
  refuted: '否认表述', uncertain: '不确定表述', unknown: '仍未知',
  needs_review: '待核对', present: '当前表述', reported: '患者自述',
};

/** 与复制共用的原话语境；标记帮助核对，不表示医生确认。 */
export function preparationContext(fact: PatientContext): string[] {
  if (!Array.isArray(fact.clinical_context)) return [];
  return fact.clinical_context.filter(span => span.advisory === true && typeof span.text === 'string')
    .map(span => `${patientText(span.text)}（${contextLabels[span.status] || '待核对'}）`);
}

export function preparationSummary(
  item: CasePreparationPackage,
  confirmedIds: string[],
  corrections: Record<string, string>,
  questionsText: string,
): string {
  const lines = ['就诊摘要（患者自述，供医生核对）', `版本 ${item.version} · 修订 ${item.revision}`, '', '患者陈述'];
  // 默认摘要使用当前陈述；先前原话仍在核对与来源详情中保留。
  for (const fact of item.known_facts.filter(entry => entry.active !== false)) {
    const originalId = preparationFactId(fact);
    const value = corrections[originalId]?.trim() || preparationValue(fact.display_value ?? fact.value);
    lines.push(`- ${fact.label}：${value}${confirmedIds.includes(fact.id) || corrections[originalId]?.trim() ? '（患者已核对）' : '（待本人核对）'}`);
    if (corrections[originalId]?.trim() && value !== preparationValue(fact.display_value ?? fact.value)) {
      lines.push('  语境待保存后重新核对');
    } else {
      for (const context of preparationContext(fact)) lines.push(`  原话语境：${context}`);
    }
  }
  const unresolvedIds = new Set(item.unresolved_facts.map(fact => fact.id));
  const knownIds = new Set(item.known_facts.flatMap(fact => [fact.id, preparationFactId(fact)]));
  for (const fact of item.unknown_facts) {
    if (fact.id === 'unknown.department_focus') continue;
    const value = corrections[fact.id]?.trim();
    lines.push(value ? `- ${fact.label}：${value}（患者补充）` : `- ${fact.label}：${fact.record_state === 'not_recorded' ? '未填写' : '未知'}${preparationResponse(fact) ? `；${preparationResponse(fact)}` : ''}`);
    if (!value) for (const context of preparationContext(fact)) lines.push(`  原话语境：${context}`);
  }
  for (const [id, value] of Object.entries(corrections)) {
    if (!value.trim() || id === 'unknown.department_focus' || knownIds.has(id)
      || unresolvedIds.has(id) || item.unknown_facts.some(fact => fact.id === id)) continue;
    lines.push(`- 患者补充：${value}`);
  }
  if (item.unresolved_facts.length) {
    lines.push('', '前后回答（仍待核对）');
    for (const fact of item.unresolved_facts) {
      lines.push(`- ${fact.label}：${fact.statements.map(entry => preparationValue(entry.value)).join('；')}`);
      for (const statement of fact.statements) {
        for (const context of preparationContext(statement)) lines.push(`  原话语境：${context}`);
      }
      if (corrections[fact.id]?.trim()) lines.push(`  当前补充：${corrections[fact.id]}（保留先前原话）`);
    }
  }
  if (item.summary.materials.length) lines.push('', '已有资料', ...item.summary.materials.map(entry => `- ${entry.filename}`));
  const questions = questionsText.split(/\r?\n/).map(text => text.trim()).filter(Boolean);
  if (questions.length) lines.push('', '想问医生', ...questions.map(text => `- ${text}`));
  lines.push('', '患者核对不等于医生确认；AI 分析请另见问诊报告。');
  return patientText(lines.join('\n'));
}

export function preparationHasChanges(
  item: CasePreparationPackage,
  confirmedIds: string[],
  corrections: Record<string, string>,
  checklist: Record<string, 'pending' | 'ready'>,
  questionsText: string,
): boolean {
  const confirmed = item.known_facts.filter(fact => fact.confirmed).map(fact => fact.id).sort();
  const savedCorrections = Object.fromEntries(item.patient_corrections.map(entry => [entry.fact_id, entry.value.trim()]));
  const correctionEntries = Object.entries(corrections).filter(([, value]) => value.trim());
  return JSON.stringify(confirmed) !== JSON.stringify([...confirmedIds].sort())
    || correctionEntries.length !== Object.keys(savedCorrections).length
    || correctionEntries.some(([id, value]) => savedCorrections[id] !== value.trim())
    || item.preparation_items.some(entry => (checklist[entry.id] || entry.status) !== entry.status)
    || JSON.stringify(item.patient_questions) !== JSON.stringify(questionsText.split(/\r?\n/).map(text => text.trim()).filter(Boolean));
}
