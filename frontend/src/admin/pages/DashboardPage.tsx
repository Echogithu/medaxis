import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Skeleton,
  Stack,
  Typography,
  useTheme,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import AssignmentOutlinedIcon from '@mui/icons-material/AssignmentOutlined';
import HealthAndSafetyOutlinedIcon from '@mui/icons-material/HealthAndSafetyOutlined';
import MenuBookOutlinedIcon from '@mui/icons-material/MenuBookOutlined';
import NotificationsNoneOutlinedIcon from '@mui/icons-material/NotificationsNoneOutlined';
import PeopleAltOutlinedIcon from '@mui/icons-material/PeopleAltOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import { fetchDashboardStats } from '../../api/admin';
import type { DashboardStats } from '../../types/admin';
import { PageHeader } from '../../components/layout/PageHeader';

type Accent = 'primary' | 'success' | 'warning' | 'secondary';

const ROLE_NAMES: Record<string, string> = {
  patient: '患者',
  doctor: '医生',
  admin: '管理员',
};

function MetricCard({
  title,
  value,
  note,
  icon,
  accent,
  to,
}: {
  title: string;
  value: string | number;
  note: string;
  icon: ReactNode;
  accent: Accent;
  to: string;
}) {
  const theme = useTheme();
  const accentColor = {
    primary: theme.palette.primary.main,
    success: theme.palette.success.main,
    warning: theme.palette.warning.main,
    secondary: theme.palette.secondary.main,
  }[accent];

  return (
    <Card
      component={Link}
      to={to}
      sx={{
        height: '100%',
        color: 'inherit',
        textDecoration: 'none',
        borderRadius: 2,
        transition: 'transform 150ms ease, box-shadow 150ms ease, border-color 150ms ease',
        '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 6px 16px rgba(15, 23, 42, 0.1)', borderColor: 'primary.main' },
        '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 },
      }}
    >
      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
          <Typography variant="body2" sx={{ color: 'text.secondary', fontSize: '0.75rem' }}>{title}</Typography>
          <Avatar variant="rounded" sx={{ width: 32, height: 32, borderRadius: 1, color: accentColor, bgcolor: alpha(accentColor, theme.palette.mode === 'dark' ? 0.2 : 0.1) }}>
            {icon}
          </Avatar>
        </Box>
        <Typography sx={{ mt: 1.1, color: 'text.primary', fontSize: '1.75rem', fontWeight: 700, lineHeight: 1.1, letterSpacing: '-0.04em', fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
        <Typography variant="caption" sx={{ display: 'block', mt: 0.75, color: 'text.secondary', fontSize: '0.74rem' }}>{note}</Typography>
      </CardContent>
    </Card>
  );
}
function SectionHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 2, mb: 2 }}>
      <Box>
        <Typography sx={{ fontSize: '0.94rem', fontWeight: 760, letterSpacing: '-0.015em' }}>{title}</Typography>
        <Typography variant="caption" sx={{ display: 'block', mt: 0.35, color: 'text.secondary', fontSize: '0.74rem' }}>{description}</Typography>
      </Box>
      {action}
    </Box>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retryCount, setRetryCount] = useState(0);
  const theme = useTheme();

  useEffect(() => {
    let cancelled = false;
    fetchDashboardStats()
      .then((data) => { if (!cancelled) setStats(data); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : '加载仪表盘失败'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [retryCount]);

  const roleEntries = useMemo(() => Object.entries(stats?.users.by_role ?? {}), [stats]);
  const lastUpdated = stats?.timestamp
    ? new Date(stats.timestamp).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '--';

  if (loading) {
    return (
      <Box>
        <Skeleton variant="text" width={250} height={42} />
        <Skeleton variant="text" width={320} height={24} sx={{ mb: 2.5 }} />
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' }, gap: 1.75 }}>
          {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} variant="rounded" height={126} sx={{ borderRadius: 2 }} />)}
        </Box>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.45fr) minmax(320px, 0.8fr)' }, gap: 2, mt: 2 }}>
          <Skeleton variant="rounded" height={310} sx={{ borderRadius: 2 }} />
          <Skeleton variant="rounded" height={310} sx={{ borderRadius: 2 }} />
        </Box>
      </Box>
    );
  }

  if (error || !stats) {
    return (
      <Box sx={{ maxWidth: 560, mx: 'auto', mt: 8 }}>
        <Alert
          severity="error"
          action={(
            <Button
              color="inherit"
              size="small"
              onClick={() => {
                setLoading(true);
                setError('');
                setRetryCount((count) => count + 1);
              }}
            >
              重试
            </Button>
          )}
        >
          加载仪表盘失败：{error || '暂无数据'}
        </Alert>
      </Box>
    );
  }

  const doctorCount = stats.users.by_role.doctor ?? 0;

  return (
    <Box>
      <PageHeader
        title="运营概览"
        subtitle="查看平台用户、模型配置与常用管理入口。"
        actions={<Box sx={{ display: { xs: 'none', sm: 'block' }, textAlign: 'right' }}>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.74rem' }}>{new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' })}</Typography>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 0.7, mt: 0.45, color: 'text.secondary', fontSize: '0.74rem', fontWeight: 600 }}>
            数据更新于 {lastUpdated}
          </Box>
        </Box>}
      />

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' }, gap: 1.5, mb: 1.5 }}>
        <MetricCard title="总用户数" value={stats.users.total.toLocaleString()} note="查看账号与用户状态" icon={<PeopleAltOutlinedIcon fontSize="small" />} accent="primary" to="/admin/users" />
        <MetricCard title="注册医生" value={doctorCount.toLocaleString()} note="查看医生认证资料" icon={<HealthAndSafetyOutlinedIcon fontSize="small" />} accent="success" to="/admin/doctors" />
        <MetricCard title="启用供应商" value={stats.llm_providers.active} note={`${stats.llm_providers.total} 项配置 · 当前已启用`} icon={<SmartToyOutlinedIcon fontSize="small" />} accent="warning" to="/admin/providers" />
        <MetricCard title="系统设置项" value={stats.system_settings} note="管理平台运行配置" icon={<SettingsOutlinedIcon fontSize="small" />} accent="secondary" to="/admin/settings" />
      </Box>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.45fr) minmax(320px, 0.8fr)' }, gap: 1.5, mb: 1.5 }}>
        <Card>
          <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
            <SectionHeader title="用户角色分布" description="当前用户结构与管理范围" action={<Chip size="small" label="统计快照" color="primary" variant="outlined" />} />
            {roleEntries.length > 0 ? (
              <Stack spacing={1.5}>
                {roleEntries.map(([role, count]) => {
                  const percentage = stats.users.total ? Math.round((count / stats.users.total) * 100) : 0;
                  const roleColor = role === 'doctor'
                    ? theme.palette.success.main
                    : role === 'admin'
                      ? theme.palette.secondary.main
                      : theme.palette.primary.main;
                  return (
                    <Box key={role}>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, mb: 0.65 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.9 }}>
                          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: roleColor }} />
                          <Typography sx={{ fontSize: '0.76rem', fontWeight: 650 }}>{ROLE_NAMES[role] || role}</Typography>
                        </Box>
                        <Typography sx={{ color: 'text.secondary', fontSize: '0.72rem' }}>{count.toLocaleString()} <Box component="span" sx={{ color: 'text.disabled' }}>· {percentage}%</Box></Typography>
                      </Box>
                      <Box sx={{ height: 7, borderRadius: 7, bgcolor: 'action.hover', overflow: 'hidden' }}><Box sx={{ width: `${percentage}%`, height: '100%', borderRadius: 7, bgcolor: roleColor, transition: 'width 420ms ease' }} /></Box>
                    </Box>
                  );
                })}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">暂无角色分布数据</Typography>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
            <SectionHeader title="常用管理入口" description="医生审核、病例复核与通知管理" />
            <Stack spacing={1}>
              {[
                { label: '医生认证', description: '查看医生资质申请', path: '/admin/doctors', icon: <HealthAndSafetyOutlinedIcon fontSize="small" /> },
                { label: '病例审核', description: '处理知识内容审核队列', path: '/admin/reviews', icon: <AssignmentOutlinedIcon fontSize="small" /> },
                { label: '知识库管理', description: '维护文档与检索内容', path: '/admin/knowledge', icon: <MenuBookOutlinedIcon fontSize="small" /> },
                { label: '站内信', description: '查看并发送平台通知', path: '/admin/notifications', icon: <NotificationsNoneOutlinedIcon fontSize="small" /> },
              ].map((item) => (
                <Button
                  key={item.path}
                  component={Link}
                  to={item.path}
                  variant="text"
                  sx={{ justifyContent: 'flex-start', textAlign: 'left', p: 1, borderRadius: 1, color: 'text.primary', '&:hover': { bgcolor: 'action.hover' } }}
                  endIcon={<ArrowForwardRoundedIcon sx={{ ml: 'auto', color: 'text.secondary', width: 17, height: 17 }} />}
                >
                  <Avatar variant="rounded" sx={{ width: 30, height: 30, mr: 1.1, bgcolor: 'primary.light', color: 'primary.dark', borderRadius: 1 }}>{item.icon}</Avatar>
                  <Box><Typography sx={{ fontSize: '0.76rem', fontWeight: 700 }}>{item.label}</Typography><Typography variant="caption" sx={{ display: 'block', mt: 0.15, color: 'text.secondary', fontSize: '0.64rem' }}>{item.description}</Typography></Box>
                </Button>
              ))}
            </Stack>
          </CardContent>
        </Card>
      </Box>

    </Box>
  );
}
