import { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { confirmPostVisitActions, dismissPostVisitActions, generatePostVisitActions, getPostVisitActions, previewPostVisitActions } from '../../api/patient';
import type { PostVisitActionDraft, PostVisitActionPreview } from '../../api/patient';

type Schedule = { selected: boolean; date: string; end: string; times: string };
export default function PostVisitActionsPanel({ caseId, revision, dirty, onBusyChange }: { caseId: string; revision: number; dirty: boolean; onBusyChange: (busy: boolean) => void }) {
  const [draft, setDraft] = useState<PostVisitActionDraft | null>(null);
  const [preview, setPreview] = useState<PostVisitActionPreview | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [channel, setChannel] = useState<'in_app' | 'email'>('in_app');
  const [values, setValues] = useState<Record<string, Schedule>>({});
  const [dismissOpen, setDismissOpen] = useState(false);
  const sourceKey = useRef('');
  sourceKey.current = `${caseId}:${revision}`;
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  const hydrate = (next: PostVisitActionDraft | null) => {
    setDraft(next);
    const schedules: Record<string, Schedule> = {};
    next?.follow_ups?.forEach(t => { schedules[t.id] = { selected: false, date: t.due_date || '', end: '', times: '' }; });
    next?.medications?.forEach(t => { schedules[t.id] = { selected: false, date: t.start_date || '', end: t.end_date || '', times: t.times.join(', ') }; });
    setValues(schedules);
  };
  useEffect(() => {
    let alive = true;
    setLoading(true); setPreview(null); setConsent(false); hydrate(null); setError('');
    getPostVisitActions(caseId).then(data => {
      if (alive && data.source_revision !== revision) throw new Error('就诊记录已更新，请重新载入整页');
      if (alive) hydrate(data.draft);
    })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : '读取失败'); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [caseId, revision]);
  const operate = async (fn: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await fn(); } catch (err) { setError(err instanceof Error ? err.message : '操作失败，请重试'); } finally { setBusy(false); }
  };
  const update = (id: string, changes: Partial<Schedule>) => setValues(old => ({ ...old, [id]: { ...old[id], ...changes } }));
  const openPreview = () => void operate(async () => {
    const key = sourceKey.current;
    setConsent(false);
    const next = await previewPostVisitActions(caseId);
    if (key !== sourceKey.current) return;
    if (next.source_revision !== revision) throw new Error('就诊记录已更新，请重新载入就诊结果');
    setPreview(next);
  });
  const confirm = () => {
    if (!draft) return;
    const follows = (draft.follow_ups || []).filter(t => values[t.id]?.selected);
    const drugs = (draft.medications || []).filter(t => values[t.id]?.selected);
    if (follows.some(t => !values[t.id].date) || drugs.some(t => !values[t.id].date || !values[t.id].end || !values[t.id].times.trim())) {
      setError('请补齐所选事项的日期和用药提醒时刻'); return;
    }
    const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date());
    if (follows.some(t => values[t.id].date < today) || drugs.some(t => {
      const v = values[t.id], times = v.times.split(/[,，]/).map(s => s.trim()).filter(Boolean);
      return v.date < today || v.end < v.date || (Date.parse(v.end) - Date.parse(v.date)) / 86400000 > 90 ||
        times.length < 1 || times.length > 6 || new Set(times).size !== times.length || times.some(s => !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(s));
    })) { setError('请核对日期范围及提醒时刻（HH:mm，每日1至6个不重复时刻，单次最多91天）'); return; }
    void operate(async () => hydrate((await confirmPostVisitActions(caseId, { draft_id: draft.id, source_revision: revision, channel,
      follow_ups: follows.map(t => ({ id: t.id, due_date: values[t.id].date })),
      medications: drugs.map(t => ({ id: t.id, start_date: values[t.id].date, end_date: values[t.id].end,
        times: values[t.id].times.split(/[,，]/).map(v => v.trim()).filter(Boolean) })) })).draft));
  };
  return <Box sx={{ mt: 3, pt: 2, borderTop: '1px solid', borderColor: 'divider' }}>
    <Typography variant="h6">从就诊结果整理安排</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>AI 提取已有复查和用药事项，请对照医嘱核对。确认后才会创建计划或提醒。</Typography>
    {dirty && <Alert severity="info">当前有未保存修改，请先保存就诊结果。修改记录会停用旧安排。</Alert>}
    {error && <Alert severity="error">{error}<Button disabled={busy} onClick={() => void operate(async () => hydrate((await getPostVisitActions(caseId)).draft))}>重新加载建议（放弃当前填写）</Button><Button disabled={busy} onClick={() => window.location.reload()}>重新载入整页（放弃未保存内容）</Button></Alert>}
    {loading ? <Typography>正在读取安排…</Typography> : <>
      {(!draft || ['failed', 'dismissed', 'generating'].includes(draft.state)) && <Button disabled={busy || dirty} onClick={openPreview}>预览脱敏文本并整理</Button>}
      {draft?.state === 'generating' && <Alert severity="info">正在整理，尚未创建安排。可刷新读取；超过两分钟未完成可重新预览后重试。<Button disabled={busy} onClick={() => void operate(async () => hydrate((await getPostVisitActions(caseId)).draft))}>刷新建议</Button></Alert>}
      {draft?.state === 'ready' && <Stack component="fieldset" disabled={busy || dirty} spacing={2} sx={{ m: 0, p: 0, border: 0, minWidth: 0 }}>
        <Alert severity="warning">有待你确认的建议。日期和时刻按北京时间（UTC+8），用药周期需对照医嘱；单次最多91天、500条提醒。复查提醒于当天09:00，已过时则在确认后提醒。</Alert>
        {(draft.follow_ups || []).map((t, i) => <Box key={t.id}>
          <FormControlLabel control={<Checkbox checked={values[t.id]?.selected || false} onChange={e => update(t.id, { selected: e.target.checked })} />} label={`随访 ${i + 1}：${t.description}`} />
          <Typography sx={{ whiteSpace: 'pre-wrap' }}>原文依据：{t.evidence}</Typography>
          <TextField label={`随访 ${i + 1} 日期`} type="date" value={values[t.id]?.date || ''} onChange={e => update(t.id, { date: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} />
        </Box>)}
        {(draft.medications || []).map((t, i) => <Box key={t.id}>
          <FormControlLabel control={<Checkbox disabled={!t.dosage} checked={values[t.id]?.selected || false} onChange={e => update(t.id, { selected: e.target.checked })} />} label={`用药 ${i + 1}：${t.name} · ${t.dosage || '剂量未记录，需先补充原记录'}`} />
          <Typography sx={{ whiteSpace: 'pre-wrap' }}>原文依据：{t.evidence}</Typography>
          <Stack spacing={1}>
            <TextField label={`用药 ${i + 1} 开始日期`} type="date" value={values[t.id]?.date || ''} onChange={e => update(t.id, { date: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} />
            <TextField label={`用药 ${i + 1} 结束日期`} type="date" value={values[t.id]?.end || ''} onChange={e => update(t.id, { end: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} />
            <TextField label={`用药 ${i + 1} 提醒时刻`} helperText="北京时间，如08:00, 20:00，每日最多6次" value={values[t.id]?.times || ''} onChange={e => update(t.id, { times: e.target.value })} />
          </Stack>
        </Box>)}
        {!draft.follow_ups?.length && !draft.medications?.length && <Alert severity="info">未识别到可核对的安排；请补充记录或手动登记随访计划。</Alert>}
        <TextField select label="提醒方式" value={channel} onChange={e => setChannel(e.target.value as 'in_app' | 'email')}>
          <MenuItem value="in_app">仅站内提醒</MenuItem><MenuItem value="email">站内＋邮件提示（不含病情与药名）</MenuItem>
        </TextField>
        <Button variant="contained" onClick={confirm} disabled={busy || dirty || !Object.values(values).some(t => t.selected)}>核对完毕，确认创建安排</Button>
        <Button onClick={() => setDismissOpen(true)}>放弃本次建议</Button>
      </Stack>}
      {draft?.state === 'confirmed' && <Stack spacing={1}>
        <Alert severity="success">安排已确认 · AI 提取、患者核对。已创建 {draft.reminder_count || 0} 条提醒。</Alert>
        {draft.plan_id && <Button component={RouterLink} to="/followups">查看随访计划</Button>}
        <Button component={RouterLink} to="/reminders">查看提醒</Button>
        <Button color="error" disabled={busy || dirty} onClick={() => setDismissOpen(true)}>停用本次安排</Button>
      </Stack>}
    </>}
    <Dialog open={!!preview} onClose={() => !busy && setPreview(null)} maxWidth="sm" fullWidth>
      <DialogTitle>确认发送脱敏就诊文本</DialogTitle><DialogContent>
        <Typography>接收模型：{preview?.recipient.provider} / {preview?.recipient.model}（{preview?.recipient.host}）</Typography>
        <Alert severity="warning" sx={{ my: 2 }}>只发送以下文字。自动脱敏可能遗漏自由文本身份信息；若仍含隐私，请取消并修改原记录。原始附件和健康档案不会发送。</Alert>
        <Box component="pre" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 13 }}>{preview?.text}</Box>
        <FormControlLabel control={<Checkbox checked={consent} disabled={busy} onChange={e => setConsent(e.target.checked)} />} label="我已检查此文本，同意本次发送给上述模型整理" />
        {error && <Alert severity="error">{error}</Alert>}
      </DialogContent><DialogActions><Button disabled={busy} onClick={() => setPreview(null)}>取消</Button>
        <Button disabled={busy || !consent || dirty} onClick={() => void operate(async () => {
          if (preview) hydrate((await generatePostVisitActions(caseId, preview)).draft);
          setPreview(null); setConsent(false);
        })}>{busy ? '整理中…' : '同意并整理'}</Button>
      </DialogActions>
    </Dialog>
    <Dialog open={dismissOpen} onClose={() => !busy && setDismissOpen(false)} maxWidth="xs" fullWidth>
      <DialogTitle>{draft?.state === 'confirmed' ? '停用本次安排' : '放弃本次建议'}</DialogTitle>
      <DialogContent>未发送提醒及进行中的关联计划会取消；历史记录保留，已开始发送的通知无法召回。{error && <Alert severity="error">{error}</Alert>}</DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => setDismissOpen(false)}>返回</Button><Button disabled={busy} onClick={() => void operate(async () => {
        if (draft) hydrate((await dismissPostVisitActions(caseId, draft.id)).draft); setDismissOpen(false);
      })}>确定停用或放弃</Button></DialogActions>
    </Dialog>
  </Box>;
}
