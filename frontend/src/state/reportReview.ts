/** 编辑器的来源版本随填写冻结，刷新不能悄悄替患者解决并发冲突。 */
import type { ReportReviewWorkspace, ReviewContent, ReviewOrigin } from '../api/reports.ts';

export const reviewLabels: Record<string, string> = { unverified: '待本人核对', draft: '草稿已保存，待核对',
  patient_confirmed: '本人已核对', source_changed: '来源变化，需重新核对' };
export const emptyReviewContent = (): ReviewContent => ({ indicators: [], sections: [] });
export interface ReviewEditor { base: ReportReviewWorkspace | null; content: ReviewContent; origin: ReviewOrigin; modified: boolean }
export function emptyReviewEditor(): ReviewEditor {
  return { base: null, content: emptyReviewContent(), origin: { based_on_version_id: null, candidate_job_id: null }, modified: false };
}
export function mergeReviewEditor(current: ReviewEditor, incoming: ReportReviewWorkspace, replace = false): ReviewEditor {
  if (current.base && (incoming.revision < current.base.revision || incoming.source_epoch < current.base.source_epoch)) return current;
  if (current.modified && !replace) return current;
  const version = incoming.draft || incoming.confirmed;
  return { base: incoming, content: structuredClone(version?.content || emptyReviewContent()),
    origin: { based_on_version_id: version?.category === incoming.category ? version.id : null, candidate_job_id: null }, modified: false };
}
export function canConfirmReview(editor: ReviewEditor): boolean {
  const draft = editor.base?.draft;
  return !!draft && !editor.modified && draft.source_current && draft.revision === editor.base?.revision &&
    !!(editor.content.indicators.length || editor.content.sections.length) &&
    editor.content.indicators.every(item => !!item.name.trim() && !!item.raw_value.trim()) &&
    editor.content.sections.every(item => !!item.text.trim());
}
