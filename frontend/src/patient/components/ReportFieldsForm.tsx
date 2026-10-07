import { MenuItem, Stack, TextField } from '@mui/material';
import type { ReportFields } from '../../api/reports';
import { reportCategories } from '../../state/reportFields';
export default function ReportFieldsForm({ value, onChange, disabled = false }: {
  value: ReportFields; onChange: (value: ReportFields) => void; disabled?: boolean;
}) {
  const update = (key: keyof ReportFields, text: string) => onChange({ ...value, [key]: ['examination_date', 'report_date'].includes(key) ? text || null : text });
  return <Stack spacing={2}>
    <TextField label="报告名称" required value={value.title} disabled={disabled} onChange={e => update('title', e.target.value)} slotProps={{ htmlInput: { maxLength: 200 } }} />
    <TextField select label="报告类别" value={value.category} disabled={disabled} onChange={e => update('category', e.target.value)}>
      {Object.entries(reportCategories).map(([key, label]) => <MenuItem key={key} value={key}>{label}</MenuItem>)}
    </TextField>
    <TextField label="医院或机构" value={value.institution} disabled={disabled} onChange={e => update('institution', e.target.value)} slotProps={{ htmlInput: { maxLength: 200 } }} />
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
      <TextField label="检查日期" type="date" value={value.examination_date || ''} disabled={disabled} onChange={e => update('examination_date', e.target.value)} fullWidth slotProps={{ inputLabel: { shrink: true } }} helperText="未知可留空" />
      <TextField label="报告日期" type="date" value={value.report_date || ''} disabled={disabled} onChange={e => update('report_date', e.target.value)} fullWidth slotProps={{ inputLabel: { shrink: true } }} helperText="以原件日期为准" />
    </Stack>
    <TextField label="备注" value={value.notes} disabled={disabled} onChange={e => update('notes', e.target.value)} multiline minRows={2} slotProps={{ htmlInput: { maxLength: 4000 } }} />
  </Stack>;
}
