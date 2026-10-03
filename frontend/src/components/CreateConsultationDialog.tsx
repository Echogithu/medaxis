import { useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Checkbox, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { ConsultationError, createConsultation, getConsultationDoctors, getConsultationPreview } from '../api/consultations';
import type { ConsultationPreview, DoctorProfile } from '../api/consultations';
import ConsultationSharedRecord from './ConsultationSharedRecord';

export default function CreateConsultationDialog({ caseId, onClose, onCreated }: { caseId: string; onClose: () => void; onCreated: (id: string) => void }) {
  const [preview, setPreview] = useState<ConsultationPreview | null>(null);
  const [doctors, setDoctors] = useState<DoctorProfile[]>([]);
  const [doctor, setDoctor] = useState('');
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [question, setQuestion] = useState('');
  const [materials, setMaterials] = useState<string[]>([]);
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const request = useRef({ key: '', id: '' });
  useEffect(() => {
    let cancelled = false;
    Promise.all([getConsultationPreview(caseId), getConsultationDoctors()]).then(([record, directory]) => {
      if (cancelled) return;
      setPreview(record); setDoctors(directory.items); setDoctor(''); setMore(directory.has_more); setPage(1);
      setMaterials([]); setConsent(false); setLoading(false);
    }).catch(e => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [caseId, reload]);
  const refresh = () => { setError(''); setLoading(true); setPreview(null); setReload(v => v + 1); };
  const loadMore = async () => {
    setBusy(true); setError('');
    try { const result = await getConsultationDoctors(page + 1); setDoctors(v => [...v, ...result.items]); setMore(result.has_more); setPage(v => v + 1); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const submit = async () => {
    if (!preview || !consent || !doctor || !question.trim()) return;
    const payload = { case_id: caseId, doctor_id: doctor, question: question.trim(), source_fingerprint: preview.source_fingerprint, material_ids: [...materials].sort(), share_confirmed: true as const };
    const key = JSON.stringify(payload);
    if (request.current.key !== key) request.current = { key, id: crypto.randomUUID() };
    setBusy(true); setError('');
    try { const item = await createConsultation({ ...payload, request_id: request.current.id }); onCreated(item.id); }
    catch (e) {
      setError((e as Error).message);
      if (e instanceof ConsultationError && e.status === 409) setConsent(false);
    } finally { setBusy(false); }
  };
  return <Dialog open onClose={busy ? undefined : onClose} fullWidth maxWidth="sm" aria-labelledby="create-consultation-title">
    <DialogTitle id="create-consultation-title">转接真实医生</DialogTitle>
    <DialogContent dividers>
      {error && <Alert severity="error" sx={{ mb: 2 }} action={<Button color="inherit" onClick={refresh} disabled={busy}>重新核对</Button>}>{error}</Alert>}
      {loading ? <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress size={28} aria-label="加载可共享资料" /></Box> : preview && <Stack spacing={2.5}>
        <TextField select fullWidth label="选择医生" value={doctor} onChange={e => { setDoctor(e.target.value); setConsent(false); }} disabled={busy}>
          {doctors.map(item => <MenuItem key={item.id} value={item.id}>{[item.name, item.title, item.hospital, item.department].filter(Boolean).join(' · ')}</MenuItem>)}
        </TextField>
        {!doctors.length && <Alert severity="info">暂无可接诊的认证医生，请稍后再试。</Alert>}
        {more && <Button onClick={loadMore} disabled={busy}>加载更多医生</Button>}
        <TextField label="希望医生帮你解答什么？" multiline minRows={3} fullWidth value={question} onChange={e => setQuestion(e.target.value)} disabled={busy} slotProps={{ htmlInput: { maxLength: 2000 } }} />
        <ConsultationSharedRecord snapshot={{ ...preview, materials: preview.materials.filter(item => materials.includes(item.file_id)) }} />
        {!!preview.materials.length && <Box><Typography variant="subtitle2">选择共享的报告解析结果</Typography>
          {preview.materials.map(item => <FormControlLabel key={item.file_id} sx={{ display: 'flex', '& .MuiFormControlLabel-label': { overflowWrap: 'anywhere' } }} control={<Checkbox checked={materials.includes(item.file_id)} disabled={busy || (!materials.includes(item.file_id) && materials.length >= 10)} onChange={(_, checked) => { setMaterials(v => checked ? [...v, item.file_id] : v.filter(id => id !== item.file_id)); setConsent(false); }} />} label={item.filename} />)}
        </Box>}
        <Box>
          <FormControlLabel control={<Checkbox checked={consent} disabled={busy} onChange={(_, checked) => setConsent(checked)} />} label="我同意向所选医生共享本次摘要及勾选的报告解析结果" />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4 }}>仅共享当前资料快照；后续资料不会自动加入，不提供原件下载。</Typography>
        </Box>
      </Stack>}
    </DialogContent>
    <DialogActions sx={{ p: 2 }}><Button onClick={onClose} disabled={busy}>取消</Button><Button variant="contained" disabled={loading || busy || !preview || !doctor || !question.trim() || !consent} onClick={submit}>{busy ? '正在转接…' : '确认转接'}</Button></DialogActions>
  </Dialog>;
}
