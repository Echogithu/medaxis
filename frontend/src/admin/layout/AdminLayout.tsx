import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Autocomplete,
  AppBar,
  Avatar,
  Badge,
  Box,
  CircularProgress,
  CssBaseline,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  ThemeProvider,
  TextField,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined';
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined';
import HealthAndSafetyOutlinedIcon from '@mui/icons-material/HealthAndSafetyOutlined';
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined';
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined';
import LocalHospitalOutlinedIcon from '@mui/icons-material/LocalHospitalOutlined';
import MenuBookOutlinedIcon from '@mui/icons-material/MenuBookOutlined';
import ChevronLeftOutlinedIcon from '@mui/icons-material/ChevronLeftOutlined';
import ChevronRightOutlinedIcon from '@mui/icons-material/ChevronRightOutlined';
import MenuIcon from '@mui/icons-material/Menu';
import NotificationsNoneOutlinedIcon from '@mui/icons-material/NotificationsNoneOutlined';
import PeopleAltOutlinedIcon from '@mui/icons-material/PeopleAltOutlined';
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import AssignmentOutlinedIcon from '@mui/icons-material/AssignmentOutlined';
import LogoutOutlinedIcon from '@mui/icons-material/LogoutOutlined';
import KeyboardArrowDownOutlinedIcon from '@mui/icons-material/KeyboardArrowDownOutlined';
import { logout, getMe, getUnreadCount } from '../../api/admin';
import AdminLoginPage from '../pages/AdminLoginPage';
import ChangePasswordPage from '../pages/ChangePasswordPage';
import ChangePasswordDialog from '../components/ChangePasswordDialog';
import { pageCenter } from '../../styles/sxUtils';
import { createAdminTheme, type AdminThemeMode } from '../adminTheme';

const DRAWER_WIDTH = 258;
const DRAWER_COLLAPSED_WIDTH = 72;
const ADMIN_THEME_STORAGE_KEY = 'admin_theme_mode';
const ADMIN_SIDEBAR_STORAGE_KEY = 'admin_sidebar_collapsed';
const NAV_ITEM_BUTTON_SX = {
  minHeight: 42,
  px: 1.35,
  borderRadius: 0,
  gap: 0.9,
  position: 'relative',
  transition: 'background-color 150ms ease, color 150ms ease',
  '&:hover': { bgcolor: 'action.hover' },
  '&.Mui-selected': {
    bgcolor: 'primary.light',
    color: 'primary.dark',
    '&::before': {
      content: '""',
      position: 'absolute',
      left: 0,
      top: 0,
      bottom: 0,
      width: 3,
      bgcolor: 'primary.main',
    },
    '&:hover': { bgcolor: 'primary.light' },
  },
};

const navItemIconSx = (isSelected: boolean) => ({
  minWidth: 24,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: isSelected ? 'primary.dark' : 'text.secondary',
  '& .MuiSvgIcon-root': { fontSize: 14 },
});

const navItemTextSx = (isSelected: boolean) => ({
  fontSize: '0.875rem',
  fontWeight: isSelected ? 650 : 500,
  lineHeight: 1.35,
});

const NAV_ITEMS = [
  { path: '/admin', label: '仪表盘', icon: <DashboardOutlinedIcon /> },
  { path: '/admin/users', label: '用户管理', icon: <PeopleAltOutlinedIcon /> },
  { path: '/admin/doctors', label: '医生认证', icon: <LocalHospitalOutlinedIcon /> },
  { path: '/admin/knowledge', label: '知识库管理', icon: <MenuBookOutlinedIcon /> },
  { path: '/admin/reviews', label: '病例审核', icon: <AssignmentOutlinedIcon /> },
  { path: '/admin/audit-logs', label: '审计日志', icon: <HistoryOutlinedIcon /> },
  { path: '/admin/notifications', label: '站内信', icon: <NotificationsNoneOutlinedIcon /> },
  { path: '/admin/email', label: '邮件管理', icon: <EmailOutlinedIcon /> },
  { path: '/admin/providers', label: 'LLM 供应商', icon: <SmartToyOutlinedIcon /> },
  { path: '/admin/settings', label: '系统设置', icon: <SettingsOutlinedIcon /> },
];

function AdminThemeShell({ theme, children }: { theme: ReturnType<typeof createAdminTheme>; children: ReactNode }) {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {children}
    </ThemeProvider>
  );
}

function getInitialThemeMode(): AdminThemeMode {
  const saved = localStorage.getItem(ADMIN_THEME_STORAGE_KEY);
  return saved === 'dark' ? 'dark' : 'light';
}

export default function AdminLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(ADMIN_SIDEBAR_STORAGE_KEY) === 'true');
  const [themeMode, setThemeMode] = useState<AdminThemeMode>(getInitialThemeMode);
  const [accountAnchor, setAccountAnchor] = useState<null | HTMLElement>(null);
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState<number | null>(null);
  const [authState, setAuthState] = useState(() => {
    const token = localStorage.getItem('access_token');
    return {
      checked: !token,
      authenticated: !!token,
      needPasswordChange: false,
      message: '',
    };
  });
  const theme = useMemo(() => createAdminTheme(themeMode), [themeMode]);
  const navigate = useNavigate();
  const location = useLocation();

  const { checked: authChecked, authenticated: isAuthenticated, needPasswordChange } = authState;
  const currentNav = NAV_ITEMS.find(
    (item) => item.path === location.pathname || (item.path !== '/admin' && location.pathname.startsWith(item.path)),
  );

  useEffect(() => {
    localStorage.setItem(ADMIN_THEME_STORAGE_KEY, themeMode);
    document.documentElement.dataset.adminTheme = themeMode;
  }, [themeMode]);

  useEffect(() => {
    localStorage.setItem(ADMIN_SIDEBAR_STORAGE_KEY, String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) return;

    getMe()
      .then((user) => {
        if (user.role !== 'admin') {
          logout();
          setAuthState({
            checked: true,
            authenticated: false,
            needPasswordChange: false,
            message: '当前账号没有管理员权限，请使用管理员账号登录。',
          });
          return;
        }

        setAuthState({
          checked: true,
          authenticated: true,
          needPasswordChange:
            user.password_change_required || localStorage.getItem('password_change_required') === 'true',
          message: '',
        });
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '';
        if (msg.includes('401') || msg.includes('Unauthorized')) {
          logout();
          setAuthState({ checked: true, authenticated: false, needPasswordChange: false, message: '' });
        } else {
          setAuthState({
            checked: true,
            authenticated: false,
            needPasswordChange: false,
            message: '暂时无法验证管理员身份，请重新登录。',
          });
        }
      });
  }, []);

  useEffect(() => {
    if (!authChecked || !isAuthenticated) return;

    let active = true;
    getUnreadCount()
      .then(({ total }) => { if (active) setUnreadCount(total); })
      .catch(() => { if (active) setUnreadCount(null); });
    return () => { active = false; };
  }, [authChecked, isAuthenticated, location.pathname]);

  const handleLogout = () => {
    setAccountAnchor(null);
    setUnreadCount(null);
    logout();
    setAuthState({ checked: true, authenticated: false, needPasswordChange: false, message: '' });
    navigate('/admin');
  };

  const handleThemeToggle = () => setThemeMode((mode) => (mode === 'light' ? 'dark' : 'light'));

  if (!authChecked) {
    return (
      <AdminThemeShell theme={theme}>
        <Box sx={{ ...pageCenter, bgcolor: 'background.default', minHeight: '100vh' }}>
          <CircularProgress color="primary" />
        </Box>
      </AdminThemeShell>
    );
  }

  if (!isAuthenticated) {
    return <AdminThemeShell theme={theme}><AdminLoginPage message={authState.message} /></AdminThemeShell>;
  }

  if (needPasswordChange) {
    return <AdminThemeShell theme={theme}><ChangePasswordPage /></AdminThemeShell>;
  }

  const drawer = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'background.paper' }}>
      <Toolbar sx={{ minHeight: '76px !important', px: sidebarCollapsed ? 1 : 2.5, gap: 1.25, justifyContent: sidebarCollapsed ? 'center' : 'flex-start' }}>
        <Avatar variant="rounded" sx={{ width: 40, height: 40, bgcolor: 'primary.main', color: 'primary.contrastText', borderRadius: 1.5 }}>
          <HealthAndSafetyOutlinedIcon />
        </Avatar>
        {!sidebarCollapsed && (
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 780, fontSize: '1rem', letterSpacing: '-0.02em' }}>医枢</Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary', letterSpacing: '0.15em', fontSize: '0.6rem' }}>ADMIN CONSOLE</Typography>
          </Box>
        )}
      </Toolbar>
      <Divider />
      <Box sx={{ flex: 1, overflowY: 'auto', px: sidebarCollapsed ? 0.75 : 1.25, py: 1.75 }}>
        {!sidebarCollapsed && <Typography variant="overline" sx={{ px: 1.25, color: 'text.secondary', fontWeight: 650, letterSpacing: '0.08em', fontSize: '0.6875rem' }}>工作台</Typography>}
        <List disablePadding sx={{ mt: 0.65 }}>
          {NAV_ITEMS.slice(0, 1).map((item) => {
            const isSelected = location.pathname === item.path;
            return (
              <ListItem key={item.path} disablePadding>
                <ListItemButton component={Link} to={item.path} selected={isSelected} onClick={() => setMobileOpen(false)} sx={{ ...NAV_ITEM_BUTTON_SX, justifyContent: sidebarCollapsed ? 'center' : 'flex-start', px: sidebarCollapsed ? 0 : 1.35 }}>
                  <ListItemIcon sx={navItemIconSx(isSelected)}>{item.icon}</ListItemIcon>
                  {!sidebarCollapsed && <ListItemText primary={<Typography sx={navItemTextSx(isSelected)}>{item.label}</Typography>} />}
                </ListItemButton>
              </ListItem>
            );
          })}
        </List>
        {!sidebarCollapsed && <Typography variant="overline" sx={{ display: 'block', mt: 2.3, px: 1.25, color: 'text.secondary', fontWeight: 650, letterSpacing: '0.08em', fontSize: '0.6875rem' }}>运营管理</Typography>}
        <List disablePadding sx={{ mt: 0.65 }}>
          {NAV_ITEMS.slice(1, 5).map((item) => {
            const isSelected = location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
            return (
              <ListItem key={item.path} disablePadding>
                <ListItemButton component={Link} to={item.path} selected={isSelected} onClick={() => setMobileOpen(false)} sx={{ ...NAV_ITEM_BUTTON_SX, justifyContent: sidebarCollapsed ? 'center' : 'flex-start', px: sidebarCollapsed ? 0 : 1.35 }}>
                  <ListItemIcon sx={navItemIconSx(isSelected)}>{item.icon}</ListItemIcon>
                  {!sidebarCollapsed && <ListItemText primary={<Typography sx={navItemTextSx(isSelected)}>{item.label}</Typography>} />}
                </ListItemButton>
              </ListItem>
            );
          })}
        </List>
        {!sidebarCollapsed && <Typography variant="overline" sx={{ display: 'block', mt: 2.3, px: 1.25, color: 'text.secondary', fontWeight: 650, letterSpacing: '0.08em', fontSize: '0.6875rem' }}>系统管理</Typography>}
        <List disablePadding sx={{ mt: 0.65 }}>
          {NAV_ITEMS.slice(5).map((item) => {
            const isSelected = location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
            return (
              <ListItem key={item.path} disablePadding>
                <ListItemButton component={Link} to={item.path} selected={isSelected} onClick={() => setMobileOpen(false)} sx={{ ...NAV_ITEM_BUTTON_SX, justifyContent: sidebarCollapsed ? 'center' : 'flex-start', px: sidebarCollapsed ? 0 : 1.35 }}>
                  <ListItemIcon sx={navItemIconSx(isSelected)}>{item.icon}</ListItemIcon>
                  {!sidebarCollapsed && <ListItemText primary={<Typography sx={navItemTextSx(isSelected)}>{item.label}</Typography>} />}
                </ListItemButton>
              </ListItem>
            );
          })}
        </List>
      </Box>
      <Box sx={{ px: sidebarCollapsed ? 1 : 1.5, py: 1.25, borderTop: 1, borderColor: 'divider', display: 'flex', justifyContent: sidebarCollapsed ? 'center' : 'flex-end' }}>
        <Tooltip title={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} placement="right">
          <IconButton onClick={() => setSidebarCollapsed((collapsed) => !collapsed)} aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} sx={{ border: 1, borderColor: 'divider', borderRadius: 1.25 }}>
            {sidebarCollapsed ? <ChevronRightOutlinedIcon fontSize="small" /> : <ChevronLeftOutlinedIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  );

  return (
    <AdminThemeShell theme={theme}>
      <Box className="admin-shell" sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
        <AppBar
          position="fixed"
          color="default"
          sx={{
            zIndex: (muiTheme) => muiTheme.zIndex.drawer + 1,
            width: { md: `calc(100% - ${sidebarCollapsed ? DRAWER_COLLAPSED_WIDTH : DRAWER_WIDTH}px)` },
            ml: { md: `${sidebarCollapsed ? DRAWER_COLLAPSED_WIDTH : DRAWER_WIDTH}px` },
            bgcolor: 'background.paper',
            color: 'text.primary',
            borderBottom: 1,
            borderColor: 'divider',
            boxShadow: '0 1px 0 rgba(15, 23, 42, 0.03)',
            transition: 'width 180ms ease, margin-left 180ms ease',
          }}
        >
          <Toolbar sx={{ minHeight: '72px !important', px: { xs: 1.5, md: 3.25 }, gap: 1.5 }}>
            <IconButton
              edge="start"
              onClick={() => setMobileOpen((open) => !open)}
              sx={{ display: { md: 'none' }, border: 1, borderColor: 'divider' }}
              aria-label="打开菜单"
            >
              <MenuIcon fontSize="small" />
            </IconButton>

            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="caption" sx={{ color: 'text.secondary', display: { xs: 'none', sm: 'block' }, fontSize: '0.68rem' }}>
                管理后台&nbsp;&nbsp;/&nbsp;&nbsp;<Box component="span" sx={{ color: 'text.primary', fontWeight: 720 }}>{currentNav?.label || '仪表盘'}</Box>
              </Typography>
              <Typography sx={{ display: { xs: 'block', sm: 'none' }, fontSize: '0.9rem', fontWeight: 720 }}>{currentNav?.label || '仪表盘'}</Typography>
            </Box>

            <Autocomplete
              size="small"
              options={NAV_ITEMS.map(({ path, label }) => ({ path, label }))}
              getOptionLabel={(option) => option.label}
              onChange={(_, option) => { if (option) navigate(option.path); }}
              autoHighlight
              sx={{
                width: { sm: 220, lg: 290 },
                display: { xs: 'none', sm: 'block' },
                '& .MuiOutlinedInput-root': { height: 38, py: 0, borderRadius: 1, bgcolor: 'action.hover' },
                '& .MuiInputBase-input': { fontSize: '0.8125rem' },
              }}
              renderInput={(params) => (
                <TextField
                  {...params}
                  placeholder="搜索管理页面"
                  slotProps={{
                    ...params.slotProps,
                    input: {
                      ...params.slotProps.input,
                      startAdornment: <><SearchOutlinedIcon sx={{ width: 17, height: 17, ml: 0.75, mr: 0.5, color: 'text.secondary' }} />{params.slotProps.input.startAdornment}</>,
                    },
                    htmlInput: { ...params.slotProps.htmlInput, 'aria-label': '搜索管理页面' },
                  }}
                />
              )}
            />

            <Tooltip title={unreadCount ? `${unreadCount} 条未读站内信` : '站内信'}>
              <IconButton onClick={() => navigate('/admin/notifications')} sx={{ border: 1, borderColor: 'divider', position: 'relative' }} aria-label={unreadCount ? `站内信，${unreadCount} 条未读` : '站内信'}>
                <Badge badgeContent={unreadCount ?? 0} color="error" max={99} invisible={!unreadCount}>
                  <NotificationsNoneOutlinedIcon fontSize="small" />
                </Badge>
              </IconButton>
            </Tooltip>

            <Tooltip title={themeMode === 'light' ? '切换深色主题' : '切换浅色主题'}>
              <IconButton onClick={handleThemeToggle} sx={{ border: 1, borderColor: 'divider' }} aria-label="切换主题">
                {themeMode === 'light' ? <DarkModeOutlinedIcon fontSize="small" /> : <LightModeOutlinedIcon fontSize="small" />}
              </IconButton>
            </Tooltip>

            <Box>
              <Tooltip title="账户菜单">
                <IconButton
                  onClick={(event) => setAccountAnchor(event.currentTarget)}
                  aria-label="打开账户菜单"
                  aria-haspopup="menu"
                  aria-expanded={accountAnchor !== null}
                  sx={{
                    ml: { xs: 0, sm: 0.25 },
                    pl: { xs: 0.35, sm: 1.25 },
                    pr: 0.45,
                    py: 0.45,
                    gap: 0.8,
                    border: 1,
                    borderColor: accountAnchor !== null ? 'primary.main' : 'divider',
                    borderRadius: 1,
                  }}
                >
                  <Typography sx={{ display: { xs: 'none', sm: 'block' }, color: 'text.secondary', fontSize: '0.72rem', fontWeight: 680, whiteSpace: 'nowrap' }}>超级管理员</Typography>
                  <Avatar sx={{ width: 30, height: 30, bgcolor: 'primary.main', color: 'primary.contrastText', fontSize: '0.72rem', fontWeight: 780 }}>管</Avatar>
                  <KeyboardArrowDownOutlinedIcon sx={{ display: { xs: 'none', sm: 'block' }, width: 16, height: 16, color: 'text.secondary', transform: accountAnchor ? 'rotate(180deg)' : 'none', transition: 'transform 180ms ease' }} />
                </IconButton>
              </Tooltip>
              <Menu
                anchorEl={accountAnchor}
                open={Boolean(accountAnchor)}
                onClose={() => setAccountAnchor(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                slotProps={{ paper: { sx: { mt: 1, minWidth: 218, borderRadius: 1, border: 1, borderColor: 'divider', boxShadow: 5 } } }}
              >
                <Box sx={{ px: 2, py: 1.35 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2 }}>
                    <Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.main', color: 'primary.contrastText', fontSize: '0.78rem', fontWeight: 780 }}>管</Avatar>
                    <Box><Typography sx={{ fontSize: '0.78rem', fontWeight: 740 }}>系统管理员</Typography><Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>Super Admin</Typography></Box>
                  </Box>
                </Box>
                <Divider />
                <MenuItem
                  onClick={() => {
                    setAccountAnchor(null);
                    setChangePasswordOpen(true);
                  }}
                  sx={{ mx: 0.7, mt: 0.5, borderRadius: 0.75, fontSize: '0.78rem', gap: 1 }}
                >
                  <SettingsOutlinedIcon sx={{ width: 17, height: 17 }} />
                  修改密码
                </MenuItem>
                <MenuItem onClick={handleLogout} sx={{ mx: 0.7, my: 0.5, borderRadius: 0.75, color: 'error.main', fontSize: '0.78rem', gap: 1 }}>
                  <LogoutOutlinedIcon sx={{ width: 17, height: 17 }} />
                  退出登录
                </MenuItem>
              </Menu>
              <ChangePasswordDialog open={changePasswordOpen} onClose={() => setChangePasswordOpen(false)} />
            </Box>
          </Toolbar>
        </AppBar>

        <Box component="nav" sx={{ width: { md: sidebarCollapsed ? DRAWER_COLLAPSED_WIDTH : DRAWER_WIDTH }, flexShrink: { md: 0 }, transition: 'width 180ms ease' }}>
          <Drawer
            variant="temporary"
            open={mobileOpen}
            onClose={() => setMobileOpen(false)}
            ModalProps={{ keepMounted: true }}
            sx={{ display: { xs: 'block', md: 'none' }, '& .MuiDrawer-paper': { boxSizing: 'border-box', width: DRAWER_WIDTH, borderRadius: 0 } }}
          >
            {drawer}
          </Drawer>
          <Drawer
            variant="permanent"
            open
            sx={{ display: { xs: 'none', md: 'block' }, '& .MuiDrawer-paper': { boxSizing: 'border-box', width: sidebarCollapsed ? DRAWER_COLLAPSED_WIDTH : DRAWER_WIDTH, borderRadius: 0, borderRight: 1, borderColor: 'divider', overflowX: 'hidden', transition: 'width 180ms ease' } }}
          >
            {drawer}
          </Drawer>
        </Box>

        <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: { xs: 2, md: 3 }, width: { md: `calc(100% - ${sidebarCollapsed ? DRAWER_COLLAPSED_WIDTH : DRAWER_WIDTH}px)` }, mt: '72px', transition: 'width 180ms ease' }}>
          <Outlet />
        </Box>
      </Box>
    </AdminThemeShell>
  );
}
