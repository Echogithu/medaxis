import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, Typography } from '@mui/material';
import { consultationActive, consultationLabels, getConsultationNotices, getConsultations, readConsultationNotice } from '../../api/consultations';
import type { ConsultationItem, ConsultationNotice } from '../../api/consultations';
import ConsultationDetailPanel from '../../components/ConsultationDetailPanel';

export default function DoctorHandoffRequests() {
  const [params, setParams] = useSearchParams();
  const selected = params.get('consultation_id');
  const [items, setItems] = useState<ConsultationItem[]>([]);
  const [notices, setNotices] = useState<ConsultationNotice[]>([]);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [noticeError, setNoticeError] = useState('');
  const [version, setVersion] = useState(0);
  const changed = useCallback(() => setVersion(v => v + 1), []);
  useEffect(() => {
    let cancelled = false;
    getConsultations(page).then(result => { if (!cancelled) { setItems(result.items); setMore(result.has_more); setLoading(false); setError(''); } })
      .catch(e => { if (!cancelled) { setItems([]); setLoading(false); setError(e.message); } });
    getConsultationNotices().then(result => { if (!cancelled) { setNotices(result); setNoticeError(''); } })
      .catch(e => { if (!cancelled) setNoticeError(e.message); });
    const focus = () => changed(); window.addEventListener('focus', focus);
    return () => { cancelled = true; window.removeEventListener('focus', focus); };
  }, [page, version, changed]);
  const select = (id: string | null) => { const next = new URLSearchParams(params); if (id) next.set('consultation_id', id); else next.delete('consultation_id'); setParams(next, { replace: true }); };
  const openNotice = async (notice: ConsultationNotice) => {
    const id = new URL(notice.action_url, window.location.origin).searchParams.get('consultation_id');
    if (!id) return;
    select(id);
    try { await readConsultationNotice(notice.id); changed(); } catch (e) { setNoticeError((e as Error).message); }
  };
  const active = items.filter(item => consultationActive(item.state));
  return <Paper component="section" aria-label="患者转接" elevation={0} sx={{ p: { xs: 2, sm: 3 }, borderRadius: '20px', mb: 3 }}>
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}><Typography variant="h6">患者转接</Typography><Button onClick={changed}>刷新转接</Button></Box>
    {error && <Alert severity="error">{error}</Alert>}
    {noticeError && <Alert severity="warning">{noticeError}</Alert>}
    <Stack spacing={1}>
      {notices.filter(notice => !notice.is_read).slice(0, 5).map(notice => <Button key={notice.id} onClick={() => openNotice(notice)} sx={{ justifyContent: 'flex-start' }}>{notice.subject}</Button>)}
      {loading ? <CircularProgress size={24} aria-label="加载患者转接" /> : !active.length ? <Typography variant="body2" color="text.secondary">暂无待接诊转接</Typography> : active.map(item => <Button key={item.id} aria-label={`查看咨询：${item.case_title || '本次问诊'}`} onClick={() => select(item.id)} sx={{ justifyContent: 'space-between', gap: 1, textAlign: 'left', p: 1.5, border: '1px solid #e4ece9', borderRadius: '12px' }}>
        <Typography sx={{ overflowWrap: 'anywhere' }}>{item.case_title || '本次问诊'}</Typography><Chip size="small" label={item.state === 'awaiting_patient' ? '等待患者补充' : consultationLabels[item.state]} />
      </Button>)}
    </Stack>
    {(page > 1 || more) && <Stack direction="row" spacing={1} sx={{ mt: 2 }}><Button disabled={page === 1} onClick={() => { setLoading(true); setPage(v => v - 1); }}>上一页</Button><Button disabled={!more} onClick={() => { setLoading(true); setPage(v => v + 1); }}>下一页</Button></Stack>}
    {selected && <Dialog open onClose={() => select(null)} fullWidth maxWidth="sm" aria-labelledby="doctor-request-title"><DialogTitle id="doctor-request-title">患者转接</DialogTitle><DialogContent dividers sx={{ p: 0 }}><ConsultationDetailPanel key={selected} id={selected} doctor onChanged={changed} /></DialogContent><DialogActions><Button onClick={() => select(null)}>关闭</Button></DialogActions></Dialog>}
  </Paper>;
}
