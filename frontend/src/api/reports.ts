/** 独立报告接口；上传不会转入旧 documents 外发解析入口。 */
import { API_BASE, authHeaders, jsonHeaders } from './client.ts';

export type ReportCategory = 'lab' | 'imaging' | 'other';
export interface ReportFields {
  title: string; category: ReportCategory; institution: string;
  examination_date: string | null; report_date: string | null; notes: string;
}
export interface ReportFile {
  id: string; position: number; filename: string; mime_type: string; byte_size: number; page_count: number;
}
export interface PatientReport extends ReportFields {
  id: string; revision: number; source_version: number; created_at: string; updated_at: string;
  ownership_declared: boolean; source: string; archive_status: string; extraction_status: string;
  review_status: string; file_count: number; page_count: number; files: ReportFile[];
  ai_status?: string;
  confirmed_at?: string | null; confirmed_revision?: number | null; review_revision?: number;
  upload_outcome?: 'archived' | 'reused';
  lifecycle_revision: number; trashed_at: string | null;
}
export type DuplicateReport = Pick<PatientReport, 'id' | 'title' | 'category' | 'institution' | 'examination_date' | 'report_date' | 'created_at'>;
export interface ReportDuplicateChoice { duplicate_mode: 'separate' | 'reuse'; duplicate_report_id?: string }
export class DuplicateReportError extends Error {
  reports: DuplicateReport[]; more: boolean;
  constructor(message: string, reports: DuplicateReport[], more: boolean) {
    super(message); this.reports = reports; this.more = more;
  }
}
export interface ReportPage {
  items: PatientReport[]; total: number; page: number; limit: number;
  stats: { archived: number; pending_review: number; latest_examination_date: string | null; trashed: number };
}
export class ReportError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}
async function check(response: Response): Promise<Response> {
  if (response.ok) return response;
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  if (response.status === 409 && detail?.code === 'duplicate_report' && Array.isArray(detail.reports)) {
    throw new DuplicateReportError(detail.message, detail.reports, detail.more === true);
  }
  const message = typeof detail === 'string' ? detail : typeof detail?.message === 'string' ?
    `${Number.isInteger(detail.file_position) ? `文件 ${detail.file_position + 1}：` : ''}${detail.message}` :
    response.status === 401 ? '登录已过期，请重新登录' : response.status === 404 ? '报告不存在或无法访问' : '报告操作失败，请重试';
  throw new ReportError(message, response.status);
}
export async function listReports(options: { page?: number; search?: string; category?: ReportCategory; pending_only?: boolean; archive?: 'active' | 'trash' } = {}): Promise<ReportPage> {
  const query = new URLSearchParams({ page: String(options.page || 1), limit: '12' });
  if (options.search) query.set('search', options.search);
  if (options.category) query.set('category', options.category);
  if (options.pending_only) query.set('pending_only', 'true');
  if (options.archive) query.set('archive', options.archive);
  return (await check(await fetch(`${API_BASE}/patient/reports?${query}`, { headers: authHeaders() }))).json();
}
export async function getReport(id: string): Promise<PatientReport> {
  return (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}`, { headers: authHeaders() }))).json();
}
export async function uploadReport(fields: ReportFields, files: File[], requestId: string, ownershipDeclared: boolean, choice?: ReportDuplicateChoice): Promise<PatientReport> {
  const body = new FormData();
  body.append('metadata', JSON.stringify({ ...fields, request_id: requestId, ownership_declared: ownershipDeclared, ...choice }));
  files.forEach(file => body.append('files', file));
  return (await check(await fetch(`${API_BASE}/patient/reports`, { method: 'POST', headers: authHeaders(), body }))).json();
}
export async function editReport(id: string, fields: ReportFields, revision: number): Promise<PatientReport> {
  return (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: jsonHeaders(), body: JSON.stringify({ ...fields, expected_revision: revision }),
  }))).json();
}
export async function getReportOriginal(reportId: string, fileId: string): Promise<Blob> {
  return (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(reportId)}/files/${encodeURIComponent(fileId)}`, { headers: authHeaders() }))).blob();
}

export interface ReportTextPage { page: number; text: string; file_id?: string; file_page?: number; method?: string }
export interface ReportRecipient { provider: string; model: string; host: string; origin: string }
export interface ReportPreview {
  id: string; hash: string; policy: string; source_version: number; pages: ReportTextPage[]; text: string;
  recipient: ReportRecipient | null; warning: string | null; expires_at: string; consumed_by?: string;
}
export interface ReportIndicator {
  name: string; raw_value: string; unit: string | null; reference_range: string | null;
  abnormal_mark: string | null; source_page: number; evidence: string;
}
export interface ReportSection { kind: 'findings' | 'conclusion' | 'other'; text: string; source_page: number; evidence: string }
export interface ReportCandidate {
  indicators: ReportIndicator[]; sections: ReportSection[]; review_status: 'unverified'; needs_manual_entry: boolean;
  preview_id: string; preview_hash: string; evidence_source: 'consented_text';
}
export interface ReportJob {
  id: string; request_id: string; kind: 'extract' | 'ai'; status: string; source_version: number; updated_at: string;
  dispatch_started_at: string | null; error_code: string | null; error_message: string | null;
  result: ({ pages?: ReportTextPage[]; needs_manual_entry?: boolean } & Partial<ReportCandidate>) | null;
}
export interface ReportWorkspace {
  revision: number; source_version: number; category: ReportCategory;
  extract_job: ReportJob | null; ai_job: ReportJob | null; preview: ReportPreview | null;
}
interface WorkflowReply { job?: ReportJob; preview?: ReportPreview; workspace: ReportWorkspace; message?: string }
export async function getReportWorkspace(id: string): Promise<ReportWorkspace> {
  return (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/workspace`, { headers: authHeaders() }))).json();
}
async function workflowPost(id: string, action: string, body?: unknown): Promise<WorkflowReply> {
  return (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/${action}`, {
    method: 'POST', headers: jsonHeaders(), ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }))).json();
}
function workflowVersion(workspace: ReportWorkspace) {
  return { expected_source_version: workspace.source_version, expected_workflow_revision: workspace.revision };
}
export const extractReportText = (id: string, workspace: ReportWorkspace, requestId: string) =>
  workflowPost(id, 'extract', { ...workflowVersion(workspace), request_id: requestId });
export const previewReportText = (id: string, workspace: ReportWorkspace, pages?: ReportTextPage[]) =>
  workflowPost(id, 'preview', { ...workflowVersion(workspace), ...(pages === undefined ? {} : { pages: pages.map(({ page, text }) => ({ page, text })) }) });
export const organizeReportText = (id: string, preview: ReportPreview, requestId: string, consent: boolean, ownership: boolean) =>
  workflowPost(id, 'ai', { request_id: requestId, preview_id: preview.id, preview_hash: preview.hash,
    expected_source_version: preview.source_version, consent, ownership_confirmed: ownership });
export const cancelReportJob = (id: string, jobId: string) => workflowPost(id, `jobs/${encodeURIComponent(jobId)}/cancel`);

export interface ReviewIndicator extends Omit<ReportIndicator, 'source_page' | 'evidence'> { source_page: number | null; evidence: string | null }
export interface ReviewSection extends Omit<ReportSection, 'source_page' | 'evidence'> { source_page: number | null; evidence: string | null }
export interface ReviewContent { indicators: ReviewIndicator[]; sections: ReviewSection[] }
export interface ReviewOrigin { based_on_version_id: string | null; candidate_job_id: string | null }
export interface ReportReviewVersion extends ReviewOrigin {
  id: string; request_id: string; revision: number; kind: 'draft' | 'confirmed'; category: ReportCategory;
  source_version: number; source_epoch: number; source_current: boolean; confirmed_draft_id: string | null;
  created_at: string; content?: ReviewContent; original_candidate?: Partial<ReportCandidate> | null;
}
export interface ReportReviewWorkspace {
  revision: number; source_epoch: number; source_version: number; source_hash: string; category: ReportCategory;
  review_status: string; confirmed_at: string | null;
  draft: ReportReviewVersion | null; confirmed: ReportReviewVersion | null;
  candidate: { job_id: string; content: ReviewContent } | null;
}
export interface ReviewReply { version: ReportReviewVersion; workspace: ReportReviewWorkspace }
export const getReportReview = async (id: string): Promise<ReportReviewWorkspace> =>
  (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/review`, { headers: authHeaders() }))).json();
function reviewVersion(workspace: ReportReviewWorkspace) {
  return { expected_revision: workspace.revision, expected_source_epoch: workspace.source_epoch,
    expected_source_version: workspace.source_version, expected_source_hash: workspace.source_hash };
}
async function reviewPost(id: string, action: string, body: unknown): Promise<ReviewReply> {
  return (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/review/${action}`, {
    method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body),
  }))).json();
}
export const saveReportReviewDraft = (id: string, workspace: ReportReviewWorkspace, content: ReviewContent, origin: ReviewOrigin, requestId: string) =>
  reviewPost(id, 'drafts', { ...reviewVersion(workspace), request_id: requestId, content, ...origin });
export const confirmReportReview = (id: string, workspace: ReportReviewWorkspace, draftId: string, requestId: string, checked: boolean) =>
  reviewPost(id, 'confirm', { ...reviewVersion(workspace), request_id: requestId, draft_id: draftId, checked_against_original: checked });
export const getReportReviewHistory = async (id: string, page = 1): Promise<{ items: ReportReviewVersion[]; total: number; page: number; limit: number }> =>
  (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/review/history?page=${page}&limit=20`, { headers: authHeaders() }))).json();
export const getReportReviewVersion = async (id: string, versionId: string): Promise<ReportReviewVersion> =>
  (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/review/versions/${encodeURIComponent(versionId)}`, { headers: authHeaders() }))).json();

export type ReportLinkStatus = 'unverified' | 'patient_confirmed' | 'source_changed' | 'review_changed';
export interface ReportCaseLink {
  case_id: string; title: string; case_status: string; source_version: number;
  review_version_id: string | null; review_revision: number | null; status: ReportLinkStatus;
  created_at: string; updated_at: string;
}
export interface ReportLinksWorkspace {
  links_revision: number; review_revision: number; source_epoch: number; source_hash: string; source_version: number;
  current_review_version_id: string | null; items: ReportCaseLink[];
}
export interface ReportCaseOptions {
  items: { id: string; title: string; status: string; created_at: string }[];
  total: number; page: number; limit: number;
}
export interface ReportLinksReply {
  operation: { id: string; request_id: string; revision: number }; workspace: ReportLinksWorkspace;
}
export const getReportLinks = async (id: string): Promise<ReportLinksWorkspace> =>
  (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/case-links`, { headers: authHeaders() }))).json();
export const listReportCaseOptions = async (id: string, search = '', page = 1): Promise<ReportCaseOptions> => {
  const query = new URLSearchParams({ search, page: String(page), limit: '10' });
  return (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/case-options?${query}`, { headers: authHeaders() }))).json();
};
export const saveReportLinks = async (id: string, workspace: ReportLinksWorkspace, caseIds: string[], refreshIds: string[], requestId: string): Promise<ReportLinksReply> =>
  (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/case-links`, {
    method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ request_id: requestId,
      expected_links_revision: workspace.links_revision, expected_review_revision: workspace.review_revision,
      expected_source_hash: workspace.source_hash, case_ids: caseIds, refresh_case_ids: refreshIds }),
  }))).json();
export interface CaseReportsPage {
  items: (PatientReport & { link: Pick<ReportCaseLink, 'source_version' | 'review_version_id' | 'review_revision' | 'status' | 'updated_at'> })[];
  total: number; page: number; limit: number;
}
export const listCaseReports = async (caseId: string, page = 1): Promise<CaseReportsPage> =>
  (await check(await fetch(`${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/reports?page=${page}&limit=10`, { headers: authHeaders() }))).json();

export type ReportLifecycleAction = 'trash' | 'restore' | 'purge';
export interface ReportLifecycleWorkspace {
  report: PatientReport; state_token: string; links_count: number; pending_jobs: number; has_dispatched_text: boolean;
}
export interface ReportLifecycleReply {
  operation: { request_id: string; kind: ReportLifecycleAction; revision: number };
  deleted: boolean; workspace: ReportLifecycleWorkspace | null;
}
export const getReportLifecycle = async (id: string): Promise<ReportLifecycleWorkspace> =>
  (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/lifecycle`, { headers: authHeaders() }))).json();
export const changeReportLifecycle = async (id: string, action: ReportLifecycleAction, stateToken: string, requestId: string, permanentConfirmed = false): Promise<ReportLifecycleReply> =>
  (await check(await fetch(`${API_BASE}/patient/reports/${encodeURIComponent(id)}/lifecycle/${action}`, {
    method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ request_id: requestId, expected_state_token: stateToken,
      ...(action === 'purge' ? { confirmed_permanent_delete: permanentConfirmed } : {}) }),
  }))).json();
