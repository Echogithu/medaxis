/** 患者端 API 服务层 */

import { API_BASE, authHeaders } from './client.ts';
import type { LabReportResult } from '../types/agent';

export interface PatientProfile {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  date_of_birth?: string;
  gender?: string | null;
  height?: number | null;
  weight?: number | null;
  age_years?: number | null;
  age_months?: number | null;
  revision?: number;
  updated_at?: string | null;
  section_states?: Partial<Record<ProfileSection, RecordState>>;
  section_metadata?: Partial<Record<ProfileSection, RecordMetadata>>;
  allergies?: string[];
  chronic_diseases?: DiseaseRecord[];
  medications?: MedicationRecord[];
}

export type RecordState = 'present' | 'none' | 'unknown' | 'not_recorded';
export type ProfileSection = 'allergies' | 'conditions' | 'medications';
export interface RecordMetadata { source?: string; updated_at?: string | null }
export interface DiseaseRecord extends RecordMetadata {
  id?: string;
  code?: string;
  name: string;
  category?: 'chronic' | 'special';
  severity?: 'unknown' | 'mild' | 'moderate' | 'severe';
  diagnosed_date?: string | null;
  notes?: string;
}
export interface MedicationRecord extends RecordMetadata {
  id?: string;
  name: string;
  dosage: string;
  frequency: string;
  start_date?: string | null;
  status?: 'active' | 'stopped';
}

export type PatientProfileUpdate = Pick<PatientProfile,
  'name' | 'phone' | 'gender' | 'height' | 'weight' | 'allergies' | 'chronic_diseases' | 'medications' | 'section_states'> & { expected_revision?: number };

export interface PatientReminder {
  id: string;
  event_type: string;
  payload: Record<string, unknown> | null;
  scheduled_at: string | null;
  triggered_at: string | null;
  acknowledged_at: string | null;
  status: string;
  retry_count: number;
  plan_id: string | null;
}

export interface PatientReminderAcknowledgement {
  success: boolean;
  id: string;
  status: string;
  acknowledged_at: string | null;
}

export interface PatientReminderCursor {
  scheduled_at: string;
  id: string;
}

export interface PatientReminderPage {
  items: PatientReminder[];
  next_cursor: PatientReminderCursor | null;
}

export interface MedicalCase {
  id: string;
  title: string;
  description: string;
  chief_complaint?: string;
  status: string;
  created_at: string | null;
  diagnosis?: string;
}

export interface CaseRecovery {
  case: { id: string; title: string; chief_complaint?: string; status: string; created_at: string | null };
  report: Record<string, unknown> | null;
  lab_reports: LabReportResult[];
  materials: Array<{
    file_id: string;
    filename: string;
    mime_type: string | null;
    status: 'queued' | 'processing' | 'completed' | 'failed';
    created_at: string | null;
  }>;
}

export interface ClinicalContext {
  start: number;
  end: number;
  text: string;
  experiencer: 'patient' | 'family' | 'unspecified';
  temporality: 'current' | 'historical' | 'hypothetical' | 'unspecified';
  negation: 'negated' | 'not_detected';
  certainty: 'reported' | 'uncertain' | 'unknown';
  status: 'present' | 'refuted' | 'historical' | 'hypothetical' | 'uncertain' | 'non_patient' | 'unknown' | 'needs_review' | 'reported';
  advisory: true;
}

export interface PatientContext {
  clinical_context_text?: string;
  clinical_context_source_id?: string;
  clinical_context?: ClinicalContext[];
}

export interface PreparationFact extends PatientContext {
  id: string;
  label: string;
  value?: unknown;
  display_value?: unknown;
  record_state?: RecordState;
  source_type?: string;
  source_id?: string;
  confirmed?: boolean;
  active?: boolean;
  status?: string;
  answer_status?: 'unknown';
  assertion_status?: 'affirmed' | 'denied' | 'reported';
  patient_response?: unknown;
  patient_response_history?: string[];
  patient_response_source_ids?: string[];
}

export interface UnresolvedPreparationFact {
  id: string;
  label: string;
  status: 'needs_reconciliation';
  source_type: 'patient_reported';
  source_id: string;
  statements: Array<{
    value: string;
    source_type: 'patient_reported';
    source_id: string;
    clinical_context_text?: string;
    clinical_context?: ClinicalContext[];
  }>;
}

export interface CasePreparationPackage {
  profile_record_states?: Partial<Record<ProfileSection, RecordState>>;
  package_id: string;
  case_id: string;
  version: number;
  revision: number;
  state: 'ready_for_review' | 'needs_reassessment';
  is_stale: boolean;
  source_fingerprint: string;
  known_facts: PreparationFact[];
  unknown_facts: PreparationFact[];
  unresolved_facts: UnresolvedPreparationFact[];
  department: {
    status: string;
    recommendation: string | null;
    reason: string;
    evidence_ids: string[];
    guidance_version?: string;
    scope_note?: string;
    risk_notes?: string[];
    references?: Array<{ id: string; title: string; url: string; published_at?: string; checked_at: string }>;
    options?: Array<{
      id: string;
      label: string;
      department: string;
      reference: { id: string; title: string; url: string; published_at?: string; checked_at: string };
    }>;
  };
  preparation_items: Array<{
    id: string;
    title: string;
    reason: string;
    source_file_ids: string[];
    status: 'pending' | 'ready';
  }>;
  source_index: Array<{
    id: string;
    source_type: string;
    name: string;
    file_id?: string;
    parse_status?: string;
    verified_citation: boolean;
    note: string;
  }>;
  unverified_knowledge_sources: Array<{
    name: string;
    verified_citation: boolean;
    note: string;
  }>;
  patient_questions: string[];
  summary: {
    case_title: string;
    patient_facts: PreparationFact[];
    unknown_facts: PreparationFact[];
    unresolved_facts: UnresolvedPreparationFact[];
    ai_inference: string[];
    materials: Array<{ file_id: string; filename: string; status: string }>;
    source_index: CasePreparationPackage['source_index'];
    unverified_knowledge_sources: CasePreparationPackage['unverified_knowledge_sources'];
    disclaimer: string;
  };
  patient_corrections: Array<{ fact_id: string; value: string }>;
  created_at: string | null;
  updated_at: string | null;
}

export interface CasePreparationResponse {
  package: CasePreparationPackage | null;
  history: CasePreparationPackage[];
}

export interface PostVisitFeedback {
  feedback_id: string;
  case_id: string;
  version: number;
  revision: number;
  source_type: 'patient_reported';
  self_reported_visit_at: string | null;
  actual_department: string | null;
  patient_summary: string | null;
  follow_up_items: string[];
  material_file_ids: string[];
  revision_history: Array<{
    revision: number;
    submitted_at: string | null;
    source_type: 'patient_reported';
    fields: Pick<PostVisitFeedback, 'self_reported_visit_at' | 'actual_department' | 'patient_summary' | 'follow_up_items' | 'material_file_ids'>;
  }>;
  created_at: string | null;
  updated_at: string | null;
}

export interface PostVisitFeedbackFields {
  self_reported_visit_at: string | null;
  actual_department: string | null;
  patient_summary: string | null;
  follow_up_items: string[];
  material_file_ids: string[];
}

export interface CarePlan {
  id: string;
  title: string;
  description?: string;
  goals: string[];
  tasks: CareTask[] | { tasks?: CareTask[] } | Record<string, unknown>;
  status?: string;
  progress_percent?: number;
  start_date?: string | null;
  end_date?: string | null;
  effective_status?: string;
  revision: number;
  source_type: string;
  source_case_id?: string | null;
  source_case_title?: string | null;
  confirmed_at?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
  can_execute: boolean;
  timezone?: string;
}

export interface CareTask {
  id?: string;
  description?: string;
  name?: string;
  due_date?: string;
  completed?: boolean;
  status?: string;
  type?: string;
  unit?: string;
  is_overdue?: boolean;
  last_value?: number | null;
  completion_notes?: string;
  completed_at?: string;
  completion_source?: string;
}

export interface CarePlanFields {
  title: string;
  description: string;
  source_case_id: string | null;
  start_date: string;
  end_date: string;
  tasks: Array<{ id?: string; type: 'follow_up' | 'self_check'; description: string; due_date: string; unit: string }>;
}
export interface CarePlanCursor { created_at: string; id: string }
export interface CarePlanPage { items: CarePlan[]; next_cursor: CarePlanCursor | null }
export type CarePlanAction = 'confirm' | 'pause' | 'resume' | 'cancel';

export async function getProfile(): Promise<PatientProfile> {
  const res = await fetch(`${API_BASE}/patient/profile`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch profile');
  return res.json();
}

export async function updateProfile(data: Partial<PatientProfileUpdate>): Promise<PatientProfile> {
  const res = await fetch(`${API_BASE}/patient/profile`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      name: data.name,
      phone: data.phone,
      gender: data.gender,
      height: data.height,
      weight: data.weight,
      allergies: data.allergies,
      chronic_diseases: data.chronic_diseases,
      medications: data.medications,
      section_states: data.section_states,
      expected_revision: data.expected_revision,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === 'string' ? body.detail : 'Failed to update profile';
    throw new ProfileSaveError(detail, res.status);
  }
  return res.json();
}

export class ProfileSaveError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function listCases(options: { page?: number; limit?: number } = {}): Promise<MedicalCase[]> {
  const page = options.page ?? 1;
  const limit = options.limit ?? 10;
  const query = new URLSearchParams({ page: String(page), limit: String(limit) });
  const res = await fetch(`${API_BASE}/patient/cases?${query}`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch cases');
  return res.json();
}

export async function getCaseRecovery(caseId: string): Promise<CaseRecovery> {
  const res = await fetch(`${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/recovery`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`无法读取病例材料（HTTP ${res.status}）`);
  return res.json();
}

export async function downloadCaseMaterial(caseId: string, fileId: string, filename: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/materials/${encodeURIComponent(fileId)}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error('无法下载病例材料');
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function getCasePreparation(caseId: string): Promise<CasePreparationResponse> {
  const res = await fetch(
    `${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/preparation`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error('无法读取就医准备内容');
  return res.json();
}

export async function createCasePreparation(caseId: string): Promise<CasePreparationPackage> {
  const res = await fetch(
    `${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/preparation`,
    { method: 'POST', headers: authHeaders() },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail?.message || '生成就医准备失败');
  }
  return res.json();
}

export async function updateCasePreparation(
  caseId: string,
  packageId: string,
  update: {
    expected_revision: number;
    confirmed_fact_ids: string[];
    patient_corrections: Array<{ fact_id: string; value: string }>;
    patient_questions: string[];
    checklist_updates: Array<{ item_id: string; status: 'pending' | 'ready' }>;
  },
): Promise<CasePreparationPackage> {
  const res = await fetch(
    `${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/preparation/${encodeURIComponent(packageId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(update),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail?.message || '保存失败，请重新载入后再试');
  }
  return res.json();
}

export async function getPostVisitFeedback(caseId: string): Promise<{ feedback: PostVisitFeedback | null; history: PostVisitFeedback[] }> {
  const res = await fetch(`${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/post-visit-feedback`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('无法读取诊后回填');
  return res.json();
}

async function savePostVisitFeedbackRequest(url: string, method: 'POST' | 'PATCH', body: object): Promise<Record<string, unknown>> {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const response = await res.json().catch(() => null);
    throw new Error(response?.detail?.message || response?.detail || '保存诊后回填失败');
  }
  return res.json();
}

export async function createPostVisitFeedback(caseId: string, fields: PostVisitFeedbackFields): Promise<{ created: boolean; feedback: PostVisitFeedback }> {
  const response = await savePostVisitFeedbackRequest(
    `${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/post-visit-feedback`, 'POST', fields,
  );
  return response as unknown as { created: boolean; feedback: PostVisitFeedback };
}

export async function updatePostVisitFeedback(caseId: string, feedbackId: string, expectedRevision: number, fields: PostVisitFeedbackFields): Promise<PostVisitFeedback> {
  const response = await savePostVisitFeedbackRequest(
    `${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/post-visit-feedback/${encodeURIComponent(feedbackId)}`,
    'PATCH', { ...fields, expected_revision: expectedRevision },
  );
  return response as unknown as PostVisitFeedback;
}

export async function listCarePlans(): Promise<CarePlan[]> {
  const res = await fetch(`${API_BASE}/patient/care-plans`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch care plans');
  return res.json();
}

export async function ackTask(planId: string, taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/patient/care-plans/${planId}/ack?task_id=${encodeURIComponent(taskId)}`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to ack task');
}

export async function getReminderCount(): Promise<{ follow_up: number; medication: number; total: number }> {
  const res = await fetch(`${API_BASE}/patient/reminders/count`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch reminder count');
  return res.json();
}

export async function listReminders(options: { cursor?: PatientReminderCursor | null; limit?: number } = {}): Promise<PatientReminderPage> {
  const limit = options.limit ?? 50;
  const query = new URLSearchParams({ limit: String(limit) });
  if (options.cursor) {
    query.set('cursor_at', options.cursor.scheduled_at);
    query.set('cursor_id', options.cursor.id);
  }
  const res = await fetch(`${API_BASE}/patient/reminders?${query}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to fetch reminders (HTTP ${res.status})`);
  return res.json();
}

async function carePlanRequest<T>(url: string, method = 'GET', body?: object): Promise<T> {
  const res = await fetch(`${API_BASE}/patient${url}`, {
    method, headers: { 'Content-Type': 'application/json', ...authHeaders() },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!res.ok) {
    const response = await res.json().catch(() => null);
    const detail = typeof response?.detail === 'string' ? response.detail : `随访操作失败（HTTP ${res.status}），请检查填写内容或重试`;
    throw new Error(detail);
  }
  return res.json();
}

export function listCarePlanPage(options: { status?: string; cursor?: CarePlanCursor | null; limit?: number } = {}): Promise<CarePlanPage> {
  const query = new URLSearchParams({ include_page: 'true', limit: String(options.limit ?? 10) });
  if (options.status) query.set('status', options.status);
  if (options.cursor) {
    query.set('cursor_at', options.cursor.created_at);
    query.set('cursor_id', options.cursor.id);
  }
  return carePlanRequest(`/care-plans?${query}`);
}

export function createCarePlan(fields: CarePlanFields, requestId: string): Promise<CarePlan> {
  return carePlanRequest('/care-plans', 'POST', { ...fields, request_id: requestId });
}
export function editCarePlan(planId: string, fields: CarePlanFields, revision: number): Promise<CarePlan> {
  return carePlanRequest(`/care-plans/${encodeURIComponent(planId)}`, 'PATCH', { ...fields, expected_revision: revision });
}
export function changeCarePlan(plan: CarePlan, action: CarePlanAction): Promise<CarePlan> {
  return carePlanRequest(`/care-plans/${encodeURIComponent(plan.id)}/actions`, 'POST', { action, expected_revision: plan.revision });
}
export function checkInCareTask(planId: string, taskId: string, notes: string, value?: number): Promise<{ plan: CarePlan }> {
  return carePlanRequest('/check-in', 'POST', { plan_id: planId, task_id: taskId, notes, ...(value === undefined ? {} : { value }) });
}

export async function acknowledgeReminder(reminderId: string): Promise<PatientReminderAcknowledgement> {
  const res = await fetch(`${API_BASE}/patient/reminders/${encodeURIComponent(reminderId)}/acknowledge`, {
    method: 'PATCH',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to acknowledge reminder (HTTP ${res.status})`);
  return res.json();
}

export interface PostVisitActionDraft {
  id: string; state: 'generating' | 'ready' | 'confirmed' | 'failed' | 'dismissed'; source_revision: number;
  follow_ups?: Array<{ id: string; description: string; evidence: string; due_date: string | null; type: string }>;
  medications?: Array<{ id: string; name: string; dosage: string; evidence: string; start_date: string | null; end_date: string | null; times: string[] }>;
  plan_id?: string | null; reminder_count?: number;
}
export interface PostVisitActionResult { draft: PostVisitActionDraft | null; source_revision: number }
export interface PostVisitActionPreview { text: string; source_revision: number; preview_hash: string; recipient: { provider: string; model: string; host: string } }
export interface PostVisitActionConfirmation {
  draft_id: string; source_revision: number; channel: 'in_app' | 'email';
  follow_ups: Array<{ id: string; due_date: string }>;
  medications: Array<{ id: string; start_date: string; end_date: string; times: string[] }>;
}
export function getPostVisitActions(caseId: string): Promise<PostVisitActionResult> {
  return carePlanRequest(`/cases/${encodeURIComponent(caseId)}/ai-actions`);
}
export function previewPostVisitActions(caseId: string): Promise<PostVisitActionPreview> {
  return carePlanRequest(`/cases/${encodeURIComponent(caseId)}/ai-actions/preview`);
}
export function generatePostVisitActions(caseId: string, preview: PostVisitActionPreview): Promise<PostVisitActionResult> {
  return carePlanRequest(`/cases/${encodeURIComponent(caseId)}/ai-actions/generate`, 'POST', {
    source_revision: preview.source_revision, preview_hash: preview.preview_hash, consent: true,
  });
}
export function confirmPostVisitActions(caseId: string, fields: PostVisitActionConfirmation): Promise<PostVisitActionResult> {
  return carePlanRequest(`/cases/${encodeURIComponent(caseId)}/ai-actions/confirm`, 'POST', fields);
}
export function dismissPostVisitActions(caseId: string, draftId: string): Promise<PostVisitActionResult> {
  return carePlanRequest(`/cases/${encodeURIComponent(caseId)}/ai-actions/dismiss`, 'POST', { draft_id: draftId });
}
export function pendingPostVisitActions(): Promise<{ items: Array<{ case_id: string; revision: number }> }> {
  return carePlanRequest('/ai-actions/pending');
}
