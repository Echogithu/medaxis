import React, { useState, useEffect } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  IconButton,
  InputAdornment,
  Link,
  Paper,
  Snackbar,
  TextField,
  Typography,
  useTheme,
} from '@mui/material';
import {
  ArrowForwardRounded,
  ChatBubbleOutlineRounded,
  EventNoteOutlined,
  FolderOpenOutlined,
  Lock,
  Email,
  MedicalServices,
  Person,
  Visibility,
  VisibilityOff,
} from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';
import { login, getMe } from '../api/auth';
import { agentApi } from '../api/agent';
import { getToken } from '../api/client';
import { completeGuestMigration } from './guestMigration';
import { carePalette } from '../theme';
import { useDemoMode } from '../state/demoMode';

const serviceItems = [
  { label: 'AI 问诊', icon: <ChatBubbleOutlineRounded /> },
  { label: '健康档案', icon: <FolderOpenOutlined /> },
  { label: '随访计划', icon: <EventNoteOutlined /> },
];

function loginNotice(state: unknown, search: string): string {
  const message = (state as { message?: string } | null)?.message || '';
  const params = new URLSearchParams(search);
  if (params.get('verified') === 'true') return '邮箱验证成功！请登录您的账号。';
  if (params.get('doctor_confirmed') === 'true') return '医生认证确认成功！请登录您的账号。';
  return message;
}

const LoginPage: React.FC = () => {
  const theme = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const demo = useDemoMode();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [guestLoading, setGuestLoading] = useState(false);
  const [guestError, setGuestError] = useState('');
  const [snackbar, setSnackbar] = useState<{
    open: boolean;
    message: string;
    severity: 'error' | 'success';
  }>(() => {
    const message = loginNotice(location.state, location.search);
    return { open: Boolean(message), message, severity: 'success' };
  });

  useEffect(() => {
    const msg = (location.state as { message?: string } | null)?.message;
    const params = new URLSearchParams(location.search);
    if (params.get('verified') === 'true' || params.get('doctor_confirmed') === 'true') {
      window.history.replaceState({}, '', '/login');
    } else if (msg) window.history.replaceState({}, '');
  }, [location.state, location.search]);

  const handleCloseSnackbar = () => setSnackbar((prev) => ({ ...prev, open: false }));

  const handleGuestAccess = async () => {
    setGuestLoading(true);
    setGuestError('');
    try {
      if (!getToken()) {
        await agentApi.createGuestSession();
      }
      navigate('/chat');
    } catch {
      setGuestError('暂时无法开始访客问诊，请检查网络后重试。');
    } finally {
      setGuestLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setSnackbar({ open: true, message: '请输入邮箱和密码', severity: 'error' });
      return;
    }
    setLoading(true);
    try {
      await login({ email: email.trim(), password, role: 'patient' });
      try {
        if (!demo?.enabled) await completeGuestMigration();
      } catch {
        setSnackbar({
          open: true,
          message: '登录已成功，但访客记录迁移未全部完成。请再次提交登录以重试；本地访客记录仍保留。',
          severity: 'error',
        });
        return;
      }
      const user = await getMe();
      const routes: Record<string, string> = {
        patient: '/today',
        doctor: '/doctor',
        admin: '/admin',
      };
      navigate(routes[user.role] || '/today', { replace: true });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '登录失败，请稍后重试';
      setSnackbar({ open: true, message, severity: 'error' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ minHeight: '100dvh', bgcolor: 'background.default' }}>
      <Box
        sx={{
          width: '100%',
          maxWidth: 1240,
          minHeight: '100dvh',
          mx: 'auto',
          px: { xs: 1.5, sm: 3, lg: 4 },
          py: { xs: 1.5, sm: 2.5 },
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Box component="header" sx={{ display: 'flex', alignItems: 'center', gap: 1.25, minHeight: 44 }}>
          <Box
            sx={{
              width: 40,
              height: 40,
              display: 'grid',
              placeItems: 'center',
              borderRadius: '13px',
              color: '#fff',
              bgcolor: carePalette.primary,
              boxShadow: '0 7px 18px rgba(23,143,130,0.17)',
            }}
          >
            <MedicalServices sx={{ fontSize: 22 }} />
          </Box>
          <Typography variant="h6" sx={{ fontWeight: 750, color: carePalette.ink, letterSpacing: '-0.02em' }}>
            医枢 MedAxis
          </Typography>
        </Box>

        <Paper
          component="main"
          elevation={0}
          sx={{
            flex: 1,
            my: { xs: 1.5, sm: 2.5, md: 3 },
            minHeight: { md: 570 },
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: '1.08fr 0.92fr' },
            overflow: 'hidden',
            border: `1px solid ${carePalette.line}`,
            borderRadius: { xs: '18px', sm: '24px' },
            bgcolor: 'background.paper',
            boxShadow: '0 18px 48px rgba(34,61,55,0.055)',
          }}
        >
          <Box
            sx={{
              p: { xs: 2.5, sm: 4, md: 6, lg: 7 },
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'flex-start',
              gap: { xs: 3, md: 4 },
              bgcolor: carePalette.mint,
            }}
          >
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: { xs: 3, md: 4 }, my: { md: 'auto' } }}>
              <Box>
                <Typography
                  component="h1"
                  sx={{
                    color: carePalette.ink,
                    fontFamily: '"Noto Serif SC", "Songti SC", serif',
                    fontSize: { xs: '2rem', sm: '2.6rem', lg: '3rem' },
                    fontWeight: 650,
                    lineHeight: 1.35,
                    letterSpacing: '0.01em',
                    mb: 1.5,
                  }}
                >
                  健康管理，<br />从一次对话开始。
                </Typography>
                <Typography variant="body1" sx={{ color: carePalette.muted, maxWidth: 410 }}>
                  问诊、健康档案与随访计划，轻松衔接。
                </Typography>
              </Box>

              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                  gap: { xs: 0.75, sm: 1.25 },
                  maxWidth: 520,
                }}
              >
                {serviceItems.map((item) => (
                  <Box
                    key={item.label}
                    sx={{
                      minWidth: 0,
                      minHeight: { xs: 76, sm: 92 },
                      p: { xs: 1, sm: 1.5 },
                      display: 'flex',
                      flexDirection: { xs: 'column', sm: 'row' },
                      alignItems: 'center',
                      justifyContent: { xs: 'center', sm: 'flex-start' },
                      gap: { xs: 0.5, sm: 1 },
                      border: `1px solid ${carePalette.line}`,
                      borderRadius: '14px',
                      bgcolor: 'rgba(255,255,255,0.78)',
                    }}
                  >
                    <Box
                      sx={{
                        width: 32,
                        height: 32,
                        flex: '0 0 auto',
                        display: 'grid',
                        placeItems: 'center',
                        borderRadius: '10px',
                        color: carePalette.primary,
                        bgcolor: carePalette.primarySoft,
                        '& svg': { fontSize: 18 },
                      }}
                    >
                      {item.icon}
                    </Box>
                    <Typography
                      variant="body2"
                      sx={{ color: carePalette.ink, fontWeight: 600, fontSize: { xs: 11, sm: 13 }, whiteSpace: 'nowrap' }}
                    >
                      {item.label}
                    </Typography>
                  </Box>
                ))}
              </Box>
            </Box>

            <Typography variant="caption" sx={{ color: carePalette.muted }}>
              AI 建议仅供健康参考，不替代医生诊断。
            </Typography>
          </Box>

          <Box
            sx={{
              px: { xs: 2.5, sm: 4, md: 5, lg: 6 },
              py: { xs: 3, sm: 4, md: 5 },
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              borderTop: { xs: `1px solid ${carePalette.line}`, md: 'none' },
              borderLeft: { md: `1px solid ${carePalette.line}` },
            }}
          >
            <Box sx={{ width: '100%', maxWidth: 390 }}>
              <Typography
                variant="h4"
                sx={{ fontWeight: 700, mb: 0.75, color: theme.palette.text.primary, letterSpacing: '-0.025em' }}
              >
                欢迎回来
              </Typography>
              <Typography variant="body2" sx={{ mb: 3, color: theme.palette.text.secondary }}>
                登录医枢 MedAxis
              </Typography>

              <Box component="form" onSubmit={handleSubmit} noValidate>
                <TextField
                  fullWidth
                  id="email-input"
                  label="邮箱地址"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  margin="normal"
                  required
                  autoComplete="email"
                  disabled={loading}
                  slotProps={{
                    input: {
                      startAdornment: (
                        <InputAdornment position="start">
                          <Email sx={{ color: theme.palette.primary.main }} />
                        </InputAdornment>
                      ),
                    },
                  }}
                  sx={{ mb: 1 }}
                />
                <TextField
                  fullWidth
                  id="password-input"
                  label="密码"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  margin="normal"
                  required
                  autoComplete="current-password"
                  disabled={loading}
                  slotProps={{
                    input: {
                      startAdornment: (
                        <InputAdornment position="start">
                          <Lock sx={{ color: theme.palette.primary.main }} />
                        </InputAdornment>
                      ),
                      endAdornment: (
                        <InputAdornment position="end">
                          <IconButton
                            type="button"
                            onClick={() => setShowPassword((prev) => !prev)}
                            edge="end"
                            aria-label={showPassword ? '隐藏密码' : '显示密码'}
                          >
                            {showPassword ? <VisibilityOff /> : <Visibility />}
                          </IconButton>
                        </InputAdornment>
                      ),
                    },
                  }}
                  sx={{ mb: 2 }}
                />

                <Button
                  type="submit"
                  fullWidth
                  variant="contained"
                  size="large"
                  disabled={loading || guestLoading}
                  endIcon={!loading && <ArrowForwardRounded />}
                  sx={{ minHeight: 50, mt: 1, fontSize: '0.98rem' }}
                >
                  {loading ? <CircularProgress size={22} color="inherit" /> : '登录'}
                </Button>
              </Box>

              {demo?.enabled && <Alert severity="info" sx={{ mt: 2 }}>请使用单独提供的演示账号登录。访客体验与公开注册已停用。</Alert>}
              {demo?.enabled === false && <>
              <Divider sx={{ my: 2.5, color: 'text.secondary', fontSize: 12 }}>或</Divider>

              {guestError && <Alert severity="error" sx={{ mb: 1.5 }}>{guestError}</Alert>}
              <Button
                fullWidth
                variant="outlined"
                size="large"
                disabled={loading || guestLoading}
                onClick={handleGuestAccess}
                startIcon={guestLoading ? <CircularProgress size={17} color="inherit" /> : <Person />}
                sx={{ minHeight: 48, borderColor: carePalette.line, color: carePalette.ink, '&:hover': { borderColor: carePalette.primary, bgcolor: carePalette.mint } }}
              >
                以访客身份体验
              </Button>

              <Typography variant="body2" sx={{ mt: 2.5, textAlign: 'center', color: theme.palette.text.secondary }}>
                没有账号？{' '}
                <Link
                  component="button"
                  type="button"
                  onClick={() => navigate('/register')}
                  sx={{ color: theme.palette.primary.main, fontWeight: 650, textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
                >
                  去注册
                </Link>
              </Typography>
              </>}
            </Box>
          </Box>
        </Paper>

        <Box component="footer" sx={{ textAlign: 'center', pb: { xs: 0.5, sm: 1 } }}>
          <Typography variant="caption" sx={{ color: carePalette.muted }}>
            © 2026 医枢 MedAxis
          </Typography>
        </Box>
      </Box>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={handleCloseSnackbar}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert onClose={handleCloseSnackbar} severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default LoginPage;
