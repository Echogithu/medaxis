import { Box, Typography, Button, Chip, LinearProgress } from '@mui/material';
import LoginIcon from '@mui/icons-material/Login';
import PersonAddIcon from '@mui/icons-material/PersonAdd';
import type { GuestStatus } from '../types/agent';
import { flexRowGap15 } from '../styles/sxUtils';


interface Props {
  status: GuestStatus | null;
  onRegister: () => void;
  onLogin: () => void;
}

export default function GuestBanner({ status, onRegister, onLogin }: Props) {
  if (!status) return null;

  const progress = ((status.max_interactions - status.remaining) / status.max_interactions) * 100;
  const isNearLimit = status.remaining <= 1;

  return (
    <Box sx={{ bgcolor: isNearLimit ? '#fff6ee' : '#f4f8f6', borderBottom: '1px solid #e5ece8', px: { xs: 1.5, sm: 2.5 }, py: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1 }}>
        <Box sx={flexRowGap15}>
          <Chip label="访客模式" size="small"
            sx={{ height: 24, bgcolor: isNearLimit ? '#fae7d8' : '#e4f1eb', color: isNearLimit ? '#a95e37' : '#3d766d', fontWeight: 650, fontSize: 10.5 }} />
          <Typography variant="body2" color={isNearLimit ? 'error' : 'text.secondary'}>
            已使用 {status.interaction_count} / {status.max_interactions} 次模型请求
          </Typography>
          {isNearLimit && (
            <Typography variant="caption" color="error" sx={{ fontWeight: 500 }}>
              ⚠️ 模型请求次数即将用完，请注册以继续
            </Typography>
          )}
        </Box>

        <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', width: { xs: '100%', sm: 'auto' }, justifyContent: { xs: 'flex-start', sm: 'flex-end' } }}>
          <Button size="small" variant="outlined" startIcon={<LoginIcon fontSize="small" />} onClick={onLogin}
            sx={{ minHeight: 30, borderColor: '#d7e2dd', color: '#4f6b6f', textTransform: 'none', borderRadius: '9px', fontSize: 11, '&:hover': { borderColor: '#178f82', bgcolor: '#eef7f3' } }}>
            登录
          </Button>
          <Button size="small" variant="contained" startIcon={<PersonAddIcon fontSize="small" />} onClick={onRegister}
            sx={{ minHeight: 30, bgcolor: '#178f82', textTransform: 'none', borderRadius: '9px', fontSize: 11, boxShadow: 'none', '&:hover': { bgcolor: '#0c756b', boxShadow: 'none' } }}>
            注册
          </Button>
        </Box>
      </Box>

      <LinearProgress variant="determinate" value={progress}
        sx={{ mt: 0.75, height: 3, borderRadius: 2, bgcolor: '#e1eae5', '& .MuiLinearProgress-bar': { bgcolor: isNearLimit ? '#e99a71' : '#55a892', borderRadius: 2 } }} />
    </Box>
  );
}
