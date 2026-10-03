import { useState, useEffect, useId, type MouseEvent } from 'react';
import {
  Box, Drawer, List, ListItem, ListItemButton, ListItemText,
  Typography, Divider, Button, Collapse, Badge, Avatar,
  Menu, MenuItem, ListItemIcon, IconButton, Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material';
import MoreHorizIcon from '@mui/icons-material/MoreHoriz';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ChatIcon from '@mui/icons-material/Chat';
import LogoutIcon from '@mui/icons-material/Logout';
import PersonAddIcon from '@mui/icons-material/PersonAdd';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import HealingIcon from '@mui/icons-material/Healing';
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth';
import MedicationIcon from '@mui/icons-material/Medication';
import MonitorHeartRoundedIcon from '@mui/icons-material/MonitorHeartRounded';
import FolderSharedOutlinedIcon from '@mui/icons-material/FolderSharedOutlined';
import HomeOutlinedIcon from '@mui/icons-material/HomeOutlined';
import type { ChatSession } from '../types/agent';
import { logout } from '../api/auth';
import { getProfile } from '../api/patient';
import { useLocation, useNavigate } from 'react-router-dom';

interface Props {
  sessions: ChatSession[];
  currentSessionId?: string;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  busy?: boolean;
  mobileOpen: boolean;
  onMobileClose: () => void;
  drawerWidth?: number;
  isGuest: boolean;
  showSessions?: boolean;
}

const DRAWER_WIDTH = 248;

function groupSessionsByDate(sessions: ChatSession[]): Record<string, ChatSession[]> {
  const groups: Record<string, ChatSession[]> = {};
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 86400000).toDateString();

  for (const s of sessions) {
    const d = new Date(s.updated_at);
    const dateStr = d.toDateString();
    let label = d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    if (dateStr === today) label = '今天';
    else if (dateStr === yesterday) label = '昨天';

    if (!groups[label]) groups[label] = [];
    groups[label].push(s);
  }
  return groups;
}

export default function Sidebar({
  sessions, currentSessionId, onSelectSession, onDeleteSession, busy,
  mobileOpen, onMobileClose, drawerWidth = DRAWER_WIDTH, isGuest,
  showSessions = true,
}: Props) {
  const [historyOpen, setHistoryOpen] = useState(true);
  const [chatMenu, setChatMenu] = useState<{ anchor: HTMLElement; id: string } | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [accountAnchorEl, setAccountAnchorEl] = useState<HTMLElement | null>(null);
  const accountMenuId = useId();
  const grouped = groupSessionsByDate(sessions);
  const navigate = useNavigate();
  const location = useLocation();
  const currentPath = location.pathname;
  const [reminderCount, setReminderCount] = useState(0);
  const [medicationCount, setMedicationCount] = useState(0);

  useEffect(() => {
    if (isGuest) return;
    const fetchCounts = async () => {
      try {
        const token = localStorage.getItem('access_token');
        const res = await fetch('/api/v1/patient/reminders/count', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setReminderCount(data.follow_up || 0);
          setMedicationCount(data.medication || 0);
        }
      } catch { /* Reminder counts are optional when the service is unavailable. */ }
    };
    fetchCounts();
    const interval = setInterval(fetchCounts, 60000);
    return () => clearInterval(interval);
  }, [isGuest]);

  useEffect(() => {
    if (isGuest) return;
    let cancelled = false;
    getProfile()
      .then((profile) => {
        if (!cancelled) setDisplayName(profile.name?.trim() || '');
      })
      .catch(() => {
        if (!cancelled) setDisplayName('');
      });
    return () => { cancelled = true; };
  }, [isGuest]);

  const handleAccountMenuOpen = (event: MouseEvent<HTMLButtonElement>) => {
    setAccountAnchorEl(event.currentTarget);
  };

  const handleAccountMenuClose = () => setAccountAnchorEl(null);

  const handleSettings = () => {
    handleAccountMenuClose();
    onMobileClose();
    navigate('/health');
  };

  const handleLogout = async () => {
    handleAccountMenuClose();
    onMobileClose();
    await logout();
    navigate('/login', { replace: true });
  };

  const drawerContent = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: '#fff' }}>
      <Box sx={{ px: 2.25, pt: 2.25, pb: 1.75, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.15, minWidth: 0 }}>
          <Box sx={{ width: 40, height: 40, display: 'grid', placeItems: 'center', borderRadius: '13px', color: '#fff', bgcolor: '#0d9488', boxShadow: '0 8px 20px rgba(23,143,130,.18)' }}>
            <MonitorHeartRoundedIcon sx={{ fontSize: 22 }} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ color: '#1e293b', fontSize: 16, fontWeight: 800, lineHeight: 1.1, whiteSpace: 'nowrap' }}>医枢 MedAxis</Typography>
            <Typography sx={{ mt: 0.4, color: '#92a09f', fontSize: 9.5, whiteSpace: 'nowrap' }}>患者端</Typography>
          </Box>
        </Box>
      </Box>

      <Divider sx={{ mx: 2, borderColor: '#edf0ed' }} />

      <Box sx={{ flex: 1, overflow: 'auto', px: 1.25, py: 1.5 }}>
        <List dense disablePadding sx={{ mb: 1.5 }}>
          {!isGuest && <ListItem disablePadding sx={{ mb: 0.5 }}>
            <ListItemButton selected={currentPath === '/today'} aria-current={currentPath === '/today' ? 'page' : undefined} onClick={() => { onMobileClose(); navigate('/today'); }} sx={{ minHeight: 46, borderRadius: '16px', px: 1.75, color: '#64748b', '&:hover': { bgcolor: '#f8fafc' }, '&.Mui-selected': { color: '#0f766e', bgcolor: '#f0fdfa', '&:hover': { bgcolor: '#ccfbf1' } } }}>
              <HomeOutlinedIcon sx={{ fontSize: 20, mr: 1.5 }} />
              <ListItemText primary="今日健康" slotProps={{ primary: { variant: 'body2', sx: { fontWeight: 600 } } }} />
            </ListItemButton>
          </ListItem>}
          <ListItem disablePadding sx={{ mb: 0.5 }}>
            <ListItemButton selected={currentPath === '/chat'} onClick={() => { onMobileClose(); navigate('/chat'); }} sx={{ minHeight: 46, borderRadius: '16px', px: 1.75, color: '#64748b', '&:hover': { bgcolor: '#f8fafc', color: '#1e293b' }, '&.Mui-selected': { color: '#0f766e', bgcolor: '#f0fdfa', '&:hover': { bgcolor: '#ccfbf1' } } }}>
              <ChatIcon sx={{ fontSize: 18, mr: 1.25 }} />
              <ListItemText primary="AI 问诊" slotProps={{ primary: { variant: 'body2', sx: { fontWeight: 600 } } }} />
            </ListItemButton>
          </ListItem>
          {!isGuest && (
            <>
              <ListItem disablePadding sx={{ mb: 0.5 }}>
                <ListItemButton selected={currentPath.startsWith('/cases')} onClick={() => { onMobileClose(); navigate('/cases'); }} sx={{ minHeight: 46, borderRadius: '16px', px: 1.75, color: '#64748b', '&:hover': { bgcolor: '#f8fafc', color: '#1e293b' }, '&.Mui-selected': { color: '#0f766e', bgcolor: '#f0fdfa', '&:hover': { bgcolor: '#ccfbf1' } } }}>
                  <FolderSharedOutlinedIcon sx={{ fontSize: 18, mr: 1.25 }} />
                  <ListItemText primary="问诊记录" slotProps={{ primary: { variant: 'body2', sx: { fontWeight: 650 } } }} />
                </ListItemButton>
              </ListItem>
              <ListItem disablePadding sx={{ mb: 0.5 }}>
                <ListItemButton selected={currentPath.startsWith('/health')} onClick={() => { onMobileClose(); navigate('/health'); }} sx={{ minHeight: 46, borderRadius: '16px', px: 1.75, color: '#64748b', '&:hover': { bgcolor: '#f8fafc', color: '#1e293b' }, '&.Mui-selected': { color: '#0f766e', bgcolor: '#f0fdfa', '&:hover': { bgcolor: '#ccfbf1' } } }}>
                  <HealingIcon sx={{ fontSize: 18, mr: 1.25 }} />
                  <ListItemText primary="健康档案" slotProps={{ primary: { variant: 'body2', sx: { fontWeight: 650 } } }} />
                </ListItemButton>
              </ListItem>
              <ListItem disablePadding sx={{ mb: 0.5 }}>
                <Badge badgeContent={reminderCount} color="warning" max={99} sx={{ width: '100%', '& .MuiBadge-badge': { top: 12, right: 14, fontSize: 9, height: 17, minWidth: 17, bgcolor: '#f2a27f', color: '#fff' } }}>
                  <ListItemButton selected={currentPath.startsWith('/followups')} onClick={() => { onMobileClose(); navigate('/followups'); }} sx={{ minHeight: 46, width: '100%', borderRadius: '16px', px: 1.75, color: '#64748b', '&:hover': { bgcolor: '#f8fafc', color: '#1e293b' }, '&.Mui-selected': { color: '#0f766e', bgcolor: '#f0fdfa', '&:hover': { bgcolor: '#ccfbf1' } } }}>
                    <CalendarMonthIcon sx={{ fontSize: 18, mr: 1.25 }} />
                    <ListItemText primary="随访计划" slotProps={{ primary: { variant: 'body2', sx: { fontWeight: 650 } } }} />
                  </ListItemButton>
                </Badge>
              </ListItem>
              <ListItem disablePadding>
                <Badge badgeContent={medicationCount} color="warning" max={99} sx={{ width: '100%', '& .MuiBadge-badge': { top: 12, right: 14, fontSize: 9, height: 17, minWidth: 17, bgcolor: '#f2a27f', color: '#fff' } }}>
                  <ListItemButton selected={currentPath.startsWith('/reminders')} onClick={() => { onMobileClose(); navigate('/reminders'); }} sx={{ minHeight: 46, width: '100%', borderRadius: '16px', px: 1.75, color: '#64748b', '&:hover': { bgcolor: '#f8fafc', color: '#1e293b' }, '&.Mui-selected': { color: '#0f766e', bgcolor: '#f0fdfa', '&:hover': { bgcolor: '#ccfbf1' } } }}>
                    <MedicationIcon sx={{ fontSize: 18, mr: 1.25 }} />
                    <ListItemText primary="用药提醒" slotProps={{ primary: { variant: 'body2', sx: { fontWeight: 650 } } }} />
                  </ListItemButton>
                </Badge>
              </ListItem>
            </>
          )}
        </List>

        {showSessions && <>
        <Typography sx={{ px: 1.25, mb: 0.5, color: '#64748b', fontSize: 10, fontWeight: 700, letterSpacing: '.12em' }}>最近会话</Typography>
        <ListItemButton onClick={() => setHistoryOpen(!historyOpen)} sx={{ minHeight: 36, borderRadius: '10px', px: 1.25, py: 0.5, color: '#475569', '&:hover': { bgcolor: '#f3f7f5' } }}>
          <Typography variant="body2" sx={{ fontWeight: 650, flex: 1 }}>
            会话历史
          </Typography>
          {historyOpen ? <ExpandLessIcon sx={{ color: '#94a3b8', fontSize: 19 }} /> : <ExpandMoreIcon sx={{ color: '#94a3b8', fontSize: 19 }} />}
        </ListItemButton>

        <Collapse in={historyOpen}>
          <List dense sx={{ py: 0 }}>
            {Object.entries(grouped).map(([label, items]) => (
              <Box key={label}>
                <Typography variant="caption" sx={{ px: 1.25, pt: 1, pb: 0.4, display: 'block', color: '#a0aaa9', fontSize: 10 }}>
                  {label}
                </Typography>
                {items.map((s) => (
                  <ListItem key={s.id} disablePadding sx={{ mb: 0.5 }}>
                    <ListItemButton selected={s.id === currentSessionId} onClick={() => onSelectSession(s.id)}
                      sx={{
                        minHeight: 36, borderRadius: '10px', px: 1.25, py: 0.5,
                        '&.Mui-selected': { bgcolor: '#f0fdfa', '&:hover': { bgcolor: '#e7f2ef' } },
                        '&:hover': { bgcolor: '#f5f8f6' },
                      }}>
                      <ChatIcon sx={{ fontSize: 15, color: s.id === currentSessionId ? '#0d9488' : '#98a5a4', mr: 1 }} />
                      <ListItemText primary={s.title || '新对话'}
                        slotProps={{ primary: { variant: 'body2', noWrap: true, sx: { color: s.id === currentSessionId ? '#1e293b' : '#64748b', fontSize: 12.5, fontWeight: s.id === currentSessionId ? 700 : 450 } } }}
                      />
                      <IconButton size="small" aria-label={`会话操作：${s.title || '新对话'}`}
                        disabled={busy && s.id === currentSessionId}
                        onClick={(event) => {
                          event.stopPropagation();
                          setChatMenu({ anchor: event.currentTarget, id: s.id });
                        }}
                        sx={{
                          ml: 0.5,
                          mr: -0.5,
                          p: 0.35,
                          color: s.id === currentSessionId ? '#6f8585' : '#8d9a99',
                          opacity: 1,
                          transition: 'color 160ms ease, background-color 160ms ease',
                          '&:hover': { color: '#1e293b', bgcolor: 'rgba(23,143,130,0.10)' },
                        }}>
                        <MoreHorizIcon fontSize="small" />
                      </IconButton>
                    </ListItemButton>
                  </ListItem>
                ))}
              </Box>
            ))}
            {sessions.length === 0 && (
              <Typography variant="caption" sx={{ px: 1.25, py: 1, display: 'block', color: '#9ba6a5' }}>
                暂无会话记录
              </Typography>
            )}
         </List>
       </Collapse>
        </>}
      </Box>

      <Divider sx={{ mx: 2, borderColor: '#edf0ed' }} />

      <Box sx={{ p: 1.5 }}>
        {isGuest ? (
          <Button fullWidth variant="outlined" startIcon={<PersonAddIcon />} onClick={() => navigate('/login')}
            sx={{ minHeight: 40, borderRadius: '12px', textTransform: 'none', color: '#48666a', borderColor: '#dce5e1', '&:hover': { borderColor: '#0d9488', bgcolor: '#f1f8f5' } }}>
            注册 / 登录
          </Button>
        ) : (
          <Button
            fullWidth
            variant="text"
            onClick={handleAccountMenuOpen}
            aria-controls={accountMenuId}
            aria-haspopup="menu"
            aria-expanded={Boolean(accountAnchorEl)}
            sx={{ minHeight: 48, justifyContent: 'flex-start', gap: 1, px: 0.75, borderRadius: '12px', textTransform: 'none', color: '#475569', '&:hover': { color: '#1e293b', bgcolor: '#f3f7f5' } }}
          >
            <Avatar aria-hidden="true" sx={{ width: 34, height: 34, fontSize: 14, fontWeight: 600, bgcolor: '#f0fdfa', color: '#0f766e', border: '1px solid #cce8df' }}>
              {Array.from(displayName || '患')[0]}
            </Avatar>
            <Typography variant="body2" noWrap sx={{ flex: 1, minWidth: 0, textAlign: 'left', color: '#1e293b', fontWeight: 700 }}>
              {displayName || '患者用户'}
            </Typography>
            <ExpandMoreIcon sx={{ color: '#94a3b8', fontSize: 18 }} />
          </Button>
        )}
      </Box>
    </Box>
  );

  return (
    <>
      <Menu anchorEl={chatMenu?.anchor} open={Boolean(chatMenu)} onClose={() => setChatMenu(null)}>
        <MenuItem onClick={() => { setDeletingId(chatMenu?.id || null); setChatMenu(null); }}>删除聊天</MenuItem>
      </Menu>
      <Dialog open={Boolean(deletingId)} onClose={() => setDeletingId(null)} aria-labelledby="delete-chat-title">
        <DialogTitle id="delete-chat-title">删除这段聊天？</DialogTitle>
        <DialogContent>将删除此浏览器中的聊天记录。已保存的问诊报告和资料仍会保留。</DialogContent>
        <DialogActions>
          <Button onClick={() => setDeletingId(null)}>取消</Button>
          <Button color="error" onClick={() => { if (deletingId) onDeleteSession(deletingId); setDeletingId(null); }}>删除聊天</Button>
        </DialogActions>
      </Dialog>
      <Drawer variant="permanent" sx={{
        width: drawerWidth, flexShrink: 0, display: { xs: 'none', md: 'block' },
        '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box', borderRight: '1px solid #f1f5f9', bgcolor: '#fff' },
      }} open>
        {drawerContent}
      </Drawer>
      <Drawer variant="temporary" open={mobileOpen} onClose={onMobileClose} ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: 'block', md: 'none' },
          '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box', borderRight: '1px solid #f1f5f9', bgcolor: '#fff' },
        }}>
        {drawerContent}
      </Drawer>
      {!isGuest && (
        <Menu
          id={accountMenuId}
          anchorEl={accountAnchorEl}
          open={Boolean(accountAnchorEl)}
          onClose={handleAccountMenuClose}
          anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
          transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
          slotProps={{ paper: { sx: { minWidth: 190, mb: 0.75, border: '1px solid #f1f5f9', borderRadius: '12px', boxShadow: '0 12px 30px rgba(34,61,55,.12)' } } }}
        >
          <MenuItem onClick={handleSettings} sx={{ minHeight: 42, color: '#475569' }}>
            <ListItemIcon sx={{ minWidth: 34, color: '#0d9488' }}><SettingsOutlinedIcon fontSize="small" /></ListItemIcon>
            设置
          </MenuItem>
          <Divider sx={{ my: 0.5 }} />
          <MenuItem onClick={handleLogout} sx={{ minHeight: 42, color: '#475569' }}>
            <ListItemIcon sx={{ minWidth: 34, color: '#64748b' }}><LogoutIcon fontSize="small" /></ListItemIcon>
            退出登录
          </MenuItem>
        </Menu>
      )}
    </>
  );
}
