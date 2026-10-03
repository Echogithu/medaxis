import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material';
import { getToken } from '../api/client';
import { consultationActive, getConsultation, getConsultations } from '../api/consultations';
import type { ConsultationItem } from '../api/consultations';
import CreateConsultationDialog from './CreateConsultationDialog';
import ConsultationDetailPanel from './ConsultationDetailPanel';

export default function DoctorHandoffDialog({ caseId, requestedId, onClose, onCreated }: {
  caseId: string | null; requestedId: string | null; onClose: () => void; onCreated: (id: string) => void;
}) {
  const navigate = useNavigate();
  const authenticated = Boolean(getToken());
  const [item, setItem] = useState<ConsultationItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(authenticated && Boolean(caseId || requestedId));
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  const changed = useCallback(() => setVersion(v => v + 1), []);
  useEffect(() => {
    if (!authenticated || (!caseId && !requestedId)) return;
    let cancelled = false;
    const load = requestedId ? getConsultation(requestedId) : getConsultations(1, caseId!).then(result =>
      result.items.find(entry => consultationActive(entry.state)) || result.items[0] || null);
    load.then(result => {
      if (cancelled) return;
      setItem(result); setCreating(!result); setLoading(false); setError('');
    }).catch(e => { if (!cancelled) { setItem(null); setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [authenticated, caseId, requestedId, version]);
  const sharedCaseId = item?.case_id || caseId;
  if (creating && authenticated && sharedCaseId) return <CreateConsultationDialog caseId={sharedCaseId} onClose={onClose} onCreated={onCreated} />;
  return <Dialog open onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="doctor-handoff-title">
    <DialogTitle id="doctor-handoff-title">{item ? '医生接诊进度' : '转接真实医生'}</DialogTitle>
    <DialogContent dividers sx={{ p: item ? 0 : 3 }}>
      {loading ? <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress size={28} aria-label="加载医生接诊进度" /></Box>
        : error ? <Alert severity="error" action={<Button onClick={changed}>重试</Button>}>{error}</Alert>
          : !authenticated ? <Typography variant="body2">登录后可转接医生。</Typography>
            : !sharedCaseId ? <Typography variant="body2">请先完成并保存本次问诊，再转接医生。</Typography>
              : item && <ConsultationDetailPanel key={item.id} id={item.id} doctor={false} onChanged={changed} />}
    </DialogContent>
    <DialogActions sx={{ p: 2 }}>
      <Button onClick={onClose}>{item ? '关闭' : '继续问诊'}</Button>
      {!authenticated && <Button variant="contained" onClick={() => navigate('/login')}>登录</Button>}
      {item && !consultationActive(item.state) && <Button variant="contained" onClick={() => setCreating(true)}>重新转接</Button>}
    </DialogActions>
  </Dialog>;
}
