import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material';
import { actOnConsultation, ConsultationError, consultationActive, consultationLabels, getConsultation, replyToConsultation } from '../api/consultations';
import type { ConsultationDetail } from '../api/consultations';
import ConsultationSharedRecord from './ConsultationSharedRecord';

const categories: Record<string, string> = { report_explanation: '报告解读', health_advice: '健康建议', visit_advice: '就医建议', request_information: '补充资料' };
const actions: Record<string, string> = { accept: '医生已接受咨询', decline: '医生婉拒了咨询', cancel: '患者已取消共享', end: '咨询已结束' };
export default function ConsultationDetailPanel({ id, doctor, onChanged }: { id: string; doctor: boolean; onChanged: () => void }) {
  const [detail, setDetail] = useState<ConsultationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState('');
  const [category, setCategory] = useState('health_advice');
  const [nextState, setNextState] = useState('awaiting_patient');
  const [confirmation, setConfirmation] = useState('');
  const [reason, setReason] = useState('');
  const request = useRef({ key: '', id: '' });
  const sequence = useRef(0);
  const refresh = useCallback(async () => {
    const current = ++sequence.current;
    setLoading(true);
    try { const value = await getConsultation(id); if (sequence.current === current) { setDetail(value); setError(''); } }
    catch (e) { if (sequence.current === current) {
      setDetail(null); setError((e as Error).message);
      if (e instanceof ConsultationError && [401, 403, 404].includes(e.status)) {
        setDraft(''); setReason(''); setConfirmation(''); onChanged();
      }
    } }
    finally { if (sequence.current === current) setLoading(false); }
  }, [id, onChanged]);
  useEffect(() => {
    const tracker = sequence;
    const current = ++tracker.current;
    getConsultation(id).then(value => { if (tracker.current === current) { setDetail(value); setError(''); setLoading(false); } })
      .catch(e => { if (tracker.current === current) { setDetail(null); setError(e.message); setLoading(false); } });
    const focus = () => { void refresh(); };
    window.addEventListener('focus', focus);
    return () => { ++tracker.current; window.removeEventListener('focus', focus); };
  }, [id, refresh]);
  const mutate = async (action?: string) => {
    if (!detail || busy) return;
    // 响应丢失后刷新会改变版本号；同一内容必须沿用编号，避免重复发布。
    const key = JSON.stringify(action ? { action, reason: reason.trim() } : { body: draft.trim(), ...(doctor ? { category, next_state: nextState } : {}) });
    if (request.current.key !== key) request.current = { key, id: crypto.randomUUID() };
    setBusy(true); setError('');
    try {
      const result = action ? await actOnConsultation(id, { expected_revision: detail.revision, action, reason: reason.trim(), request_id: request.current.id })
        : await replyToConsultation(id, { expected_revision: detail.revision, body: draft.trim(), ...(doctor ? { category, next_state: nextState } : {}), request_id: request.current.id });
      request.current = { key: '', id: '' }; setDraft(''); setConfirmation(''); setReason('');
      if (doctor && !consultationActive(result.state)) { ++sequence.current; setDetail(null); setError('本次咨询已结束，共享授权已停止。'); }
      else await refresh();
      onChanged();
    } catch (e) {
      // 同步最新状态，同时保留未发送内容；网络结果不确定时沿用提交编号。
      await refresh(); setError((e as Error).message); onChanged();
    } finally { setBusy(false); }
  };
  return <Paper elevation={0} sx={{ p: { xs: 2, sm: 3 }, borderRadius: '24px', minWidth: 0, bgcolor: '#fff' }}>
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}><Typography component="h2" variant="h6">咨询详情</Typography><Button onClick={refresh} disabled={busy || loading}>刷新</Button></Box>
    {error && <Alert severity={detail ? 'error' : 'info'} sx={{ mb: 2 }}>{error}</Alert>}
    {loading && <Box sx={{ textAlign: 'center', p: 3 }}><CircularProgress size={26} aria-label="加载咨询详情" /></Box>}
    {detail && !loading && <Stack spacing={2.5}>
      <Box><Chip size="small" label={doctor && detail.state === 'awaiting_patient' ? '等待患者补充' : consultationLabels[detail.state]} color={consultationActive(detail.state) ? 'primary' : 'default'} variant="outlined" />
        <Typography sx={{ mt: 1, fontWeight: 650 }}>{doctor ? detail.snapshot.case_title : `${detail.doctor.name} · ${detail.doctor.department || '医生'}`}</Typography>
        <Typography variant="body2" sx={{ mt: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{detail.question}</Typography></Box>
      <ConsultationSharedRecord snapshot={detail.snapshot} />
      <Box component="section" aria-label="医生建议与留言"><Typography variant="subtitle2" sx={{ mb: 1.5 }}>医生建议与留言</Typography>
        {!detail.messages.length && <Typography variant="body2" color="text.secondary">等待医生接诊。</Typography>}
        <Stack spacing={1.5}>{detail.messages.map(message => <Box key={message.id} sx={{ p: 2, borderRadius: '16px', bgcolor: message.author.role === 'doctor' ? '#edf8f4' : '#f6f8f7' }}>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 0.75 }}><Typography variant="body2" sx={{ fontWeight: 650 }}>{message.author.name || (message.author.role === 'doctor' ? '医生' : '患者')}</Typography>
            {message.category && <Chip size="small" label={categories[message.category] || message.category} sx={{ height: 22 }} />}
            <Typography variant="caption" color="text.secondary">{new Date(message.created_at).toLocaleString('zh-CN')}</Typography></Box>
          {message.kind !== 'message' && <Typography variant="body2">{actions[message.kind] || '状态已更新'}</Typography>}
          {message.body && <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{message.body}</Typography>}
        </Box>)}</Stack>
      </Box>
      {doctor && detail.state === 'pending' && <Stack direction="row" spacing={1}><Button variant="contained" disabled={busy} onClick={() => mutate('accept')}>接受咨询</Button><Button disabled={busy} onClick={() => setConfirmation('decline')}>婉拒</Button></Stack>}
      {['accepted', 'awaiting_patient'].includes(detail.state) && <Box>
        {doctor && <Alert severity="info" sx={{ mb: 2 }}>请提供报告解读、健康或就医建议；正式诊断和处方需通过医疗机构完成。</Alert>}
        <TextField fullWidth multiline minRows={3} label={doctor ? '给患者的建议' : '补充说明'} value={draft} onChange={e => setDraft(e.target.value)} disabled={busy} slotProps={{ htmlInput: { maxLength: 5000 } }} />
        {doctor && <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mt: 2 }}>
          <TextField select label="建议类别" value={category} onChange={e => setCategory(e.target.value)} fullWidth disabled={busy}>{Object.entries(categories).map(([value, label]) => <MenuItem value={value} key={value}>{label}</MenuItem>)}</TextField>
          <TextField select label="回复后" value={nextState} onChange={e => setNextState(e.target.value)} fullWidth disabled={busy}><MenuItem value="awaiting_patient">等待患者补充</MenuItem><MenuItem value="completed">完成本次咨询</MenuItem></TextField>
        </Stack>}
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}><Button variant="contained" disabled={busy || !draft.trim()} onClick={() => nextState === 'completed' && doctor ? setConfirmation('reply_complete') : mutate()}>{busy ? '正在发送…' : doctor ? '发布建议' : '发送补充'}</Button></Box>
      </Box>}
      {!doctor && consultationActive(detail.state) && <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}><Button color="inherit" disabled={busy} onClick={() => setConfirmation('cancel')}>取消咨询与共享</Button></Box>}
    </Stack>}
    <Dialog open={Boolean(confirmation)} onClose={busy ? undefined : () => setConfirmation('')} fullWidth maxWidth="xs" aria-labelledby="consultation-action-title">
      <DialogTitle id="consultation-action-title">{confirmation === 'decline' ? '婉拒本次咨询' : confirmation === 'cancel' ? '取消咨询与共享？' : '发布建议并完成咨询？'}</DialogTitle>
      <DialogContent>{confirmation === 'decline' ? <TextField autoFocus multiline minRows={2} fullWidth label="婉拒原因" value={reason} onChange={e => setReason(e.target.value)} disabled={busy} slotProps={{ htmlInput: { maxLength: 1000 } }} sx={{ mt: 1 }} /> : <Typography variant="body2">结束后医生将无法继续查看共享资料，患者可保留咨询记录。</Typography>}</DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => setConfirmation('')}>返回</Button><Button variant="contained" disabled={busy || (confirmation === 'decline' && !reason.trim())} onClick={() => mutate(confirmation === 'reply_complete' ? undefined : confirmation)}>{confirmation === 'decline' ? '确认婉拒' : confirmation === 'cancel' ? '确认取消' : '确认发布'}</Button></DialogActions>
    </Dialog>
  </Paper>;
}
