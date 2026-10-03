import { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert, Box, Button, Card, CardContent, Chip, Container, Dialog, DialogActions,
  Checkbox, DialogContent, DialogTitle, Divider, Grid, LinearProgress, MenuItem, Stack, Tab, Tabs, TextField, Typography,
} from '@mui/material';
import {
  changeCarePlan, checkInCareTask, createCarePlan, editCarePlan, listCarePlanPage, listCases,
} from '../../api/patient';
import type { CarePlan, CarePlanAction, CarePlanCursor, CarePlanFields, CareTask, MedicalCase } from '../../api/patient';
import { pageHeader } from '../../styles/sxUtils';
import { carePalette } from '../../theme';
import PendingPostVisitActions from '../components/PendingPostVisitActions';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import CalendarMonthOutlinedIcon from '@mui/icons-material/CalendarMonthOutlined';

const statusLabels: Record<string, string> = {
  pending_confirmation: '待确认', active: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消', expired: '已到期',
};
const actionLabels: Record<CarePlanAction, string> = { confirm: '确认执行', pause: '暂停计划', resume: '恢复计划', cancel: '取消计划' };
const dateToday = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date());
function tasksOf(plan: CarePlan): CareTask[] {
  return Array.isArray(plan.tasks) ? plan.tasks : Array.isArray(plan.tasks.tasks) ? plan.tasks.tasks : [];
}
const emptyFields = (): CarePlanFields => ({ title: '', description: '', source_case_id: null, start_date: dateToday(), end_date: dateToday(),
  tasks: [{ type: 'follow_up', description: '', due_date: dateToday(), unit: '' }] });
const messageOf = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试';
const formatTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '未记录';

export default function FollowUpPage() {
  const [plans, setPlans] = useState<CarePlan[]>([]);
  const [filter, setFilter] = useState('');
  const [cursor, setCursor] = useState<CarePlanCursor | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const requestVersion = useRef(0);
  const [busy, setBusy] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<CarePlan | null>(null);
  const [fields, setFields] = useState<CarePlanFields>(emptyFields);
  const [formError, setFormError] = useState('');
  const requestId = useRef('');
  const lastSubmitted = useRef('');
  const [cases, setCases] = useState<MedicalCase[]>([]);
  const [casePage, setCasePage] = useState(1);
  const [caseMore, setCaseMore] = useState(false);
  const [caseLoading, setCaseLoading] = useState(false);
  const [caseError, setCaseError] = useState('');
  const caseVersion = useRef(0);
  const [action, setAction] = useState<{ plan: CarePlan; name: CarePlanAction } | null>(null);
  const [execution, setExecution] = useState<{ plan: CarePlan; task: CareTask } | null>(null);
  const [value, setValue] = useState('');
  const [notes, setNotes] = useState('');
  const [dialogError, setDialogError] = useState('');
  const [symptoms, setSymptoms] = useState('');
  const [medication, setMedication] = useState('');
  const [summaryPlans, setSummaryPlans] = useState<CarePlan[]>([]);
  const [summaryMore, setSummaryMore] = useState(false);
  const [summaryError, setSummaryError] = useState('');
  const [summaryLoaded, setSummaryLoaded] = useState(false);
  const [summaryReload, setSummaryReload] = useState(0);

  useEffect(() => {
    let alive = true;
    listCarePlanPage({ status: 'active', limit: 50 }).then(data => {
      if (alive) { setSummaryPlans(data.items); setSummaryMore(Boolean(data.next_cursor)); setSummaryError(''); setSummaryLoaded(true); }
    }).catch(err => { if (alive) { setSummaryError(messageOf(err)); setSummaryLoaded(false); } });
    return () => { alive = false; };
  }, [reloadKey, summaryReload]);

  useEffect(() => {
    let alive = true;
    const version = ++requestVersion.current;
    listCarePlanPage({ status: filter || undefined }).then(data => {
      if (alive && version === requestVersion.current) { setPlans(data.items); setCursor(data.next_cursor); setLoaded(true); }
    }).catch(err => { if (alive) setError(messageOf(err)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [filter, reloadKey]);

  const resetList = () => { setLoading(true); setLoaded(false); setPlans([]); setCursor(null); setError(''); };
  const selectFilter = (next: string) => { if (next !== filter) { resetList(); setFilter(next); } };
  const reloadList = () => { resetList(); setReloadKey(k => k + 1); };

  const loadMore = async () => {
    if (!cursor) return;
    const version = requestVersion.current;
    setLoading(true); setError('');
    try {
      const data = await listCarePlanPage({ status: filter || undefined, cursor });
      if (version !== requestVersion.current) return;
      setPlans(previous => [...previous, ...data.items.filter(item => !previous.some(p => p.id === item.id))]);
      setCursor(data.next_cursor);
    } catch (err) { if (version === requestVersion.current) setError(messageOf(err)); }
    finally { if (version === requestVersion.current) setLoading(false); }
  };
  const loadCases = async (page: number, version: number) => {
    setCaseLoading(true); setCaseError('');
    try {
      const items = await listCases({ page, limit: 20 });
      if (version !== caseVersion.current) return;
      setCases(previous => page === 1 ? items : [...previous, ...items.filter(item => !previous.some(p => p.id === item.id))]);
      setCasePage(page); setCaseMore(items.length === 20);
    } catch { if (version === caseVersion.current) setCaseError('病历加载失败，可重试或暂不关联病历'); }
    finally { if (version === caseVersion.current) setCaseLoading(false); }
  };
  const openForm = (plan: CarePlan | null) => {
    setEditing(plan); setFormError(''); requestId.current = crypto.randomUUID(); lastSubmitted.current = '';
    setFields(plan ? { title: plan.title, description: plan.description || '', source_case_id: plan.source_case_id || null,
      start_date: plan.start_date || dateToday(), end_date: plan.end_date || dateToday(),
      tasks: tasksOf(plan).map(task => ({ id: task.id, type: task.type === 'self_check' ? 'self_check' : 'follow_up',
        description: task.description || task.name || '', due_date: task.due_date || dateToday(), unit: task.unit || '' })) } : emptyFields());
    setCases([]); setCaseMore(false); setCasePage(1); setFormOpen(true);
    void loadCases(1, ++caseVersion.current);
  };
  const saveForm = async () => {
    if (!fields.title.trim() || !fields.tasks.length || fields.tasks.some(t => !t.description.trim() || !t.due_date)) {
      setFormError('请填写计划名称和每项任务的内容、日期'); return;
    }
    if (!fields.start_date || !fields.end_date || fields.end_date < fields.start_date || fields.tasks.some(t => t.due_date < fields.start_date || t.due_date > fields.end_date)) {
      setFormError('任务日期必须在计划起止日期内，结束日期不能早于开始日期'); return;
    }
    const serialized = JSON.stringify(fields);
    if (lastSubmitted.current && serialized !== lastSubmitted.current) requestId.current = crypto.randomUUID();
    lastSubmitted.current = serialized;
    setBusy(true); setFormError('');
    try {
      if (editing) await editCarePlan(editing.id, fields, editing.revision);
      else await createCarePlan(fields, requestId.current);
      setFormOpen(false); setNotice('已保存为待确认计划，请核对后确认执行');
      selectFilter('pending_confirmation'); reloadList();
    } catch (err) { setFormError(`${messageOf(err)}；当前填写已保留。`); }
    finally { setBusy(false); }
  };
  const performAction = async () => {
    if (!action) return;
    setBusy(true); setDialogError('');
    try {
      await changeCarePlan(action.plan, action.name);
      setAction(null); setNotice('计划状态已更新'); reloadList();
    } catch (err) { setDialogError(messageOf(err)); }
    finally { setBusy(false); }
  };
  const openFeedback = (plan: CarePlan, task: CareTask) => {
    setExecution({ plan, task }); setValue(''); setNotes(''); setSymptoms(''); setMedication(''); setDialogError('');
  };
  const complete = async (target = execution, direct = false) => {
    if (!target?.task.id || busy) return;
    const numeric = !direct && value.trim() ? Number(value) : undefined;
    if (numeric !== undefined && !Number.isFinite(numeric)) { setDialogError('请输入有效数值'); return; }
    if (!direct && (!symptoms || !notes.trim())) { setDialogError('请选择症状变化并填写本次反馈'); return; }
    const feedback = direct ? '' : [`症状变化：${symptoms}`, medication && `用药情况：${medication}`, notes.trim()].filter(Boolean).join('\n');
    if (feedback.length > 1000) { setDialogError('反馈内容过长，请精简后保存'); return; }
    setBusy(true); setDialogError(''); if (direct) setError('');
    try {
      const result = await checkInCareTask(target.plan.id, target.task.id, feedback, numeric);
      setPlans(previous => previous.map(plan => plan.id === result.plan.id ? result.plan : plan)
        .filter(plan => !filter || (plan.effective_status || plan.status) === filter));
      setExecution(null); setNotice('任务已完成并记录为患者自报'); setSummaryReload(k => k + 1);
    } catch (err) { if (direct) setError(messageOf(err)); else setDialogError(`${messageOf(err)}；填写内容已保留。`); }
    finally { setBusy(false); }
  };
  const updateTask = (index: number, changes: Partial<CarePlanFields['tasks'][number]>) => {
    setFields(previous => ({ ...previous, tasks: previous.tasks.map((task, i) => i === index ? { ...task, ...changes } : task) }));
  };

  const today = dateToday();
  const activeTasks = summaryPlans.flatMap(plan => tasksOf(plan));
  const completedCount = activeTasks.filter(task => task.status === 'completed').length;
  const upcoming = summaryPlans.flatMap(plan => tasksOf(plan).filter(task => task.status !== 'completed' && task.due_date && task.due_date >= today).map(task => ({ plan, task })))
    .sort((a, b) => a.task.due_date!.localeCompare(b.task.due_date!));
  const nextFollowUp = upcoming.find(item => item.task.type === 'follow_up');
  const days = Array.from({ length: 7 }, (_, index) => { const day = new Date(`${today}T12:00:00+08:00`); day.setUTCDate(day.getUTCDate() + index); return day; });
  const checkboxIcon = <Box sx={{ width: 24, height: 24, border: '1px solid', borderColor: carePalette.line, borderRadius: '8px', bgcolor: '#fff' }} />;
  const checkedIcon = <Box sx={{ width: 24, height: 24, borderRadius: '8px', bgcolor: carePalette.primarySoft, color: carePalette.primary, display: 'grid', placeItems: 'center' }}><CheckRoundedIcon sx={{ fontSize: 18 }} /></Box>;
  return <Box sx={{ pb: 6 }}><Container maxWidth="lg">
    <Box sx={{ ...pageHeader, flexWrap: 'wrap', gap: 1 }}>
      <Box sx={{ flex: 1, minWidth: 200 }}><Typography component="h1" variant="h5" sx={{ fontWeight: 600 }}>随访计划</Typography></Box>
      <Button variant="contained" onClick={() => openForm(null)} disabled={busy}>新建随访计划</Button>
    </Box>
    <Grid container spacing={2} sx={{ mb: 3 }}>
      {[
        ['进行中的计划', summaryLoaded ? summaryPlans.length : '—'],
        ['任务已完成', summaryLoaded ? `${completedCount}/${activeTasks.length}` : '—'],
        ['下一次随访', summaryLoaded ? nextFollowUp?.task.due_date?.slice(5).replace('-', '.') || '暂无安排' : '—'],
      ].map(([label, count]) => <Grid key={label} size={{ xs: 12, sm: 4 }}><Card variant="outlined" sx={{ boxShadow: 'none', borderRadius: '20px' }}><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}><Typography variant="body2" color="text.secondary">{label}</Typography><Typography sx={{ fontSize: 30, fontWeight: 600, my: 1 }}>{count}</Typography><Typography variant="caption">{summaryMore ? '已加载的进行中计划' : label === '任务已完成' ? '进行中计划 · 本人记录' : label === '下一次随访' ? '按计划任务日期' : '已确认的计划'}</Typography></CardContent></Card></Grid>)}
    </Grid>
    {summaryError && <Alert severity="warning" action={<Button onClick={() => setSummaryReload(v => v + 1)}>重试概览</Button>} sx={{ mb: 2 }}>概览暂未加载：{summaryError}</Alert>}
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ justifyContent: 'space-between', mb: 3 }}>
      <Tabs value={['', 'active', 'completed'].includes(filter) ? filter : false} onChange={(_, next) => selectFilter(next)} aria-label="随访计划筛选" sx={{ minHeight: 44 }}><Tab value="active" label="进行中" disabled={loading || busy} /><Tab value="completed" label="已完成" disabled={loading || busy} /><Tab value="" label="全部计划" disabled={loading || busy} /></Tabs>
      <TextField select size="small" label="其他状态" value={['pending_confirmation', 'paused', 'cancelled', 'expired'].includes(filter) ? filter : ''} onChange={e => selectFilter(e.target.value)} disabled={loading || busy} sx={{ minWidth: 150, alignSelf: 'flex-start' }}><MenuItem value="">更多状态</MenuItem>{['pending_confirmation', 'paused', 'cancelled', 'expired'].map(key => <MenuItem key={key} value={key}>{statusLabels[key]}</MenuItem>)}</TextField>
    </Stack>
    <PendingPostVisitActions />
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}
    {error && <Alert severity="error" sx={{ mb: 2 }} action={<Button color="inherit" onClick={() => cursor && loaded ? void loadMore() : reloadList()}>重试</Button>}>{error}</Alert>}
    {loaded && plans.length === 0 && <Card sx={{ textAlign: 'center', py: 4 }}><CardContent><Typography sx={{ fontWeight: 600, mb: 2 }}>暂无{filter ? statusLabels[filter] : ''}随访计划</Typography>
      <Button onClick={() => openForm(null)} disabled={busy}>添加复查或自测事项</Button></CardContent></Card>}
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0,1fr)', lg: 'minmax(0,1.7fr) minmax(300px,1fr)' }, gap: 3, alignItems: 'start' }}><Box sx={{ minWidth: 0 }}><Stack spacing={3}>{plans.map(plan => {
      const status = plan.effective_status || plan.status || 'active';
      return <Card key={plan.id} sx={{ borderRadius: '24px' }}><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}>
        <Stack direction="row" sx={{ justifyContent: 'space-between' }} spacing={1}><Typography variant="h6" sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>{plan.title}</Typography>
          <Chip size="small" label={statusLabels[status] || '状态待核对'} sx={{ bgcolor: ['active', 'completed'].includes(status) ? carePalette.mint : carePalette.page, color: ['active', 'completed'].includes(status) ? carePalette.primary : carePalette.muted }} /></Stack>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>{plan.source_type === 'patient_reported' ? '患者录入' : plan.source_type === 'ai_extracted_patient_confirmed' ? 'AI 提取、患者确认' : '历史计划，来源未核验'}{plan.confirmed_at && ` · 确认时间：${formatTime(plan.confirmed_at)}`}</Typography>
        {plan.source_case_id && <Typography variant="body2"><Button component={RouterLink} to={`/cases?case_id=${encodeURIComponent(plan.source_case_id)}`} size="small">关联病历：{plan.source_case_title || '查看病历'}</Button></Typography>}
        {plan.description && <Typography variant="body2" sx={{ my: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{plan.description}</Typography>}
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>{plan.start_date || '开始日期未记录'} 至 {plan.end_date || '结束日期未记录'}{plan.updated_at && ` · 更新时间：${formatTime(plan.updated_at)}`}</Typography>
        <LinearProgress aria-label={`${plan.title}进度`} variant="determinate" value={plan.progress_percent || 0} sx={{ mt: 1, height: 8, borderRadius: 4, bgcolor: carePalette.line }} />
        <Stack direction="row" sx={{ justifyContent: 'space-between', mt: 1 }}><Typography variant="caption">已完成 {tasksOf(plan).filter(task => task.status === 'completed').length} / {tasksOf(plan).length} 项</Typography><Typography variant="caption">进度 {plan.progress_percent || 0}%</Typography></Stack><Divider sx={{ mt: 2 }} />
        <Stack>{tasksOf(plan).map(task => <Box key={task.id} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', py: 2, borderBottom: '1px solid', borderColor: 'divider', minWidth: 0 }}>
          <Checkbox checked={task.status === 'completed'} disabled={busy || task.status === 'completed' || !plan.can_execute || !task.id} icon={checkboxIcon} checkedIcon={checkedIcon} slotProps={{ input: { 'aria-label': `${task.status === 'completed' ? '已完成' : '标记完成'}：${task.description || task.name || '历史任务'}` } }} onChange={() => task.type === 'self_check' ? openFeedback(plan, task) : void complete({ plan, task }, true)} sx={{ p: 1.25, mt: -.75, ml: -1, '&.Mui-disabled': { opacity: task.status === 'completed' ? 1 : .5 } }} />
          <Box sx={{ flex: 1, minWidth: 0 }}><Typography sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{task.description || task.name || '历史任务'}</Typography><Typography variant="caption">{task.due_date || '日期未记录'} · {task.type === 'self_check' ? '自测' : task.type === 'medication' ? '历史用药任务' : '复查'}</Typography>
            {task.status === 'completed' && <Typography variant="body2" sx={{ mt: .5, color: carePalette.muted, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{[task.last_value != null ? `数值：${task.last_value} ${task.unit || ''}` : '', task.completion_notes || '', task.completed_at ? `${formatTime(task.completed_at)} · 本人记录` : ''].filter(Boolean).join('\n')}</Typography>}
            {task.is_overdue && task.status !== 'completed' && <Typography variant="caption" sx={{ display: 'block', color: carePalette.amber }}>逾期未完成</Typography>}
          </Box>
          {task.status === 'completed' ? <Chip size="small" label="已完成（患者自报）" sx={{ bgcolor: carePalette.mint, color: carePalette.primary, display: { xs: 'none', sm: 'inline-flex' } }} /> : <Button size="small" disabled={busy || !plan.can_execute || !task.id} onClick={() => openFeedback(plan, task)} sx={{ flexShrink: 0, minHeight: 44, px: .5 }}>填写反馈</Button>}
        </Box>)}</Stack>
        {status === 'active' && !plan.can_execute && <Typography variant="caption" color="text.secondary">计划尚未到开始日期</Typography>}
        <Stack direction="row" sx={{ mt: 2, flexWrap: 'wrap', gap: 1 }}>
          {status === 'pending_confirmation' && <Button onClick={() => openForm(plan)} disabled={busy}>编辑计划</Button>}
          {(status === 'pending_confirmation' ? ['confirm', 'cancel'] : status === 'active' ? ['pause', 'cancel'] : status === 'paused' ? ['resume', 'cancel'] : status === 'expired' ? ['cancel'] : []).map(name =>
            <Button key={name} variant={name === 'confirm' ? 'contained' : 'outlined'} disabled={busy} onClick={() => { setAction({ plan, name: name as CarePlanAction }); setDialogError(''); }}>{actionLabels[name as CarePlanAction]}</Button>)}
        </Stack>
      </CardContent></Card>;
    })}</Stack>
    {loading && <LinearProgress sx={{ mt: 2 }} />}
    {cursor && <Button fullWidth onClick={() => void loadMore()} disabled={loading || busy} sx={{ mt: 2 }}>加载更多计划</Button>}
    </Box><Stack component="aside" spacing={3} sx={{ minWidth: 0 }}>
      <Card sx={{ borderRadius: '24px' }}><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}><Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}><Typography component="h2" variant="h6">{Number(today.slice(5, 7))} 月照护日历</Typography><CalendarMonthOutlinedIcon color="primary" /></Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(7,minmax(0,1fr))', gap: .5, my: 2.5 }}>{days.map((day, index) => { const date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(day); return <Box key={date} sx={{ py: 1.25, textAlign: 'center', borderRadius: '12px', bgcolor: index === 0 ? carePalette.primary : 'transparent', color: index === 0 ? '#fff' : carePalette.muted }}><Typography sx={{ fontSize: 11 }}>{day.toLocaleDateString('zh-CN', { weekday: 'narrow', timeZone: 'Asia/Shanghai' })}</Typography><Typography sx={{ fontSize: 18, fontWeight: 600, my: .5 }}>{Number(date.slice(8))}</Typography><Typography sx={{ fontSize: 10 }}>{index === 0 ? '今天' : upcoming.some(item => item.task.due_date === date) ? '任务' : '·'}</Typography></Box>; })}</Box>
        {!upcoming.length && <Typography variant="body2" color="text.secondary">{summaryError ? '安排暂未加载' : summaryLoaded ? '暂无待办安排' : '安排加载中…'}</Typography>}
        {upcoming.slice(0, 3).map(({ plan, task }) => <Box key={`${plan.id}-${task.id}`} sx={{ borderLeft: '3px solid', borderColor: carePalette.coral, pl: 1.5, my: 2 }}><Typography sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{task.due_date?.slice(5).replace('-', '.')} · {task.description || task.name}</Typography><Typography variant="caption">{plan.title}</Typography></Box>)}
      </CardContent></Card>
      <Card sx={{ borderRadius: '24px' }}><CardContent sx={{ p: 3, '&:last-child': { pb: 3 } }}><Typography component="h2" variant="h6" sx={{ mb: 2 }}>就诊前准备</Typography>{[['核对健康档案', '过敏史、疾病与当前用药', '/health'], ['整理检查报告', '携带原件供医生核对', '/cases']].map(([title, detail, link]) => <Stack direction="row" key={title} sx={{ py: 1.5, alignItems: 'center', justifyContent: 'space-between', gap: 1 }}><Box><Typography sx={{ fontWeight: 600 }}>{title}</Typography><Typography variant="caption">{detail}</Typography></Box><Button component={RouterLink} to={link} aria-label={title}>查看 →</Button></Stack>)}</CardContent></Card>
      <Alert severity="warning" icon={false}>症状明显加重或出现紧急危险信号时，请及时就医。</Alert>
    </Stack></Box>

    <Dialog open={formOpen} onClose={() => !busy && setFormOpen(false)} maxWidth="sm" fullWidth>
      <DialogTitle>{editing ? '编辑待确认计划' : '新建随访计划'}</DialogTitle>
      <DialogContent><Stack component="fieldset" disabled={busy} spacing={2} sx={{ border: 0, p: 0, m: 0, pt: 1, minWidth: 0 }}>
        <Typography variant="body2" color="text.secondary">每项任务记录一次复查或自测。内容由患者录入，执行记录为患者自报。</Typography>
        {formError && <Alert severity="error">{formError}{editing && <Button onClick={() => { setFormOpen(false); reloadList(); }}>放弃当前填写并重新加载</Button>}</Alert>}
        <TextField label="计划名称" value={fields.title} onChange={e => setFields({ ...fields, title: e.target.value })} slotProps={{ htmlInput: { maxLength: 255 } }} required />
        <TextField label="计划说明" multiline minRows={2} value={fields.description} onChange={e => setFields({ ...fields, description: e.target.value })} slotProps={{ htmlInput: { maxLength: 2000 } }} />
        <TextField select label="关联病历（可选）" value={fields.source_case_id || ''} onChange={e => setFields({ ...fields, source_case_id: e.target.value || null })}>
          <MenuItem value="">暂不关联</MenuItem>
          {fields.source_case_id && !cases.some(item => item.id === fields.source_case_id) && <MenuItem value={fields.source_case_id}>{editing?.source_case_title || '已关联病历'}</MenuItem>}
          {cases.map(item => <MenuItem key={item.id} value={item.id}>{item.title}</MenuItem>)}
        </TextField>
        {caseError && <Alert severity="warning" action={<Button onClick={() => void loadCases(casePage, caseVersion.current)}>重试</Button>}>{caseError}</Alert>}
        {caseLoading && <Typography variant="caption">病历加载中…</Typography>}
        {caseMore && <Button disabled={caseLoading} onClick={() => void loadCases(casePage + 1, caseVersion.current)}>加载更多病历</Button>}
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField fullWidth label="开始日期" type="date" value={fields.start_date} onChange={e => setFields({ ...fields, start_date: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} required />
          <TextField fullWidth label="结束日期" type="date" value={fields.end_date} onChange={e => setFields({ ...fields, end_date: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} required />
        </Stack>
        {fields.tasks.map((task, index) => <Card variant="outlined" key={index}><CardContent><Stack spacing={2}>
          <Typography variant="subtitle2">任务 {index + 1}</Typography>
          <TextField select label={`任务 ${index + 1} 类型`} value={task.type} onChange={e => updateTask(index, { type: e.target.value as 'follow_up' | 'self_check' })}>
            <MenuItem value="follow_up">复查</MenuItem><MenuItem value="self_check">自测</MenuItem></TextField>
          <TextField label={`任务 ${index + 1} 内容`} value={task.description} onChange={e => updateTask(index, { description: e.target.value })} slotProps={{ htmlInput: { maxLength: 500 } }} required />
          <TextField label={`任务 ${index + 1} 日期`} type="date" value={task.due_date} onChange={e => updateTask(index, { due_date: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} required />
          {task.type === 'self_check' && <TextField label={`任务 ${index + 1} 数值单位（可选）`} value={task.unit} onChange={e => updateTask(index, { unit: e.target.value })} slotProps={{ htmlInput: { maxLength: 30 } }} />}
          <Button color="error" disabled={fields.tasks.length === 1} onClick={() => setFields({ ...fields, tasks: fields.tasks.filter((_, i) => i !== index) })}>删除任务 {index + 1}</Button>
        </Stack></CardContent></Card>)}
        <Button disabled={fields.tasks.length >= 20} onClick={() => setFields({ ...fields, tasks: [...fields.tasks, { type: 'follow_up', description: '', due_date: fields.start_date, unit: '' }] })}>添加任务</Button>
      </Stack></DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => setFormOpen(false)}>关闭</Button><Button variant="contained" disabled={busy} onClick={() => void saveForm()}>保存待确认计划</Button></DialogActions>
    </Dialog>
    <Dialog open={!!action} onClose={() => !busy && setAction(null)} maxWidth="xs" fullWidth>
      <DialogTitle>{action ? actionLabels[action.name] : ''}</DialogTitle><DialogContent>
        <Typography sx={{ overflowWrap: 'anywhere', mb: 1 }}>{action?.plan.title}</Typography>
        <Typography variant="body2">{action?.name === 'confirm' ? '请核对任务内容与日期。确认代表你准备执行该计划，来源仍为患者录入。' : action?.name === 'cancel' ? '取消后无法继续执行；需要修改时可重新创建。尚未发送的关联提醒将取消，已开始发送的提醒无法召回。' : action?.name === 'pause' ? '暂停后停止执行，尚未发送的关联提醒暂停。已开始发送的提醒无法召回。' : '恢复后可继续执行；暂停期间错过的提醒不集中补发。'}</Typography>
        {dialogError && <Alert severity="error" sx={{ mt: 2 }}>{dialogError}<Button onClick={() => { setAction(null); reloadList(); }}>重新加载计划</Button></Alert>}
      </DialogContent><DialogActions><Button disabled={busy} onClick={() => setAction(null)}>返回</Button><Button variant="contained" disabled={busy} onClick={() => void performAction()}>确定</Button></DialogActions>
    </Dialog>
    <Dialog open={!!execution} onClose={() => !busy && setExecution(null)} maxWidth="sm" fullWidth aria-labelledby="feedback-title">
      <DialogTitle id="feedback-title">{execution?.task.description || execution?.task.name || '填写随访反馈'}</DialogTitle><DialogContent dividers><Stack spacing={2.5} sx={{ pt: 1 }}>
        <TextField select label="症状变化" value={symptoms} onChange={e => setSymptoms(e.target.value)} disabled={busy} required>{['基本稳定', '有所缓解', '有所加重', '不适用或不确定'].map(label => <MenuItem key={label} value={label}>{label}</MenuItem>)}</TextField>
        {execution?.task.type === 'self_check' && <TextField label={`自测数值${execution.task.unit ? `（${execution.task.unit}）` : '（可选）'}`} type="number" value={value} onChange={e => setValue(e.target.value)} disabled={busy} />}
        <TextField select label="用药情况（可选）" value={medication} onChange={e => setMedication(e.target.value)} disabled={busy}><MenuItem value="">暂不填写</MenuItem>{['按原处方用药', '有漏服或不适，待咨询医生', '暂无用药', '不确定'].map(label => <MenuItem key={label} value={label}>{label}</MenuItem>)}</TextField>
        <TextField label="本次反馈与想问医生的问题" multiline minRows={3} value={notes} onChange={e => setNotes(e.target.value)} slotProps={{ htmlInput: { maxLength: 800 } }} disabled={busy} required />
        <Typography variant="caption">保存为本人随访记录，不会自动发送给医生。</Typography>
        {dialogError && <Alert severity="error">{dialogError}<Button onClick={() => { setExecution(null); reloadList(); }}>放弃当前填写并重新加载</Button></Alert>}
      </Stack></DialogContent><DialogActions sx={{ p: 2.5 }}><Button disabled={busy} onClick={() => setExecution(null)}>取消</Button><Button variant="contained" disabled={busy} onClick={() => void complete()}>保存并完成任务</Button></DialogActions>
    </Dialog>
  </Container></Box>;
}
