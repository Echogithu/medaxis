import { useState, useEffect, useMemo } from 'react';
import {
  Alert, Container, Box, Typography, Card, CardContent, Tabs, Tab,
  Checkbox, Chip, Divider, Stack, LinearProgress,
} from '@mui/material';
import { listCarePlans, ackTask } from '../../api/patient';
import type { CarePlan, CareTask } from '../../api/patient';
import { pageHeader } from '../../styles/sxUtils';
import { carePalette } from '../../theme';

const warmText = carePalette.ink;
const warmPrimary = carePalette.primary;

/* ---------- 工具函数 ---------- */
function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function isExpired(plan: CarePlan): boolean {
  if (!plan.end_date) return false;
  return plan.end_date < todayStr();
}

function isAllCompleted(plan: CarePlan): boolean {
  const tasks = getTasks(plan);
  return tasks.length > 0 && tasks.every(isTaskCompleted);
}

function getPlanStatus(plan: CarePlan): '进行中' | '已完成' | '已过期' {
  if (plan.status === 'completed' || isAllCompleted(plan)) return '已完成';
  if (isExpired(plan)) return '已过期';
  return '进行中';
}

function completionRate(plan: CarePlan): number {
  const tasks = getTasks(plan);
  if (!tasks.length) return 0;
  return Math.round((tasks.filter(isTaskCompleted).length / tasks.length) * 100);
}

function getTasks(plan: CarePlan): CareTask[] {
  if (Array.isArray(plan.tasks)) return plan.tasks;
  return 'tasks' in plan.tasks && Array.isArray(plan.tasks.tasks) ? plan.tasks.tasks : [];
}

function isTaskCompleted(task: CareTask): boolean {
  return task.completed === true || task.status === 'completed';
}

/* ---------- 组件 ---------- */
export default function FollowUpPage() {
  const [plans, setPlans] = useState<CarePlan[]>([]);
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [ackingTask, setAckingTask] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    listCarePlans()
      .then((data) => {
        if (mounted) {
          setPlans(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) {
          setError('随访计划加载失败，请稍后重试');
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleAck = async (planId: string, taskId: string) => {
    setAckingTask(`${planId}:${taskId}`);
    setError('');
    try {
      await ackTask(planId, taskId);
      setPlans(await listCarePlans());
    } catch {
      setError('任务更新失败，请重试');
    } finally {
      setAckingTask(null);
    }
  };

  const { active, completed } = useMemo(() => ({
    active: plans.filter((plan) => getPlanStatus(plan) === '进行中'),
    completed: plans.filter((plan) => getPlanStatus(plan) === '已完成'),
  }), [plans]);

  const tabs = [
    { label: `进行中 (${active.length})` },
    { label: `已完成 (${completed.length})` },
    { label: `全部 (${plans.length})` },
  ];

  const filtered = tab === 0 ? active : tab === 1 ? completed : plans;

  return (
    <Box sx={{ pb: 6 }}>
      <Container maxWidth="md">
        <Box sx={pageHeader}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="h5" sx={{ fontWeight: 700, color: warmText }}>随访计划</Typography>
            <Typography variant="body2" sx={{ color: carePalette.muted, mt: 0.4 }}>勾选已完成的任务，方便按节奏复查和护理。</Typography>
          </Box>
        </Box>

        <Tabs value={tab} onChange={(_, value: number) => setTab(value)} sx={{ mb: 2 }}
          slotProps={{ indicator: { sx: { bgcolor: warmPrimary } } }}>
          {tabs.map((item, index) => <Tab key={item.label} label={item.label} value={index} />)}
        </Tabs>

        {loading && <Typography sx={{ textAlign: 'center', py: 4 }}>加载中...</Typography>}
        {!!error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {!loading && filtered.length === 0 && (
          <Box sx={{ textAlign: 'center', py: 8, px: 2, border: '1px dashed #d7e4df', borderRadius: 3, bgcolor: '#fbfcfb' }}>
            <Typography sx={{ fontWeight: 700, color: warmText, mb: 0.75 }}>暂无{tab === 0 ? '进行中的' : tab === 1 ? '已完成的' : ''}随访计划</Typography>
            <Typography variant="body2" sx={{ color: carePalette.muted }}>完成一次问诊并保存记录后，这里会陆续出现需要关注的事项。</Typography>
          </Box>
        )}

        <Stack spacing={2}>
          {filtered.map((plan) => {
            const taskEntries = getTasks(plan);
            const pct = completionRate(plan);
            const planStatus = getPlanStatus(plan);

            return (
              <Card key={plan.id} sx={{ borderRadius: 3 }}>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                    <Typography variant="h6" sx={{ color: warmText, fontWeight: 600 }}>
                      {plan.title || '护理计划'}
                    </Typography>
                    <Chip label={planStatus}
                      color={planStatus === '已完成' ? 'success' : planStatus === '已过期' ? 'default' : 'warning'} size="small" />
                  </Box>
                  {plan.description && (
                    <Typography variant="body2" sx={{ color: carePalette.muted, mb: 1 }}>{plan.description}</Typography>
                  )}
                  <LinearProgress variant="determinate" value={pct}
                    sx={{ mb: 1, height: 8, borderRadius: 4, bgcolor: carePalette.line,
                      '& .MuiLinearProgress-bar': { bgcolor: warmPrimary } }} />
                  <Typography variant="caption" color="text.secondary">进度 {pct}%</Typography>
                  <Divider sx={{ my: 1.5 }} />
                  <Stack spacing={1}>
                    {taskEntries.map((task, idx) => {
                      const isCompleted = isTaskCompleted(task);
                      const taskId = task.id;
                      const isAcking = !!taskId && ackingTask === `${plan.id}:${taskId}`;
                      return (
                      <Box key={taskId || idx} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Checkbox checked={isCompleted}
                          onChange={() => taskId && handleAck(plan.id, taskId)}
                          disabled={isCompleted || !taskId || isAcking}
                          size="small" sx={{ color: warmPrimary, '&.Mui-checked': { color: warmPrimary } }} />
                        <Typography variant="body2" sx={{
                          flex: 1, color: warmText,
                          textDecoration: isCompleted ? 'line-through' : 'none',
                        }}>
                          {task.description || task.name || `任务 ${idx + 1}`}
                        </Typography>
                      </Box>
                    );})}
                  </Stack>
                  {plan.start_date && (
                    <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                      开始: {new Date(plan.start_date).toLocaleDateString('zh-CN')}
                      {plan.end_date && ` — 结束: ${new Date(plan.end_date).toLocaleDateString('zh-CN')}`}
                    </Typography>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </Stack>
      </Container>
    </Box>
  );
}
