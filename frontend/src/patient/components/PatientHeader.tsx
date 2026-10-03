import { Link as RouterLink } from 'react-router-dom';
import { AppBar, IconButton, Toolbar, Typography } from '@mui/material';
import MenuRoundedIcon from '@mui/icons-material/MenuRounded';
import NotificationsNoneRoundedIcon from '@mui/icons-material/NotificationsNoneRounded';
import { carePalette } from '../../theme';

export default function PatientHeader({ title, onOpenNavigation, isGuest = false }: {
  title: string;
  onOpenNavigation: () => void;
  isGuest?: boolean;
}) {
  return <AppBar component="header" aria-label="患者页顶部栏" position="static" elevation={0} sx={{
    bgcolor: 'rgba(255,255,255,.85)', borderBottom: `1px solid ${carePalette.line}`,
    backdropFilter: 'blur(16px)', '@media print': { display: 'none' },
  }}>
    <Toolbar sx={{ minHeight: { xs: 64, md: 72 }, px: { xs: 2, sm: 3, lg: 4 }, gap: 1.5 }}>
      <IconButton edge="start" onClick={onOpenNavigation} aria-label="打开导航菜单" sx={{ display: { md: 'none' }, color: carePalette.muted }}><MenuRoundedIcon /></IconButton>
      {isGuest ? <Typography variant="body2" color="text.secondary">访客模式</Typography>
        : <Typography component={RouterLink} to="/today" variant="body2" sx={{ color: carePalette.muted, textDecoration: 'none', '&:hover': { color: carePalette.primaryDark } }}>患者工作台</Typography>}
      <Typography aria-hidden="true" sx={{ color: '#cbd5e1' }}>/</Typography>
      <Typography variant="body2" sx={{ color: carePalette.ink, fontWeight: 500, flex: 1 }}>{title}</Typography>
      {!isGuest && <IconButton component={RouterLink} to="/reminders" aria-label="查看提醒" sx={{ color: carePalette.muted, bgcolor: '#f1f5f9', borderRadius: '14px', width: 42, height: 42 }}><NotificationsNoneRoundedIcon sx={{ fontSize: 21 }} /></IconButton>}
    </Toolbar>
  </AppBar>;
}
