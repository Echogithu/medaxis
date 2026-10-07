import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Box, ButtonBase, Drawer, Typography } from '@mui/material';
import { HomeOutlined, ChatBubbleOutlineRounded, DescriptionOutlined, HealingOutlined, MoreHorizRounded, CalendarMonthOutlined, MedicationOutlined, UploadFileOutlined } from '@mui/icons-material';
import { carePalette } from '../../theme';

const links = [
  { path: '/today', label: '今日', icon: <HomeOutlined /> },
  { path: '/chat', label: '问诊', icon: <ChatBubbleOutlineRounded /> },
  { path: '/cases', label: '记录', icon: <DescriptionOutlined /> },
  { path: '/health', label: '档案', icon: <HealingOutlined /> },
];
const moreLinks = [
  { path: '/followups', label: '随访计划', icon: <CalendarMonthOutlined /> },
  { path: '/reminders', label: '用药提醒', icon: <MedicationOutlined /> },
  { path: '/reports', label: '检查报告', icon: <UploadFileOutlined /> },
];

export default function MobilePatientNav() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const go = (path: string) => { setOpen(false); navigate(path); };
  return <>
    <Box component="nav" aria-label="移动端导航" sx={{
      display: { xs: 'grid', md: 'none' }, gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
      position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 1100,
      p: '8px 8px calc(8px + env(safe-area-inset-bottom))',
      bgcolor: 'rgba(255,255,255,.88)', backdropFilter: 'blur(16px)', borderTop: `1px solid ${carePalette.line}`,
      '@media print': { display: 'none' },
    }}>
      {links.map(link => <ButtonBase key={link.path} aria-label={link.label === '今日' ? '今日健康' : link.label === '问诊' ? 'AI 问诊' : link.label === '记录' ? '问诊记录' : '健康档案'}
        aria-current={pathname === link.path ? 'page' : undefined} onClick={() => go(link.path)}
        sx={{ py: 0.75, gap: 0.25, flexDirection: 'column', borderRadius: '12px', minHeight: 48,
          color: pathname === link.path ? carePalette.primaryDark : carePalette.muted,
          bgcolor: pathname === link.path ? carePalette.mint : 'transparent', '& .MuiSvgIcon-root': { fontSize: 22 } }}>
        {link.icon}<Typography sx={{ fontSize: 11, fontWeight: 600 }}>{link.label}</Typography>
      </ButtonBase>)}
      <ButtonBase aria-label="更多功能" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}
        sx={{ py: 0.75, gap: 0.25, flexDirection: 'column', borderRadius: '12px', color: moreLinks.some(link => pathname.startsWith(link.path)) ? carePalette.primaryDark : carePalette.muted }}>
        <MoreHorizRounded /><Typography sx={{ fontSize: 11, fontWeight: 600 }}>更多</Typography>
      </ButtonBase>
    </Box>
    <Drawer anchor="bottom" open={open} onClose={() => setOpen(false)} slotProps={{ paper: { sx: { p: 3, pb: 'calc(32px + env(safe-area-inset-bottom))', borderRadius: '32px 32px 0 0' }, role: 'dialog', 'aria-label': '更多功能' } }}>
      <Box sx={{ width: 40, height: 4, borderRadius: 2, bgcolor: carePalette.line, mx: 'auto', mb: 2 }} />
      <Typography variant="h6" sx={{ mb: 2 }}>更多功能</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
        {moreLinks.map(link => <ButtonBase key={link.path} onClick={() => go(link.path)} sx={{ flexDirection: 'column', gap: 1, p: 3, borderRadius: '16px', bgcolor: carePalette.page, color: carePalette.primaryDark }}>
          {link.icon}<Typography variant="body2">{link.label}</Typography>
        </ButtonBase>)}
      </Box>
    </Drawer>
  </>;
}
