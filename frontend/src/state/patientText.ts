/** 患者展示层：只隐藏明确的内部标识，不改写数值、单位或原始记录。 */
export function patientText(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value
    .replace(/(?:患者\s*(?:ID|编号)|patient[_ ]?id)[*`"'\s]*[:：=]\s*[`"']?[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}[`"']?/gi, '')
    .replace(/(?:ICD[-\s]?11|icd11_code)[*`"'\s]*[:：=]\s*[`"']?[A-Z0-9][A-Z0-9.-]*[`"']?/gi, '')
    .replace(/(?:retrieved_chunks|internal_sources|external_sources)[`"'\s]*[:=：]\s*\d+\s*[,，;；]?/gi, '')
    .replace(/腹泻型肠易激综合征\s*[（(]IBS-D[）)]/gi, '腹泻型肠易激综合征')
    .replace(/\bIBS-D\b/gi, '腹泻型肠易激综合征')
    .replace(/[（(]\s*[,，;；]*\s*[）)]/g, '')
    .trim();
}

export function patientList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(patientText).filter(Boolean) : [];
}
