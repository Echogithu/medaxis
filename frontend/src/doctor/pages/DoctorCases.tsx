import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Typography,
  Card,
  CardContent,
  TextField,
  Avatar,
  Chip,
  Button,
  IconButton,
  Skeleton,
  Stack,
  Divider,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import ArrowForwardIosIcon from '@mui/icons-material/ArrowForwardIos';
import VisibilityIcon from '@mui/icons-material/Visibility';
import MessageOutlinedIcon from '@mui/icons-material/MessageOutlined';
import { listPatients } from '../../api/doctor';
import type { PatientSummary } from '../../api/doctor';
import { flexRowBetweenMb2 } from '../../styles/sxUtils';


type FilterTag = 'all' | 'pending' | 'followup' | 'new' | 'high';

const filterTabs: { key: FilterTag; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待回复' },
  { key: 'followup', label: '随访中' },
  { key: 'new', label: '新患者' },
  { key: 'high', label: '高风险' },
];

const statusMap: Record<string, { label: string; color: 'default' | 'primary' | 'success' | 'warning' | 'error' }> = {
  pending: { label: '待处理', color: 'warning' },
  followup: { label: '随访中', color: 'primary' },
  stable: { label: '稳定', color: 'success' },
};

const riskMap: Record<string, { label: string; color: 'default' | 'primary' | 'success' | 'warning' | 'error' }> = {
  low: { label: '低风险', color: 'success' },
  medium: { label: '中风险', color: 'warning' },
  high: { label: '高风险', color: 'error' },
};

export default function DoctorCases() {
  const navigate = useNavigate();
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeFilter, setActiveFilter] = useState<FilterTag>('all');
  const [search, setSearch] = useState('');

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    listPatients()
      .then((data) => {
        if (mounted) setPatients(data);
      })
      .catch(() => {
        if (mounted) setPatients([]);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const filteredPatients = useMemo(() => {
    let result = patients;
    if (activeFilter === 'pending') {
      result = result.filter((p) => p.status === 'pending');
    } else if (activeFilter === 'followup') {
      result = result.filter((p) => p.status === 'followup');
    } else if (activeFilter === 'new') {
      result = result.filter((p) => p.last_activity.includes('新注册') || p.last_activity.includes('新'));
    } else if (activeFilter === 'high') {
      result = result.filter((p) => p.risk_level === 'high');
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.last_activity.toLowerCase().includes(q) ||
          p.agent_summary.toLowerCase().includes(q)
      );
    }
    return result;
  }, [patients, activeFilter, search]);

  const handleViewCase = (caseId: string) => {
    navigate(`/doctor/cases/${caseId}`);
  };

  return (
    <Box sx={{ display: 'flex', gap: 3, flexDirection: { xs: 'column', md: 'row' } }}>
      {/* 左侧筛选栏 */}
      <Box sx={{ width: { xs: '100%', md: 220 }, flexShrink: 0 }}>
        <Typography variant="h6" sx={{ fontWeight: 700, color: 'text.primary', mb: 2 }}>
          患者列表
        </Typography>
        <TextField
          fullWidth
          size="small"
          placeholder="搜索患者..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          slotProps={{
            input: {
              startAdornment: <SearchIcon sx={{ color: 'secondary.light', mr: 1, fontSize: '1.1rem' }} />,
            },
          }}
          sx={{
            mb: 2,
            '& .MuiOutlinedInput-root': {
              borderRadius: 2,
              bgcolor: '#fff',
            },
          }}
        />
        <Stack spacing={1}>
          {filterTabs.map((tab) => {
            const isActive = activeFilter === tab.key;
            return (
              <Button
                key={tab.key}
                fullWidth
                onClick={() => setActiveFilter(tab.key)}
                sx={{
                  justifyContent: 'flex-start',
                  textTransform: 'none',
                  fontWeight: isActive ? 600 : 500,
                  color: isActive ? 'primary.main' : 'text.secondary',
                  bgcolor: isActive ? 'rgba(23,143,130,0.10)' : 'transparent',
                  borderRadius: 2,
                  px: 2,
                  py: 1,
                  '&:hover': {
                    bgcolor: isActive ? 'rgba(23,143,130,0.14)' : 'rgba(23,143,130,0.04)',
                  },
                }}
              >
                {tab.label}
              </Button>
            );
          })}
        </Stack>
      </Box>

      <Divider orientation="vertical" flexItem sx={{ display: { xs: 'none', md: 'block' }, borderColor: 'secondary.light' }} />

      {/* 患者列表 */}
      <Box sx={{ flexGrow: 1 }}>
        <Box sx={flexRowBetweenMb2}>
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            共 {filteredPatients.length} 位患者
          </Typography>
        </Box>

        <Stack spacing={2}>
          {loading
            ? Array.from({ length: 4 }).map((_, idx) => (
                <Card key={idx} sx={{ borderRadius: 3 }}>
                  <CardContent>
                    <Skeleton variant="rectangular" height={100} />
                  </CardContent>
                </Card>
              ))
            : filteredPatients.map((p) => (
                <Card
                  key={p.id}
                  sx={{
                    borderRadius: 3,
                    boxShadow: '0 5px 18px rgba(34,61,55,0.045)',
                    transition: 'box-shadow 0.2s',
                    '&:hover': { boxShadow: '0 10px 26px rgba(34,61,55,0.09)' },
                  }}
                >
                  <CardContent>
                    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2 }}>
                      <Avatar sx={{ bgcolor: 'primary.main', fontWeight: 600 }}>
                        {p.name[0]}
                      </Avatar>
                      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, flexWrap: 'wrap' }}>
                          <Typography variant="subtitle1" sx={{ fontWeight: 600, color: 'text.primary' }}>
                            {p.name}
                          </Typography>
                          <Chip
                            size="small"
                            label={statusMap[p.status]?.label || p.status}
                            color={statusMap[p.status]?.color || 'default'}
                          />
                          {p.risk_level && (
                            <Chip
                              size="small"
                              variant="outlined"
                              label={riskMap[p.risk_level]?.label || p.risk_level}
                              color={riskMap[p.risk_level]?.color || 'default'}
                            />
                          )}
                        </Box>
                        <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.5 }}>
                          {p.last_activity}
                        </Typography>
                        <Typography variant="body2" sx={{ color: 'text.primary', mb: 1 }}>
                          {p.agent_summary}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<VisibilityIcon fontSize="small" />}
                            onClick={() => handleViewCase(p.id)}
                            sx={{
                              textTransform: 'none',
                              borderRadius: 2,
                              borderColor: 'primary.main',
                              color: 'primary.main',
                              '&:hover': { bgcolor: 'rgba(23,143,130,0.06)' },
                            }}
                          >
                            查看病例
                          </Button>
                          <Button
                            size="small"
                            variant="text"
                            startIcon={<MessageOutlinedIcon fontSize="small" />}
                            onClick={() => navigate('/doctor/messages')}
                            sx={{
                              textTransform: 'none',
                              borderRadius: 2,
                              color: 'text.secondary',
                              '&:hover': { color: 'primary.main', bgcolor: 'rgba(23,143,130,0.06)' },
                            }}
                          >
                            发消息
                          </Button>
                        </Box>
                      </Box>
                      <IconButton
                        size="small"
                        onClick={() => handleViewCase(p.id)}
                        sx={{ color: 'secondary.light', mt: 0.5 }}
                      >
                        <ArrowForwardIosIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  </CardContent>
                </Card>
              ))}
          {!loading && filteredPatients.length === 0 && (
            <Card sx={{ borderRadius: 3, textAlign: 'center', py: 6 }}>
              <Typography variant="body1" sx={{ color: 'text.secondary' }}>
                没有找到匹配的患者
              </Typography>
            </Card>
          )}
        </Stack>
      </Box>
    </Box>
  );
}
