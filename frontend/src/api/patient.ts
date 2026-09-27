/** 患者端 API 服务层 */

import { API_BASE } from './client';

import { authHeaders } from './client';

export interface PatientProfile {
  id: string;
  name: string;
  email: string;
  phone?: string;
  date_of_birth?: string;
  gender?: string;
  height?: number;
  weight?: number;
  allergies?: string[];
  chronic_diseases?: { code: string; name: string }[];
  medications?: Array<{
    name: string;
    dosage: string;
    frequency: string;
    start_date?: string;
  }>;
}

export interface MedicalCase {
  id: string;
  title: string;
  description: string;
  chief_complaint?: string;
  status: string;
  created_at: string;
  diagnosis?: string;
}

export interface CaseRecovery {
  case: { id: string; title: string; chief_complaint?: string; status: string; created_at: string | null };
  report: Record<string, unknown> | null;
  lab_reports: Array<Record<string, unknown>>;
  materials: Array<{
    file_id: string;
    filename: string;
    mime_type: string | null;
    status: 'queued' | 'processing' | 'completed' | 'failed';
    created_at: string | null;
  }>;
}

export interface PreparationFact {
  id: string;
  label: string;
  value?: unknown;
  source_type?: string;
  source_id?: string;
  confirmed?: boolean;
  active?: boolean;
  status?: string;
}

export interface CasePreparationPackage {
  package_id: string;
  case_id: string;
  version: number;
  revision: number;
  state: 'ready_for_review' | 'needs_reassessment';
  is_stale: boolean;
  source_fingerprint: string;
  known_facts: PreparationFact[];
  unknown_facts: PreparationFact[];
  department: {
    status: string;
    recommendation: string | null;
    reason: string;
    evidence_ids: string[];
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
}

export interface CareTask {
  id?: string;
  description?: string;
  name?: string;
  due_date?: string;
  completed?: boolean;
  status?: string;
}

export async function getProfile(): Promise<PatientProfile> {
  const res = await fetch(`${API_BASE}/patient/profile`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch profile');
  return res.json();
}

export async function updateProfile(data: Partial<PatientProfile>): Promise<PatientProfile> {
  const res = await fetch(`${API_BASE}/patient/profile`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Failed to update profile');
  return res.json();
}

export async function listCases(): Promise<MedicalCase[]> {
  const res = await fetch(`${API_BASE}/patient/cases`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch cases');
  return res.json();
}

export async function getCaseRecovery(caseId: string): Promise<CaseRecovery> {
  const res = await fetch(`${API_BASE}/patient/cases/${encodeURIComponent(caseId)}/recovery`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('无法读取病例材料');
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

export async function listReminders(): Promise<unknown[]> {
  const res = await fetch(`${API_BASE}/patient/reminders`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch reminders');
  return res.json();
}

export async function acknowledgeReminder(reminderId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/patient/reminders/${reminderId}/ack`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('Failed to acknowledge reminder');
}
