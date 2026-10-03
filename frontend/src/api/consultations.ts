import { API_BASE, jsonHeaders } from './client';
import type { DiagnosisReport, LabReportResult } from '../types/agent';

export type ConsultationState = 'pending' | 'accepted' | 'awaiting_patient' | 'completed' | 'declined' | 'cancelled' | 'unavailable';
export interface DoctorProfile { id: string; name: string; role: string; hospital?: string; department?: string; title?: string }
export interface SharedSnapshot {
  case_title: string; chief_complaint?: string; description?: string; ai_summary?: string;
  report?: DiagnosisReport; materials: { file_id: string; filename: string; result: LabReportResult }[];
}
export interface ConsultationPreview extends SharedSnapshot { source_fingerprint: string }
export interface ConsultationItem {
  id: string; case_id: string; state: ConsultationState; revision: number; doctor: DoctorProfile;
  case_title?: string; question: string; created_at: string; updated_at: string;
}
export interface ConsultationDetail extends ConsultationItem {
  snapshot: SharedSnapshot;
  messages: { id: string; author: DoctorProfile; kind: string; body: string; category?: string; created_at: string }[];
}
export interface ConsultationNotice { id: string; subject: string; action_url: string; is_read: boolean; created_at: string }
export class ConsultationError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}
async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`${API_BASE}/consultations${path}`, {
    method: body ? 'POST' : 'GET', headers: jsonHeaders(), ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ConsultationError(response.status, typeof data?.detail === 'string' ? data.detail : '操作失败，请重试');
  return data;
}
export const getConsultationDoctors = (page = 1) => request<{ items: DoctorProfile[]; has_more: boolean }>(`/doctors?page=${page}`);
export const getConsultationPreview = (caseId: string) => request<ConsultationPreview>(`/preview/${encodeURIComponent(caseId)}`);
export const getConsultations = (page = 1, caseId?: string) => request<{ items: ConsultationItem[]; has_more: boolean }>(`?page=${page}${caseId ? `&case_id=${encodeURIComponent(caseId)}` : ''}`);
export const getConsultation = (id: string) => request<ConsultationDetail>(`/${encodeURIComponent(id)}`);
export const getConsultationNotices = () => request<ConsultationNotice[]>('/notifications');
export const readConsultationNotice = (id: string) => request(`/notifications/${encodeURIComponent(id)}/read`, {});
export const createConsultation = (body: { request_id: string; case_id: string; doctor_id: string; question: string; source_fingerprint: string; material_ids: string[]; share_confirmed: true }) => request<ConsultationItem>('', body);
export const actOnConsultation = (id: string, body: { request_id: string; expected_revision: number; action: string; reason: string }) => request<ConsultationItem>(`/${id}/actions`, body);
export const replyToConsultation = (id: string, body: { request_id: string; expected_revision: number; body: string; category?: string; next_state?: string }) => request<ConsultationItem>(`/${id}/messages`, body);

export const consultationLabels: Record<ConsultationState, string> = {
  pending: '等待医生接诊', accepted: '医生处理中', awaiting_patient: '等待你补充', completed: '咨询已完成',
  declined: '医生已婉拒', cancelled: '已取消共享', unavailable: '医生暂不可用',
};
export const consultationActive = (state: ConsultationState) => ['pending', 'accepted', 'awaiting_patient'].includes(state);
