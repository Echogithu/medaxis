import { useState, useEffect, useMemo } from 'react';
import {
  Container, Box, Typography, Card, CardContent,
  Button, Chip, Stack, CircularProgress, LinearProgress, linearProgressClasses,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlineOutlined';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { authHeaders } from '../../api/client';
import { pageHeader } from '../../styles/sxUtils';
import { carePalette } from '../../theme';

const warmText = carePalette.ink;
const warmPrimary = carePalette.primary;

function groupByDate(reminders: any[]): Record<string, any[]> {
  const groups: Record<string, any[]> = {};
  const today = new Date().toDateString();
  const tomorrow = new Date(Date.now() + 86400000).toDateString();
  for (const r of reminders) {
    const ds = new Date(r.scheduled_at).toDateString();
    if (ds === today) { groups['今天'] = [...(groups['今天'] || []), r]; }
    else if (ds === tomorrow) { groups['明天'] = [...(groups['明天'] || []), r]; }
    else {
      const label = new Date(r.scheduled_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' });
      groups[label] = [...(groups[label] || []), r];
    }
  }
  return groups;
}

export default function MedicationReminderPage() {
  const [reminders, setReminders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [acking, setAcking] = useState<Set<string>>(new Set());

  const fetchReminders = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/patient/reminders?limit=100', { headers: authHeaders() });
      if (res.ok) setReminders(await res.json());
      else setReminders([]);
    } catch { setReminders([]); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchReminders(); }, []);

  const handleAck = async (id: string) => {
    setAcking(new Set(acking).add(id));
    try {
      await fetch(`/api/v1/patient/reminders/${id}/acknowledge`, {
        method: 'PATCH', headers: authHeaders(),
      });
      setReminders(prev => prev.map(r => r.id === id
        ? { ...r, status: 'acknowledged', acknowledged_at: new Date().toISOString() } : r));
    } catch {}
    setAcking(prev => { const s = new Set(prev); s.delete(id); return s; });
  };

  const grouped = useMemo(() => groupByDate(reminders), [reminders]);
  const adherencePct = useMemo(() => {
    if (!reminders.length) return 100;
    return Math.round((reminders.filter(r => r.status === 'acknowledged' || r.acknowledged_at).length / reminders.length) * 100);
  }, [reminders]);

  return (
    <Box sx={{ pb: 6 }}>
      <Container maxWidth="md">
        <Box sx={pageHeader}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="h5" sx={{ fontWeight: 700, color: warmText }}>用药提醒</Typography>
            <Typography variant="body2" sx={{ color: carePalette.muted, mt: 0.4 }}>按时间打卡，便于了解近期服药情况。</Typography>
          </Box>
          <Typography variant="body2" sx={{ color: warmPrimary, fontWeight: 600 }}>
            依从性 {adherencePct}%
          </Typography>
        </Box>
        <LinearProgress variant="determinate" value={adherencePct}
          sx={{ mb: 2, height: 8, borderRadius: 4, bgcolor: carePalette.line,
            [`& .${linearProgressClasses.bar}`]: { bgcolor: adherencePct > 80 ? '#4CAF50' : adherencePct > 50 ? warmPrimary : '#f44336' } }} />
        {loading && <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress sx={{ color: warmPrimary }} /></Box>}
        {!loading && reminders.length === 0 && (
          <Box sx={{ textAlign: 'center', py: 8, px: 2, border: '1px dashed #d7e4df', borderRadius: 3, bgcolor: '#fbfcfb' }}>
            <Typography sx={{ fontWeight: 700, color: warmText, mb: 0.75 }}>暂无用药提醒</Typography>
            <Typography variant="body2" sx={{ color: carePalette.muted }}>在健康档案中记录正在服用的药物后，提醒会显示在这里。</Typography>
          </Box>
        )}
        <Stack spacing={2}>
          {Object.entries(grouped).map(([label, items]) => (
            <Card key={label} sx={{ borderRadius: 3 }}>
              <CardContent sx={{ pb: 1 }}>
                <Typography variant="subtitle1" sx={{ color: warmText, fontWeight: 600, mb: 1 }}>
                  {label}
                </Typography>
                <Stack spacing={0.5}>
                  {items.map(r => {
                    const payload = r.payload || {};
                    const name = payload.name || payload.description || r.event_type;
                    const dosage = payload.dosage || '';
                    const isDone = r.status === 'acknowledged' || r.acknowledged_at;
                    const isAcking = acking.has(r.id);
                    return (
                      <Box key={r.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1 }}>
                        {isDone
                          ? <CheckCircleIcon sx={{ color: '#4CAF50', fontSize: 20 }} />
                          : <CheckCircleOutlineIcon sx={{ color: warmPrimary, fontSize: 20 }} />}
                        <Typography variant="body2" sx={{
                          flex: 1, color: warmText,
                          textDecoration: isDone ? 'line-through' : 'none',
                        }}>
                          <Chip label={new Date(r.scheduled_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                            size="small" sx={{ mr: 1, height: 22, fontSize: 11, bgcolor: carePalette.mint, color: warmText }} />
                          {name}{dosage && <span style={{ color: carePalette.muted }}> · {dosage}</span>}
                        </Typography>
                        {!isDone && (
                          <Button size="small" variant="outlined" onClick={() => handleAck(r.id)} disabled={isAcking}
                            sx={{ borderRadius: 2, textTransform: 'none', minWidth: 60, color: warmPrimary, borderColor: warmPrimary, fontSize: 12 }}>
                            {isAcking ? '...' : '打卡'}
                          </Button>
                        )}
                        {isDone && <Typography variant="caption" color="success.main">✔</Typography>}
                      </Box>
                    );
                  })}
                </Stack>
              </CardContent>
            </Card>
          ))}
        </Stack>
      </Container>
    </Box>
  );
}
