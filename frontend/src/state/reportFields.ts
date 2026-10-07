import type { ReportCategory, ReportFields } from '../api/reports';

export const reportCategories: Record<ReportCategory, string> = { lab: '检验报告', imaging: '影像报告文字', other: '其他报告' };
export function fieldsOf(value: ReportFields): ReportFields {
  return { title: value.title, category: value.category, institution: value.institution,
    examination_date: value.examination_date, report_date: value.report_date, notes: value.notes };
}
