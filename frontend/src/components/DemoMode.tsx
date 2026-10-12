import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Alert, Button } from '@mui/material';
import { API_BASE } from '../api/client';
import { DemoContext } from '../state/demoMode';
import type { DemoStatus } from '../state/demoMode';

export function DemoModeProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [error, setError] = useState(false);
  const refresh = useCallback(() => {
    // 状态更新发生在异步响应中；首次加载、定时刷新和手动刷新共用同一入口。
    return fetch(`${API_BASE}/demo/status`, { cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error('无法读取演示状态');
      const value = await response.json() as DemoStatus;
      if (typeof value.enabled !== 'boolean' || !Number.isInteger(value.remaining)) throw new Error('状态无效');
      setStatus(value);
      setError(false);
    }).catch(() => { setError(true); });
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!status?.enabled) return;
    const timer = window.setInterval(() => { void refresh(); }, 15000);
    return () => window.clearInterval(timer);
  }, [status?.enabled, refresh]);
  return <DemoContext.Provider value={status}>
    {status?.enabled && <Alert severity={status.remaining ? 'info' : 'warning'}
      action={<Button color="inherit" size="small" onClick={() => { void refresh(); }}>刷新额度</Button>}>
      面试演示 · 预置资料为合成数据，请勿输入真实医疗资料 · 模型请求 {status.used}/{status.limit}
      {status.remaining === 0 && ' · 额度已用完，资料仍可浏览'}
    </Alert>}
    {error && <Alert severity="error">服务连接不可用，请刷新页面后重试。</Alert>}
    {children}
  </DemoContext.Provider>;
}
