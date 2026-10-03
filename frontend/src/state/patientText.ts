const informationLabels: Record<string, string> = {
  adv_stool_pattern: '大便的性状与次数', adv_epidemic: '近期饮食及接触情况',
  hpi_onset: '症状起始时间', hpi_quality: '症状特点', hpi_severity: '严重程度',
  hpi_associated: '伴随表现', pmh_chronic: '既往疾病', pmh_allergy: '过敏情况', med_current: '当前用药',
};

/** 患者展示层：隐藏内部标识，保留数值、单位及可理解的内容。 */
export function patientText(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value
    .replace(/\b(?:adv|hpi|pmh|ps|fh|med)_[a-z0-9_]+\b/g, key => informationLabels[key] ?? '')
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
