import { API_BASE, authHeaders } from './client.ts';
export interface HealthMeasurement {
  id: string; systolic: number | null; diastolic: number | null; heart_rate: number | null;
  weight: number | null; recorded_at: string; created_at: string; source: 'patient_reported';
}
export type MeasurementFields = Pick<HealthMeasurement, 'systolic' | 'diastolic' | 'heart_rate' | 'weight' | 'recorded_at'>;
async function request<T>(query: string, body?: MeasurementFields & { request_id: string }): Promise<T> {
  const response = await fetch(`${API_BASE}/patient/measurements${query}`, {
    method: body ? 'POST' : 'GET', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : '健康指标操作失败，请核对读数和记录时间后重试');
  }
  return response.json();
}
export const listMeasurements = async (page = 1) => {
  const data = await request<{ items: HealthMeasurement[]; has_more: boolean }>(`?page=${page}`);
  if (!Array.isArray(data?.items) || typeof data.has_more !== 'boolean') throw new Error('健康指标暂时无法读取，请稍后重试');
  return data;
};
export const createMeasurement = (fields: MeasurementFields, requestId: string) => request<HealthMeasurement>('', { ...fields, request_id: requestId });
