import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Card, CardContent, Chip, CircularProgress, List, ListItemButton, ListItemText, Stack, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { downloadCaseMaterial, getCaseRecovery, listCases } from '../../api/patient';
import type { CaseRecovery, MedicalCase } from '../../api/patient';
import CasePreparationPanel from '../components/CasePreparationPanel';
import PostVisitFeedbackPanel from '../components/PostVisitFeedbackPanel';
import PatientReportBody from '../../components/PatientReportBody';
import { patientText } from '../../state/patientText';
import { careFonts, carePalette } from '../../theme';

const statusLabels: Record<string, string> = { queued: '等待处理', processing: '处理中', completed: '已整理', failed: '处理失败' };
const demoDepartments = ['全科/普通门诊', '内科', '外科', '妇产科', '儿科', '眼科', '耳鼻喉科', '皮肤科'];
function caseTitle(item: { chief_complaint?: string; title: string }): string {
  return patientText(item.chief_complaint) || patientText(item.title.replace(/^AI Diagnosis:\s*/i, '')) || '问诊记录';
}

function CaseDetail({ recovery }: { recovery: CaseRecovery }) {
  const [downloadError, setDownloadError] = useState('');
  return <Stack spacing={2}>
    <Box>
      <Typography variant="h5" sx={{ fontFamily: careFonts.serif, fontWeight: 700 }}>{caseTitle(recovery.case)}</Typography>
      <Typography variant="body2" color="text.secondary">
        {recovery.case.created_at ? new Date(recovery.case.created_at).toLocaleString('zh-CN') : ''}
      </Typography>
    </Box>
    <Box sx={{
      position: 'relative', overflow: 'hidden', px: { xs: 1.75, sm: 2.5 }, py: { xs: 1.75, sm: 2.5 },
      border: '1px solid #e1e8e4', borderRadius: '22px', bgcolor: '#fff',
      '&::before': { content: '""', position: 'absolute', left: 0, top: 0, bottom: 0, width: 5, background: 'linear-gradient(180deg, #178f82 0%, #e58a68 100%)' },
    }}>
      <Typography sx={{ fontFamily: careFonts.serif, fontWeight: 800, mb: 2 }}>本次问诊总结</Typography>
      {recovery.report ? <PatientReportBody report={recovery.report} /> : <Alert severity="info">这次问诊暂无总结。</Alert>}
    </Box>
    <Accordion disableGutters>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>准备去就诊</AccordionSummary>
      <AccordionDetails>
        {recovery.report && <CasePreparationPanel caseId={recovery.case.id} />}
        <Accordion disableGutters elevation={0} sx={{ mt: 2 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>浏览科室名称（演示目录）</AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>通用科室名称，仅供浏览，不构成针对你的科室推荐或预约。</Typography>
            <Stack direction="row" useFlexGap sx={{ flexWrap: 'wrap', gap: 1 }}>
              {demoDepartments.map(department => <Chip key={department} label={department} variant="outlined" />)}
            </Stack>
            <Typography variant="caption" color="text.secondary">来源：本项目内置演示目录 · v1 · 非具体医院科室表</Typography>
          </AccordionDetails>
        </Accordion>
      </AccordionDetails>
    </Accordion>
    <Accordion disableGutters>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>记录就诊结果</AccordionSummary>
      <AccordionDetails><PostVisitFeedbackPanel caseId={recovery.case.id} /></AccordionDetails>
    </Accordion>
    {recovery.materials.length > 0 && <Accordion disableGutters>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>上传的检查资料（{recovery.materials.length}）</AccordionSummary>
      <AccordionDetails>
        {downloadError && <Alert severity="error">{downloadError}</Alert>}
        <Stack spacing={1}>
          {recovery.materials.map(material => <Box key={material.file_id} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box sx={{ flex: 1, minWidth: 0 }}><Typography sx={{ overflowWrap: 'anywhere' }}>{material.filename}</Typography>
              <Typography variant="caption" color="text.secondary">{statusLabels[material.status] || material.status}</Typography></Box>
            <Button onClick={() => {
              setDownloadError('');
              void downloadCaseMaterial(recovery.case.id, material.file_id, material.filename).catch(() => setDownloadError('资料下载失败，请重试。'));
            }}>下载</Button>
          </Box>)}
        </Stack>
      </AccordionDetails>
    </Accordion>}
  </Stack>;
}

export default function PatientCasesPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedCaseId = searchParams.get('case_id');
  const [cases, setCases] = useState<MedicalCase[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [recovery, setRecovery] = useState<CaseRecovery | null>(null);
  const [loadingCases, setLoadingCases] = useState(true);
  const [loadingRecovery, setLoadingRecovery] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [listReload, setListReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listCases().then(items => {
      if (cancelled) return;
      setCases(items);
      const id = requestedCaseId || items[0]?.id || '';
      setSelectedId(items.some(item => item.id === id) ? id : '');
      setLoadingRecovery(items.some(item => item.id === id));
      setError(id && !items.some(item => item.id === id) ? '未找到这条问诊记录，请从列表选择。' : '');
    }).catch(() => { if (!cancelled) setError('问诊记录暂时无法读取，请重试。'); })
      .finally(() => { if (!cancelled) setLoadingCases(false); });
    return () => { cancelled = true; };
  }, [requestedCaseId, listReload]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    getCaseRecovery(selectedId).then(item => {
      if (cancelled) return;
      if (item.case.id !== selectedId) { setError('记录不匹配，请重新选择。'); return; }
      setRecovery(item);
    }).catch(() => { if (!cancelled) setError('这条问诊记录暂时无法读取，请重试。'); })
      .finally(() => { if (!cancelled) setLoadingRecovery(false); });
    return () => { cancelled = true; };
  }, [selectedId, reload]);

  const currentRecovery = recovery?.case.id === selectedId ? recovery : null;
  const selectCase = (id: string) => {
    if (id === selectedId) return;
    setSelectedId(id); setRecovery(null); setLoadingRecovery(true); setError('');
  };
  return <Box sx={{ maxWidth: 1120, mx: 'auto', p: { xs: 2, md: 4 } }}>
    <Box sx={{ mb: 3 }}>
      <Typography variant="h5" sx={{ fontFamily: careFonts.serif, fontWeight: 800 }}>问诊记录</Typography>
      <Typography variant="body2" sx={{ color: carePalette.muted, mt: 0.5 }}>查看每次问诊总结，整理就诊时要带的内容和问题。</Typography>
    </Box>
    {error && <Alert severity="error" sx={{ mb: 2 }} action={<Button color="inherit" onClick={() => {
      setError(''); setRecovery(null);
      if (selectedId) { setLoadingRecovery(true); setReload(value => value + 1); }
      else { setLoadingCases(true); setLoadingRecovery(false); setListReload(value => value + 1); }
    }}>重试</Button>}>{error}</Alert>}
    {loadingCases ? <CircularProgress aria-label="加载问诊记录" /> : cases.length === 0 ? <Card><CardContent>
      <Typography sx={{ fontWeight: 700, mb: 0.75 }}>暂无问诊记录</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>完成一次 AI 问诊后，总结会出现在这里，方便下次复诊对照。</Typography>
      <Button variant="contained" onClick={() => navigate('/chat')}>开始问诊</Button>
    </CardContent></Card> : <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '280px minmax(0, 1fr)' }, gap: 2 }}>
      <Card sx={{ alignSelf: 'start' }}><List aria-label="问诊记录列表" disablePadding>
        {cases.map(item => <ListItemButton key={item.id} selected={item.id === selectedId} onClick={() => selectCase(item.id)}
          sx={{ py: 1.4, px: 2, '&.Mui-selected': { bgcolor: carePalette.primarySoft, color: carePalette.primaryDark } }}>
          <ListItemText
            primary={caseTitle(item)}
            secondary={new Date(item.created_at).toLocaleDateString('zh-CN')}
            slotProps={{ primary: { noWrap: true, sx: { fontWeight: 700, fontSize: 14 } }, secondary: { sx: { fontSize: 12 } } }}
          />
        </ListItemButton>)}
      </List></Card>
      <Card><CardContent sx={{ p: { xs: 2, md: 3 }, minHeight: 220 }}>
        {loadingRecovery ? <CircularProgress aria-label="加载问诊详情" /> : currentRecovery ? <CaseDetail key={selectedId} recovery={currentRecovery} />
          : !error && <Typography color="text.secondary">请选择一条问诊记录。</Typography>}
      </CardContent></Card>
    </Box>}
  </Box>;
}
