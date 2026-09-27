import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { AppBar, Box, IconButton, Toolbar, Typography } from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import MonitorHeartRoundedIcon from '@mui/icons-material/MonitorHeartRounded';
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined';
import Chip from '@mui/material/Chip';
import Sidebar from '../../components/Sidebar';
import { careFonts, carePalette } from '../../theme';

const pageCopy: Record<string, { title: string; subtitle: string }> = {
  '/health': { title: '健康档案', subtitle: '过敏、慢病与用药，问诊时会作为参考' },
  '/followups': { title: '随访计划', subtitle: '按计划完成复查与护理任务' },
  '/reminders': { title: '用药提醒', subtitle: '按时服药，记录依从情况' },
  '/cases': { title: '问诊记录', subtitle: '查看总结、准备就诊与记录结果' },
};

export default function PatientLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const copy = pageCopy[location.pathname] || { title: '患者工作台', subtitle: '医枢健康管理' };

  return (
    <Box sx={{
      display: 'flex',
      height: '100dvh',
      minHeight: 0,
      bgcolor: carePalette.page,
      backgroundImage: 'radial-gradient(1000px 380px at 100% -12%, rgba(23,143,130,0.07), transparent 55%), radial-gradient(720px 280px at -10% 110%, rgba(229,138,104,0.07), transparent 50%)',
    }}>
      <Sidebar
        sessions={[]}
        onSelectSession={() => navigate('/chat')}
        onNewSession={() => navigate('/chat')}
        onDeleteSession={() => undefined}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
        isGuest={false}
        showSessions={false}
      />
      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <AppBar position="static" elevation={0} sx={{ bgcolor: 'rgba(255,255,255,0.92)', borderBottom: '1px solid #e6ebe8', backdropFilter: 'blur(12px)' }}>
          <Toolbar sx={{ minHeight: { xs: 58, sm: 64 }, px: { xs: 1.5, sm: 2.5 } }}>
            <IconButton edge="start" onClick={() => setMobileOpen(true)} aria-label="打开导航菜单" sx={{ mr: 1.25, display: { md: 'none' }, color: '#456267' }}>
              <MenuIcon />
            </IconButton>
            <Box sx={{ width: 34, height: 34, mr: 1.1, display: 'grid', placeItems: 'center', borderRadius: '11px', color: '#fff', bgcolor: carePalette.primary }}>
              <MonitorHeartRoundedIcon sx={{ fontSize: 20 }} />
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ color: carePalette.ink, fontFamily: careFonts.serif, fontSize: 16, fontWeight: 800, lineHeight: 1.2 }}>
                {copy.title}
              </Typography>
              <Typography sx={{ display: { xs: 'none', sm: 'block' }, color: '#94a1a0', fontSize: 11, lineHeight: 1.2, mt: 0.25 }}>
                {copy.subtitle}
              </Typography>
            </Box>
            <Chip
              icon={<VerifiedUserOutlinedIcon sx={{ fontSize: '15px !important' }} />}
              label="隐私保护"
              size="small"
              sx={{ display: { xs: 'none', sm: 'inline-flex' }, height: 28, color: '#52736f', bgcolor: '#edf7f3', border: '1px solid #dceee6', fontSize: 11, fontWeight: 650 }}
            />
          </Toolbar>
        </AppBar>
        <Box component="main" sx={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
          <Outlet />
        </Box>
      </Box>
    </Box>
  );
}
