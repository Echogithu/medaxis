import { useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Card, CardContent, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Grid, Stack, TextField, Typography } from '@mui/material';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import { createMeasurement, listMeasurements } from '../../api/measurements';
import type { HealthMeasurement, MeasurementFields } from '../../api/measurements';
import { carePalette } from '../../theme';

const localMinute = () => { const date = new Date(); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const timeText = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false });
const readingText = (item: HealthMeasurement) => [item.systolic != null ? `${item.systolic}/${item.diastolic} mmHg` : '', item.heart_rate != null ? `心率 ${item.heart_rate} 次/分` : '', item.weight != null ? `${item.weight} kg` : ''].filter(Boolean).join(' · ');

export default function HealthMeasurementsPanel({ open, onClose, onOpen }: { open: boolean; onClose: () => void; onOpen: () => void }) {
  const [items, setItems] = useState<HealthMeasurement[]>([]);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [fields, setFields] = useState({ systolic: '', diastolic: '', heart_rate: '', weight: '', recorded_at: localMinute() });
  const submitted = useRef({ key: '', id: '' });
  useEffect(() => {
    let alive = true;
    listMeasurements().then(result => { if (alive) { setItems(result.items); setPage(1); setMore(result.has_more); setError(''); setLoading(false); } })
      .catch(e => { if (alive) { setError(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [reload]);
  const loadMore = async () => {
    setLoading(true); setError('');
    try { const result = await listMeasurements(page + 1); setItems(v => [...v, ...result.items.filter(item => !v.some(old => old.id === item.id))]); setPage(v => v + 1); setMore(result.has_more); }
    catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  const save = async () => {
    const values = Object.fromEntries(['systolic', 'diastolic', 'heart_rate', 'weight'].map(key => [key, fields[key as keyof typeof fields].trim() ? Number(fields[key as keyof typeof fields]) : null])) as Omit<MeasurementFields, 'recorded_at'>;
    if (Object.values(values).every(value => value == null)) { setFormError('请至少填写一项健康指标'); return; }
    if ((values.systolic == null) !== (values.diastolic == null)) { setFormError('血压需同时填写收缩压与舒张压'); return; }
    if (values.systolic != null && values.systolic <= values.diastolic!) { setFormError('收缩压应大于舒张压，请核对读数'); return; }
    if (Object.entries(values).some(([key, value]) => value != null && (!Number.isFinite(value) || (key !== 'weight' && !Number.isInteger(value))
      || value < ({ systolic: 40, diastolic: 20, heart_rate: 20, weight: 2 }[key as keyof typeof values])
      || value > ({ systolic: 300, diastolic: 200, heart_rate: 250, weight: 500 }[key as keyof typeof values])))) { setFormError('请核对健康指标读数'); return; }
    const date = new Date(fields.recorded_at);
    if (!fields.recorded_at || Number.isNaN(date.getTime()) || date.getTime() > Date.now()) { setFormError('请选择有效的记录时间，不能晚于当前时间'); return; }
    const payload = { ...values, recorded_at: date.toISOString() };
    const key = JSON.stringify(payload);
    if (submitted.current.key !== key) submitted.current = { key, id: crypto.randomUUID() };
    setBusy(true); setFormError('');
    try {
      await createMeasurement(payload, submitted.current.id);
      setFields({ systolic: '', diastolic: '', heart_rate: '', weight: '', recorded_at: localMinute() });
      submitted.current = { key: '', id: '' }; setReload(v => v + 1); onClose();
    } catch (e) { setFormError(`${(e as Error).message}；填写内容已保留。`); } finally { setBusy(false); }
  };
  const latest = items[0];
  return <>
    <Card><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}>
      <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 2.5 }}><Typography component="h2" variant="h6">最近一次健康记录</Typography><MonitorHeartOutlinedIcon sx={{ color: carePalette.primary }} /></Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }} action={<Button disabled={loading} onClick={() => more && items.length ? void loadMore() : setReload(v => v + 1)}>重试</Button>}>{error}</Alert>}
      {loading && !latest ? <CircularProgress size={24} aria-label="加载健康指标" /> : latest ? <Grid container spacing={2.5}>
        {[['血压 · mmHg', latest.systolic == null ? '未记录' : `${latest.systolic}/${latest.diastolic}`], ['静息心率 · 次/分', latest.heart_rate ?? '未记录'], ['体重 · kg', latest.weight ?? '未记录'], ['记录时间', timeText(latest.recorded_at)]].map(([label, value]) => <Grid key={label} size={6}><Typography variant="caption">{label}</Typography><Typography sx={{ mt: .5, overflowWrap: 'anywhere' }}>{value}</Typography></Grid>)}
      </Grid> : !error && <Typography color="text.secondary">暂无健康指标记录</Typography>}
      <Button variant="outlined" startIcon={<MonitorHeartOutlinedIcon />} onClick={onOpen} sx={{ mt: 3 }}>添加记录</Button>
    </CardContent></Card>
    <Card><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}>
      <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 1 }}><Typography component="h2" variant="h6">指标记录</Typography><Typography variant="caption">本人记录</Typography></Stack>
      {!items.length && !loading && !error && <Typography variant="body2" color="text.secondary">暂无记录</Typography>}
      {items.map(item => <Box key={item.id} sx={{ py: 2, borderBottom: '1px solid', borderColor: 'divider', '&:last-child': { borderBottom: 0 } }}><Typography sx={{ fontWeight: 600 }}>{readingText(item)}</Typography><Typography variant="caption" sx={{ display: 'block', mt: .5 }}>{timeText(item.recorded_at)}</Typography></Box>)}
      {loading && !!items.length && <CircularProgress size={20} aria-label="加载更多指标" />}
      {more && <Button disabled={loading} onClick={loadMore}>加载更多记录</Button>}
    </CardContent></Card>
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="sm" aria-labelledby="measurement-title" slotProps={{ transition: { onEnter: () => { if (!fields.systolic && !fields.diastolic && !fields.heart_rate && !fields.weight) setFields(v => ({ ...v, recorded_at: localMinute() })); } } }}>
      <DialogTitle id="measurement-title">记录健康指标</DialogTitle><DialogContent dividers><Stack spacing={2.5} sx={{ pt: 1 }}>
        <Typography variant="body2" color="text.secondary">填写本次测量结果，至少记录一项。</Typography>
        {formError && <Alert severity="error">{formError}</Alert>}
        <Grid container spacing={2}>
          {([{ key: 'systolic', label: '收缩压（mmHg）' }, { key: 'diastolic', label: '舒张压（mmHg）' }, { key: 'heart_rate', label: '静息心率（次/分）' }, { key: 'weight', label: '体重（kg）' }] as const).map(({ key, label }) => <Grid key={key} size={{ xs: 12, sm: 6 }}><TextField fullWidth type="number" label={label} value={fields[key]} onChange={e => setFields(v => ({ ...v, [key]: e.target.value }))} disabled={busy} slotProps={{ htmlInput: { step: key === 'weight' ? .1 : 1 } }} /></Grid>)}
        </Grid>
        <TextField type="datetime-local" label="记录时间" value={fields.recorded_at} onChange={e => setFields(v => ({ ...v, recorded_at: e.target.value }))} disabled={busy} slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: localMinute() } }} />
      </Stack></DialogContent><DialogActions sx={{ p: 2.5 }}><Button disabled={busy} onClick={onClose}>取消</Button><Button variant="contained" disabled={busy} onClick={save}>{busy ? '保存中…' : '保存记录'}</Button></DialogActions>
    </Dialog>
  </>;
}
