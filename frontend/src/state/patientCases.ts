export interface PatientCaseId {
  id: string;
}

export const CASE_MATERIAL_POLL_INTERVAL_MS = 1500;
export const CASE_MATERIAL_MAX_POLL_ATTEMPTS = 80;

export function shouldPollCaseMaterials(
  materials: Array<{ status: string }>,
  attempts: number,
): boolean {
  return attempts < CASE_MATERIAL_MAX_POLL_ATTEMPTS
    && materials.some(material => material.status === 'queued' || material.status === 'processing');
}

export function initialCaseSelection(
  requestedCaseId: string | null,
  cases: PatientCaseId[],
): string {
  return requestedCaseId || cases[0]?.id || '';
}

export function mergeCasePage<T extends PatientCaseId>(current: T[], incoming: T[]): T[] {
  const seen = new Set(current.map(item => item.id));
  const appended: T[] = [];
  for (const item of incoming) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    appended.push(item);
  }
  return [...current, ...appended];
}
