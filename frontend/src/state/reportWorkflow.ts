/** 工作区响应可能乱序；保留较新任务状态和患者尚未保存的文字。 */
import type { ReportPreview, ReportTextPage, ReportWorkspace } from '../api/reports.ts';

export interface ReportApproval { previewKey: string | null; consent: boolean; ownership: boolean }
export const emptyReportApproval = (): ReportApproval => ({ previewKey: null, consent: false, ownership: false });
// 校验值同时绑定文字、来源和接收方；工作区更新时旧勾选立即失效。
export function reportPreviewKey(preview: ReportPreview | null | undefined): string | null {
  return preview ? `${preview.id}:${preview.hash}` : null;
}
export function updateReportApproval(current: ReportApproval, previewKey: string | null,
  field: 'consent' | 'ownership', checked: boolean): ReportApproval {
  const approval = current.previewKey === previewKey ? current : emptyReportApproval();
  return { ...approval, previewKey, [field]: checked };
}
export function approvedReportPreview(approval: ReportApproval, previewKey: string | null): boolean {
  return !!previewKey && approval.previewKey === previewKey && approval.consent && approval.ownership;
}

export interface ReportTextEditor { pages: ReportTextPage[]; modified: boolean; workspace: ReportWorkspace | null }
const jobTime = (workspace: ReportWorkspace) => Math.max(0,
  ...[workspace.extract_job, workspace.ai_job].map(job => job ? Date.parse(job.updated_at) : 0));
export function newerWorkspace(current: ReportWorkspace | null, incoming: ReportWorkspace): ReportWorkspace {
  if (current && (incoming.revision < current.revision ||
    (incoming.revision === current.revision && jobTime(incoming) < jobTime(current)))) return current;
  return incoming;
}
export function mergeReportTextEditor(current: ReportTextEditor, incoming: ReportWorkspace, pageCount: number, replace = false): ReportTextEditor {
  const workspace = newerWorkspace(current.workspace, incoming);
  if (workspace !== incoming) return current;
  if (current.modified && !replace) return { ...current, workspace };
  const pages = workspace.preview?.pages || workspace.extract_job?.result?.pages ||
    Array.from({ length: pageCount }, (_, index) => ({ page: index + 1, text: '' }));
  return { pages, modified: false, workspace };
}
