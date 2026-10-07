import { Suspense, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Box, CircularProgress } from '@mui/material';
import Sidebar from '../../components/Sidebar';
import MobilePatientNav from '../components/MobilePatientNav';
import PatientHeader from '../components/PatientHeader';
import { carePalette } from '../../theme';
import { getToken } from '../../api/client';
import { ChatNavigationContext, type ChatNavigation } from './chatNavigation';

const pageTitles: Record<string, string> = {
  '/today': '今日健康', '/chat': 'AI 问诊', '/health': '健康档案', '/followups': '随访计划', '/reminders': '用药提醒', '/cases': '问诊记录', '/reports': '检查报告',
};

export default function PatientLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [chatNavigation, setChatNavigation] = useState<ChatNavigation | null>(null);
  const location = useLocation();
  const isChat = location.pathname === '/chat';
  const isGuest = !getToken();
  return <ChatNavigationContext.Provider value={setChatNavigation}><Box sx={{ display: 'flex', height: '100dvh', minHeight: 0, bgcolor: carePalette.page,
    '@media print': { height: 'auto', display: 'block', bgcolor: '#fff', '& > .MuiDrawer-root': { display: 'none' } } }}>
    <Sidebar sessions={isChat ? chatNavigation?.sessions || [] : []} currentSessionId={isChat ? chatNavigation?.currentSessionId : undefined}
      onSelectSession={id => { chatNavigation?.onSelectSession(id); setMobileOpen(false); }}
      onDeleteSession={id => chatNavigation?.onDeleteSession(id)} busy={chatNavigation?.busy}
      mobileOpen={mobileOpen} onMobileClose={() => setMobileOpen(false)} isGuest={isGuest} showSessions={isChat && Boolean(chatNavigation)} />
    <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', '@media print': { display: 'block', overflow: 'visible' } }}>
      <PatientHeader title={pageTitles[location.pathname] || (location.pathname.startsWith('/reports/') ? '检查报告' : '医枢')} onOpenNavigation={() => setMobileOpen(true)} isGuest={isGuest} />
      <Box component={isChat ? 'div' : 'main'} sx={{ flex: 1, minHeight: 0, overflow: isChat ? 'hidden' : 'auto', pb: isGuest ? 0 : { xs: 'calc(80px + env(safe-area-inset-bottom))', md: 0 },
        '& > .MuiBox-root > .MuiContainer-root': { maxWidth: 1200, px: { xs: 2, sm: 3, lg: 4 } },
        '& > .MuiBox-root > .MuiContainer-root > .MuiBox-root:first-of-type': { pt: { xs: 3, sm: 4 }, pb: 3 },
        '@media print': { overflow: 'visible', pb: 0 } }}>
        <Suspense fallback={<Box sx={{ height: '100%', minHeight: 240, display: 'grid', placeItems: 'center' }}><CircularProgress aria-label="加载页面内容" /></Box>}><Outlet /></Suspense>
      </Box>
    </Box>
    {!isGuest && <MobilePatientNav />}
  </Box></ChatNavigationContext.Provider>;
}
