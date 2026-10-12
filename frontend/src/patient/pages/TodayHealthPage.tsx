import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Button, Card, Chip, LinearProgress, Skeleton, Stack, Typography } from '@mui/material';
import { ArrowForwardRounded, CalendarMonthOutlined, CheckRounded, ChatBubbleOutlineRounded, DescriptionOutlined, HealingOutlined, MedicationOutlined, MonitorWeightOutlined, StraightenRounded } from '@mui/icons-material';
import { getProfile, listCarePlanPage, listCases, listReminders } from '../../api/patient';
import type { CarePlanPage, MedicalCase, PatientProfile, PatientReminderPage } from '../../api/patient';
import { CARE_TIMEZONE, careDate, careOverview } from '../../state/todayHealth';
import { patientText } from '../../state/patientText';
import { carePalette, careShadows } from '../../theme';

interface OverviewData {
  profile: PatientProfile | null;
  plans: CarePlanPage | null;
  reminders: PatientReminderPage | null;
  cases: MedicalCase[] | null;
  errors: string[];
}
const panel = { p: { xs: 3, lg: 3.5 }, minWidth: 0 };
const heading = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 2 };

export default function TodayHealthPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [reload, setReload] = useState(0);
  const [showAllToday, setShowAllToday] = useState(false);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const update = () => setNow(new Date());
    const timer = window.setInterval(update, 60_000);
    window.addEventListener('focus', update);
    return () => { clearInterval(timer); window.removeEventListener('focus', update); };
  }, []);
  useEffect(() => {
    let current = true;
    Promise.allSettled([getProfile(), listCarePlanPage({ limit: 50 }), listReminders({ limit: 50 }), listCases({ limit: 3 })])
      .then(([profile, plans, reminders, cases]) => {
        if (!current) return;
        setData({
          profile: profile.status === 'fulfilled' ? profile.value : null,
          plans: plans.status === 'fulfilled' ? plans.value : null,
          reminders: reminders.status === 'fulfilled' ? reminders.value : null,
          cases: cases.status === 'fulfilled' ? cases.value : null,
          errors: [profile.status === 'rejected' && '健康档案', plans.status === 'rejected' && '随访计划', reminders.status === 'rejected' && '用药提醒', cases.status === 'rejected' && '问诊记录'].filter((value): value is string => Boolean(value)),
        });
      });
    return () => { current = false; };
  }, [reload]);
  const today = careDate(now);
  const dateLabel = now.toLocaleDateString('zh-CN', { timeZone: CARE_TIMEZONE, month: 'long', day: 'numeric', weekday: 'long' });
  const hour = Number(now.toLocaleTimeString('en-GB', { timeZone: CARE_TIMEZONE, hour: '2-digit', hour12: false }));
  const greeting = hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好';
  const items = careOverview(data?.plans?.items || [], data?.reminders?.items || [], today);
  const todayItems = items.filter(item => item.date === today);
  const completed = todayItems.filter(item => item.done).length;
  const upcoming = items.filter(item => !item.done).slice(0, 4);
  const partial = Boolean(data?.plans?.next_cursor || data?.reminders?.next_cursor);
  const careLoaded = Boolean(data?.plans && data?.reminders);
  const activePlans = data?.plans?.items.filter(plan => (plan.effective_status || plan.status) === 'active').length;
  const medicationState = data?.profile?.section_states?.medications ?? (data?.profile?.medications?.length ? 'present' : 'not_recorded');
  const medicationCount = data?.profile && ['present', 'none'].includes(medicationState)
    ? (data.profile.medications || []).filter(item => item.status !== 'stopped').length : '—';
  const metrics = [
    { label: '体重', value: data?.profile ? data.profile.weight ?? '—' : '—', unit: 'kg', icon: <MonitorWeightOutlined />, color: carePalette.amber, bg: carePalette.amberSoft, path: '/health' },
    { label: '身高', value: data?.profile ? data.profile.height ?? '—' : '—', unit: 'cm', icon: <StraightenRounded />, color: '#6366f1', bg: '#eef2ff', path: '/health' },
    { label: '当前用药', value: medicationCount, unit: '项', icon: <MedicationOutlined />, color: carePalette.primary, bg: carePalette.mint, path: '/health' },
    { label: '进行中的计划', value: activePlans == null ? '—' : `${activePlans}${data?.plans?.next_cursor ? '+' : ''}`, unit: '份', icon: <CalendarMonthOutlined />, color: carePalette.danger, bg: carePalette.dangerSoft, path: '/followups' },
  ];
  return <Box sx={{ maxWidth: 1440, mx: 'auto', p: { xs: 2, sm: 3, lg: 4 } }}>
    <Box sx={{ ...heading, mb: 3 }}>
      <Typography component="h1" variant="h5">今日健康</Typography>
      <Button size="small" onClick={() => { setData(null); setReload(value => value + 1); }} disabled={!data}>刷新</Button>
    </Box>
    {data?.errors.length ? <Alert severity="warning" sx={{ mb: 3 }} action={<Button color="inherit" onClick={() => { setData(null); setReload(value => value + 1); }}>重试</Button>}>{data.errors.join('、')}暂时无法加载</Alert> : null}
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1.8fr) minmax(0, 1fr)' }, gap: 2.5 }}>
      <Card component="section" sx={{ ...panel, p: { xs: 3, sm: 4 }, borderRadius: '32px', background: 'linear-gradient(125deg, #fff 15%, #f0fdfa 100%)' }}>
        <Box sx={{ ...heading, alignItems: 'flex-start', flexWrap: 'wrap', mb: 3 }}>
          <Typography sx={{ fontSize: { xs: 26, sm: 32 }, fontWeight: 600, letterSpacing: '-.03em', overflowWrap: 'anywhere' }}>{greeting}{data?.profile?.name ? `，${data.profile.name}` : ''}</Typography>
          <Typography component="time" dateTime={today} variant="body2" color="text.secondary" sx={{ pt: 0.75 }}>{dateLabel}</Typography>
        </Box>
        <Typography component="h2" sx={{ fontSize: { xs: 20, sm: 24 }, fontWeight: 600, mb: 1 }}>今天感觉怎么样？</Typography>
        <Typography color="text.secondary">从一次交流开始，照顾好今天的自己。</Typography>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mt: 3.5 }}>
          <Button component={RouterLink} to="/chat" variant="contained" endIcon={<ArrowForwardRounded />} sx={{ px: 3, boxShadow: careShadows.brand }}>开始 AI 问诊</Button>
          <Button component={RouterLink} to="/cases" startIcon={<DescriptionOutlined />} sx={{ bgcolor: '#fff', color: carePalette.ink, px: 2.5 }}>查看问诊记录</Button>
        </Stack>
      </Card>
      <Card component="section" aria-label="今日照护" sx={panel}>
        <Box sx={heading}><Typography component="h2" variant="h6">今日照护</Typography>{partial && <Chip label="部分记录" size="small" />}</Box>
        {!data ? <><Skeleton width="75%" /><Skeleton height={60} /><Skeleton width="85%" /></> : <>
          {todayItems.length > 0 && <>
            <Box sx={{ ...heading, mb: 1 }}><Typography variant="body2" color="text.secondary">已记录 {completed} / {todayItems.length} 项</Typography>
              {careLoaded && !partial && <Typography sx={{ color: carePalette.primaryDark, fontWeight: 600 }}>{Math.round(completed / todayItems.length * 100)}%</Typography>}</Box>
            <LinearProgress aria-label="今日照护完成进度" variant="determinate" value={completed / todayItems.length * 100} sx={{ height: 6, borderRadius: 3, bgcolor: '#f1f5f9', mb: 2 }} />
          </>}
          <Stack spacing={1}>{(showAllToday ? todayItems : todayItems.slice(0, 4)).map(item => <Button key={item.id} component={RouterLink} to={item.path} sx={{ justifyContent: 'flex-start', gap: 1.25, px: 0.5, color: item.done ? carePalette.muted : carePalette.ink, textAlign: 'left' }}>
            <Box sx={{ width: 24, height: 24, flexShrink: 0, borderRadius: '8px', display: 'grid', placeItems: 'center', bgcolor: item.done ? carePalette.mint : '#f1f5f9', color: carePalette.primaryDark }}>{item.done ? <CheckRounded sx={{ fontSize: 16 }} /> : <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: item.failed ? carePalette.danger : carePalette.primary }} />}</Box>
            <Typography variant="body2" sx={{ overflowWrap: 'anywhere', textDecoration: item.done ? 'line-through' : 'none' }}>{item.time && `${item.time} · `}{patientText(item.title)}</Typography>
          </Button>)}</Stack>
          {todayItems.length > 4 && <Button size="small" onClick={() => setShowAllToday(value => !value)}>{showAllToday ? '收起当天安排' : `查看其余 ${todayItems.length - 4} 项`}</Button>}
          {!todayItems.length && <Box sx={{ py: 2.5 }}><CalendarMonthOutlined sx={{ fontSize: 32, color: '#94a3b8', mb: 1 }} /><Typography color="text.secondary">{!careLoaded ? '照护安排暂时无法加载' : partial ? '查看完整照护安排' : '今天暂无照护安排'}</Typography></Box>}
          <Button component={RouterLink} to="/followups" size="small" endIcon={<ArrowForwardRounded />} sx={{ mt: 1 }}>查看随访计划</Button>
          <Button component={RouterLink} to="/reminders" size="small" sx={{ mt: 1 }}>用药提醒</Button>
        </>}
      </Card>
    </Box>
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', lg: 'repeat(4, minmax(0, 1fr))' }, gap: { xs: 1.5, sm: 2 }, my: 2.5 }}>
      {metrics.map(metric => <Card key={metric.label} component={RouterLink} to={metric.path} sx={{ textDecoration: 'none', p: { xs: 2.5, sm: 3 }, display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1.5, transition: 'transform 200ms ease, box-shadow 200ms ease', '&:hover': { transform: 'translateY(-3px)', boxShadow: careShadows.paper } }}>
        <Box sx={{ width: 44, height: 44, borderRadius: '16px', bgcolor: metric.bg, color: metric.color, display: 'grid', placeItems: 'center' }}>{metric.icon}</Box>
        <Box><Typography variant="caption">{metric.label}</Typography>{!data ? <Skeleton width={60} /> : <Typography sx={{ fontSize: 24, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{metric.value} <Box component="span" sx={{ fontSize: 12, color: carePalette.muted, fontWeight: 400 }}>{metric.unit}</Box></Typography>}</Box>
      </Card>)}
    </Box>
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1.2fr) minmax(0, 1fr)' }, gap: 2.5 }}>
      <Card component="section" sx={panel}>
        <Box sx={heading}><Typography component="h2" variant="h6">近期问诊</Typography><Button component={RouterLink} to="/cases" size="small">查看全部 →</Button></Box>
        {!data ? <Skeleton height={150} /> : data.cases === null ? <Typography color="text.secondary">问诊记录暂时无法加载</Typography> : data.cases.length ? data.cases.map(item => <Box key={item.id} sx={{ display: 'flex', gap: 2, alignItems: 'center', py: 2, '& + &': { borderTop: '1px solid #f1f5f9' } }}>
          <Box sx={{ width: 42, height: 42, flexShrink: 0, bgcolor: carePalette.mint, color: carePalette.primary, borderRadius: '14px', display: 'grid', placeItems: 'center' }}><ChatBubbleOutlineRounded sx={{ fontSize: 20 }} /></Box>
          <Box sx={{ flex: 1, minWidth: 0 }}><Typography sx={{ fontWeight: 500, overflowWrap: 'anywhere' }}>{patientText(item.chief_complaint || item.title.replace(/^AI Diagnosis:\s*/i, '')) || '问诊记录'}</Typography><Typography variant="caption">{item.created_at && careDate(item.created_at) ? new Date(item.created_at).toLocaleDateString('zh-CN', { timeZone: CARE_TIMEZONE, month: 'long', day: 'numeric' }) : '日期未记录'}</Typography></Box>
          <Button component={RouterLink} to={`/cases?case_id=${encodeURIComponent(item.id)}`} size="small" aria-label={`查看问诊：${patientText(item.chief_complaint || item.title)}`}>查看</Button>
        </Box>) : <Box sx={{ py: 3 }}><Typography color="text.secondary" sx={{ mb: 1.5 }}>还没有问诊记录</Typography><Button component={RouterLink} to="/chat" startIcon={<ChatBubbleOutlineRounded />}>开始第一次问诊</Button></Box>}
      </Card>
      <Card component="section" sx={panel}>
        <Box sx={heading}><Typography component="h2" variant="h6">接下来的照护</Typography><CalendarMonthOutlined sx={{ color: carePalette.primary }} /></Box>
        {!data ? <Skeleton height={150} /> : upcoming.length ? upcoming.map(item => <Box key={item.id} sx={{ display: 'flex', gap: 1.5, py: 1.75, alignItems: 'flex-start', '& + &': { borderTop: '1px solid #f1f5f9' } }}>
          <Box sx={{ mt: 0.9, width: 8, height: 8, borderRadius: '50%', flexShrink: 0, bgcolor: item.failed ? carePalette.danger : carePalette.primary }} />
          <Box sx={{ flex: 1, minWidth: 0 }}><Typography variant="caption">{item.date === today ? '今天' : item.date.slice(5).replace('-', '月') + '日'}{item.time && ` ${item.time}`}</Typography><Typography sx={{ fontWeight: 500, overflowWrap: 'anywhere' }}>{patientText(item.title)}</Typography><Typography variant="caption" sx={{ overflowWrap: 'anywhere' }}>{patientText(item.detail)}</Typography></Box>
          <Button component={RouterLink} to={item.path} size="small">查看</Button>
        </Box>) : <Typography color="text.secondary" sx={{ py: 3 }}>{!careLoaded ? '照护安排暂时无法加载' : partial ? '查看完整照护安排' : '暂无后续安排'}</Typography>}
        {partial && <Button component={RouterLink} to="/followups" size="small">查看更多安排 →</Button>}
        <Box sx={{ mt: 2, p: 2, borderRadius: '16px', bgcolor: carePalette.page, display: 'flex', alignItems: 'center', gap: 1.5 }}><HealingOutlined sx={{ color: carePalette.primary }} /><Typography variant="body2" sx={{ flex: 1 }}>我的健康档案</Typography><Button component={RouterLink} to="/health" size="small">查看</Button></Box>
      </Card>
    </Box>
  </Box>;
}
