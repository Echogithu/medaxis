import PendingPostVisitActions from '../components/PendingPostVisitActions';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Container,
  Stack, Typography,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlineOutlined';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import MedicationOutlinedIcon from '@mui/icons-material/MedicationOutlined';
import { Link as RouterLink } from 'react-router-dom';
import {
  acknowledgeReminder, listReminders, type PatientReminder, type PatientReminderCursor,
} from '../../api/patient.ts';
import { pageHeader } from '../../styles/sxUtils';
import { carePalette } from '../../theme';

const PAGE_SIZE = 50;
const warmText = carePalette.ink;
const warmPrimary = carePalette.primary;

interface ReminderLoadError {
  cursor: PatientReminderCursor | null;
  append: boolean;
  message: string;
}

function groupByDate(reminders: PatientReminder[]): Record<string, PatientReminder[]> {
  const groups: Record<string, PatientReminder[]> = {};
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date());
  const tomorrow = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date(Date.now() + 86400000));
  for (const reminder of reminders) {
    const date = reminder.scheduled_at ? new Date(reminder.scheduled_at) : null;
    const dateString = date && !Number.isNaN(date.getTime()) ? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(date) : null;
    const label = !dateString
      ? '时间待定'
      : dateString === today
        ? '今天'
        : dateString === tomorrow
          ? '明天'
          : date!.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: 'numeric', day: 'numeric' });
    groups[label] = [...(groups[label] || []), reminder];
  }
  return groups;
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '等待发送',
    in_flight: '正在发送',
    sent: '待你确认',
    acknowledged: '已打卡（患者自报）',
    failed: '发送失败',
    cancelled: '已取消',
  };
  return labels[status] ?? `状态：${status}`;
}

function getLoadErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : '';
  if (message.includes('HTTP 401')) return '登录状态可能已过期，请重新登录后重试。';
  return '提醒加载失败，请检查网络或稍后重试。';
}

export default function MedicationReminderPage() {
  const [reminders, setReminders] = useState<PatientReminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<PatientReminderCursor | null>(null);
  const [loadError, setLoadError] = useState<ReminderLoadError | null>(null);
  const [acking, setAcking] = useState<Set<string>>(new Set());
  const [ackErrors, setAckErrors] = useState<Record<string, string>>({});

  const loadPage = useCallback(async (cursor: PatientReminderCursor | null, append: boolean) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    setLoadError(null);
    try {
      const result = await listReminders({ cursor, limit: PAGE_SIZE });
      setReminders(current => append ? [...current, ...result.items] : result.items);
      setNextCursor(result.next_cursor);
    } catch (error) {
      setLoadError({ cursor, append, message: getLoadErrorMessage(error) });
    } finally {
      if (append) setLoadingMore(false);
      else setLoading(false);
    }
  }, []);

  useEffect(() => {
    let isCurrent = true;
    void listReminders({ limit: PAGE_SIZE })
      .then(results => {
        if (!isCurrent) return;
        setReminders(results.items);
        setNextCursor(results.next_cursor);
      })
      .catch(error => {
        if (isCurrent) setLoadError({ cursor: null, append: false, message: getLoadErrorMessage(error) });
      })
      .finally(() => {
        if (isCurrent) setLoading(false);
      });
    return () => { isCurrent = false; };
  }, []);

  const handleAck = async (id: string) => {
    setAcking(current => new Set(current).add(id));
    setAckErrors(current => {
      const next = { ...current };
      delete next[id];
      return next;
    });
    try {
      const result = await acknowledgeReminder(id);
      setReminders(current => current.map(reminder => reminder.id === id
        ? { ...reminder, status: result.status, acknowledged_at: result.acknowledged_at }
        : reminder));
    } catch {
      setAckErrors(current => ({ ...current, [id]: '打卡未保存，请重试；若仍失败，请重新登录后再试。' }));
    } finally {
      setAcking(current => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  };

  const grouped = useMemo(() => groupByDate(reminders), [reminders]);
  const checkInStats = useMemo(() => {
    const delivered = reminders.filter(reminder => ['sent', 'acknowledged'].includes(reminder.status));
    const acknowledged = delivered.filter(reminder => reminder.status === 'acknowledged').length;
    return {
      delivered: delivered.length,
      acknowledged,
      percentage: delivered.length ? Math.round((acknowledged / delivered.length) * 100) : null,
    };
  }, [reminders]);

  return (
    <Box sx={{ pb: 6 }}>
      <Container maxWidth="md">
        <Box sx={pageHeader}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography component="h1" variant="h5" sx={{ fontWeight: 600, color: warmText }}>用药提醒</Typography>
          </Box>
          <Button component={RouterLink} to="/health" sx={{ flexShrink: 0 }}>用药清单</Button>
        </Box>

        <PendingPostVisitActions />
        {checkInStats.delivered > 0 && <Chip size="small" label={`已加载的已送达提醒 · 已打卡 ${checkInStats.acknowledged}/${checkInStats.delivered} · 患者自报`} sx={{ mb: 2, bgcolor: carePalette.mint, color: carePalette.primaryDark, maxWidth: '100%', height: 'auto', '& .MuiChip-label': { py: 0.75, whiteSpace: 'normal' } }} />}

        {loading && reminders.length === 0 && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress sx={{ color: warmPrimary }} />
          </Box>
        )}

        {loadError && (
          <Alert
            severity="error"
            sx={{ mb: 2 }}
            action={(
              <Button color="inherit" size="small" onClick={() => void loadPage(loadError.cursor, loadError.append)}>
                重试
              </Button>
            )}
          >
            {loadError.message}
          </Alert>
        )}

        {!loading && !loadError && reminders.length === 0 && (
          <Card sx={{ textAlign: 'center', py: 7, px: 3 }}>
            <Box sx={{ width: 56, height: 56, mx: 'auto', mb: 2, display: 'grid', placeItems: 'center', borderRadius: '18px', bgcolor: carePalette.amberSoft, color: carePalette.amber }}><MedicationOutlinedIcon sx={{ fontSize: 28 }} /></Box>
            <Typography sx={{ fontWeight: 600, color: warmText, mb: 2 }}>暂无用药提醒</Typography>
            <Button component={RouterLink} to="/cases">查看问诊记录</Button>
          </Card>
        )}

        <Stack spacing={2}>
          {Object.entries(grouped).map(([label, items]) => (
            <Card key={label} sx={{ borderRadius: 3 }}>
              <CardContent sx={{ pb: 1 }}>
                <Typography variant="subtitle1" sx={{ color: warmText, fontWeight: 600, mb: 1 }}>
                  {label}
                </Typography>
                <Stack spacing={1}>
                  {items.map(reminder => {
                    const payload = reminder.payload ?? {};
                    const payloadName = typeof payload.name === 'string' ? payload.name : null;
                    const description = typeof payload.description === 'string' ? payload.description : null;
                    const dosage = typeof payload.dosage === 'string' ? payload.dosage : '';
                    const name = payloadName || description || reminder.event_type;
                    const isDone = reminder.status === 'acknowledged';
                    const isAcking = acking.has(reminder.id);
                    const schedule = reminder.scheduled_at ? new Date(reminder.scheduled_at) : null;
                    const timeLabel = schedule && !Number.isNaN(schedule.getTime())
                      ? schedule.toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit' })
                      : '时间待定';
                    return (
                      <Box key={reminder.id}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: { xs: 1.5, sm: 2 }, py: 1.5, flexWrap: 'wrap', '& + &': { borderTop: '1px solid #f1f5f9' } }}>
                          <Typography sx={{ width: { xs: 56, sm: 72 }, fontSize: { xs: 18, sm: 22 }, fontWeight: 600, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>{timeLabel}</Typography>
                          {isDone
                            ? <CheckCircleIcon sx={{ color: warmPrimary, fontSize: 22, display: { xs: 'none', sm: 'block' } }} />
                            : <CheckCircleOutlineIcon sx={{ color: warmPrimary, fontSize: 22, display: { xs: 'none', sm: 'block' } }} />}
                          <Box sx={{ flex: 1, minWidth: 0 }}>
                            <Typography variant="body2" sx={{ color: warmText, fontWeight: 600, overflowWrap: 'anywhere', textDecoration: isDone ? 'line-through' : 'none' }}>
                              {name}
                            </Typography>
                            <Typography variant="caption" sx={{ color: carePalette.muted }}>
                              {dosage && `${dosage} · `}{getStatusLabel(reminder.status)}
                            </Typography>
                          </Box>
                          {reminder.status === 'sent' && (
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => void handleAck(reminder.id)}
                              disabled={isAcking}
                              sx={{ borderRadius: 2, textTransform: 'none', minWidth: 72, color: warmPrimary, borderColor: warmPrimary, fontSize: 12 }}
                            >
                              {isAcking ? '提交中…' : reminder.event_type === 'medication_reminder' ? '我已服用' : '我已查看'}
                            </Button>
                          )}
                        </Box>
                        {ackErrors[reminder.id] && (
                          <Typography role="alert" variant="caption" color="error.main" sx={{ display: 'block', pl: 4 }}>
                            {ackErrors[reminder.id]}
                          </Typography>
                        )}
                      </Box>
                    );
                  })}
                </Stack>
              </CardContent>
            </Card>
          ))}
        </Stack>

        {nextCursor && !loadError?.append && reminders.length > 0 && (
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
            <Button onClick={() => void loadPage(nextCursor, true)} disabled={loadingMore}>
              {loadingMore ? <CircularProgress size={18} sx={{ mr: 1 }} /> : null}
              加载更多提醒
            </Button>
          </Box>
        )}
      </Container>
    </Box>
  );
}
