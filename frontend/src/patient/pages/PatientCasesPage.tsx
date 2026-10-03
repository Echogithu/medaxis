import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button,
  Card, Chip, CircularProgress, IconButton, Stack, Tooltip, Typography,
} from '@mui/material';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import ArrowForwardIosRoundedIcon from '@mui/icons-material/ArrowForwardIosRounded';
import AssignmentOutlinedIcon from '@mui/icons-material/AssignmentOutlined';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ChildCareOutlinedIcon from '@mui/icons-material/ChildCareOutlined';
import EventNoteOutlinedIcon from '@mui/icons-material/EventNoteOutlined';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FaceOutlinedIcon from '@mui/icons-material/FaceOutlined';
import FolderOpenOutlinedIcon from '@mui/icons-material/FolderOpenOutlined';
import HealingOutlinedIcon from '@mui/icons-material/HealingOutlined';
import MedicationLiquidOutlinedIcon from '@mui/icons-material/MedicationLiquidOutlined';
import PrintOutlinedIcon from '@mui/icons-material/PrintOutlined';
import ShareOutlinedIcon from '@mui/icons-material/ShareOutlined';
import { downloadCaseMaterial, getCaseRecovery, listCases } from '../../api/patient';
import type { CaseRecovery, MedicalCase } from '../../api/patient';
import CasePreparationPanel from '../components/CasePreparationPanel';
import PostVisitFeedbackPanel from '../components/PostVisitFeedbackPanel';
import PatientReportBody from '../../components/PatientReportBody';
import LabReportCard from '../../components/LabReportCard';
import { patientText } from '../../state/patientText';
import {
  CASE_MATERIAL_POLL_INTERVAL_MS,
  initialCaseSelection,
  mergeCasePage,
  shouldPollCaseMaterials,
} from '../../state/patientCases.ts';
import { careFonts, carePalette } from '../../theme';

/* ─── constants ─── */

const statusLabels: Record<string, string> = {
  queued: '等待处理', processing: '处理中', completed: '已整理', failed: '处理失败',
};
const CASE_PAGE_SIZE = 10;

const recordStages = [
  { id: 'summary', title: '本次问诊总结', hint: '回顾病情与建议' },
  { id: 'preparation', title: '准备去就诊', hint: '整理资料与问题' },
  { id: 'visit', title: '记录就诊结果', hint: '看诊后补充记录' },
] as const;
type RecordStage = typeof recordStages[number]['id'];

/* ─── utils ─── */

function caseTitle(item: { chief_complaint?: string; title: string }): string {
  return patientText(item.chief_complaint) || patientText(item.title.replace(/^AI Diagnosis:\s*/i, '')) || '问诊记录';
}

function formatCaseDate(value: string | null | undefined, withTime = false): string {
  if (!value) return '时间未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '时间未知';
  return date.toLocaleString('zh-CN', withTime
    ? { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { year: 'numeric', month: 'numeric', day: 'numeric' });
}

function casePreview(item: MedicalCase): string {
  const preview = patientText(item.description) || patientText(item.chief_complaint) || patientText(item.diagnosis);
  return preview ? `${preview.slice(0, 42)}${preview.length > 42 ? '…' : ''}` : '暂无症状摘要';
}

function caseIcon(item: MedicalCase): string {
  const text = `${item.title} ${item.chief_complaint || ''}`;
  if (/宝宝|儿童|孩子|婴儿/.test(text)) return 'baby';
  if (/皮肤|过敏|红疹|瘙痒/.test(text)) return 'skin';
  if (/药|服药|用药|胶囊|片/.test(text)) return 'medicine';
  return 'stomach';
}

const caseTypeMeta: Record<string, { icon: React.ReactElement; css: { color: string; bg: string; border: string } }> = {
  baby: {
    icon: <ChildCareOutlinedIcon sx={{ fontSize: 18 }} />,
    css: { color: '#166b62', bg: '#e0f0ec', border: '#b8d9d0' },
  },
  skin: {
    icon: <FaceOutlinedIcon sx={{ fontSize: 18 }} />,
    css: { color: '#b97b4b', bg: '#f5ebe2', border: '#e7d5c6' },
  },
  medicine: {
    icon: <MedicationLiquidOutlinedIcon sx={{ fontSize: 18 }} />,
    css: { color: '#617bb4', bg: '#e8edf5', border: '#cad5e6' },
  },
  stomach: {
    icon: <HealingOutlinedIcon sx={{ fontSize: 18 }} />,
    css: { color: carePalette.primaryDark, bg: carePalette.primarySoft, border: '#cfe6de' },
  },
};

function CaseBadge({ type }: { type: string }) {
  const m = caseTypeMeta[type] || caseTypeMeta.stomach;
  return (
    <Box sx={{
      width: 36, height: 36, flex: '0 0 auto', display: 'grid', placeItems: 'center',
      borderRadius: '50%', color: m.css.color, bgcolor: m.css.bg, border: `1px solid ${m.css.border}`,
      transition: 'transform 180ms ease',
    }}>
      {m.icon}
    </Box>
  );
}

/* ─── CaseStepper ─── redesigned 3-stage navigation ─── */

function CaseStepper({ activeStage, onSelect }: { activeStage: RecordStage; onSelect: (s: RecordStage) => void }) {
  return (
    <Box component="nav" aria-label="问诊记录阶段" sx={{
      position: 'sticky', top: 0, zIndex: 3, mb: 2.5,
      bgcolor: 'rgba(255,255,255,0.88)', backdropFilter: 'blur(12px)',
      borderRadius: '16px', border: '1px solid #e2e8f0', p: 1.25,
      boxShadow: '0 4px 20px rgba(34,61,55,0.04)',
      '@media print': { display: 'none' },
    }}>
      <Box sx={{ display: 'flex', alignItems: 'flex-start', position: 'relative', pt: 0.5 }}>
        {recordStages.map((stage, index) => {
          const isActive = activeStage === stage.id;
          const isPast = recordStages.findIndex(s => s.id === activeStage) > index;
          const dotColor = isActive ? carePalette.primary : isPast ? carePalette.primaryDark : '#cddbd3';
          const dotSize = 26;
          return (
            <Box key={stage.id} sx={{ flex: 1, minWidth: 0, textAlign: 'center', position: 'relative' }}>
              {/* left connector half — meets previous dot exactly */}
              {index > 0 && (
                <Box aria-hidden sx={{
                  position: 'absolute', top: `${4 + dotSize / 2 - 1}px`, left: 0,
                  width: `calc(50% - ${dotSize / 2}px)`, height: 2,
                  bgcolor: isPast || isActive ? '#a8d5c8' : '#e2ebe6',
                  transition: 'background-color 200ms ease',
                }} />
              )}
              {/* right connector half — meets next dot exactly */}
              {index < recordStages.length - 1 && (
                <Box aria-hidden sx={{
                  position: 'absolute', top: `${4 + dotSize / 2 - 1}px`, right: 0,
                  width: `calc(50% - ${dotSize / 2}px)`, height: 2,
                  bgcolor: isPast ? '#a8d5c8' : '#e2ebe6',
                  transition: 'background-color 200ms ease',
                }} />
              )}
              <Box
                component="button"
                type="button"
                aria-current={isActive ? 'step' : undefined}
                aria-label={stage.title}
                onClick={() => onSelect(stage.id)}
                sx={{
                  appearance: 'none', border: 0, cursor: 'pointer', position: 'relative', zIndex: 1,
                  display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: '6px',
                  px: { xs: 0.5, sm: 1 }, py: 0.5, borderRadius: '12px', font: 'inherit',
                  bgcolor: isActive ? '#f0fdfa' : 'transparent',
                  transition: 'background-color 180ms ease',
                  '&:hover': { bgcolor: isActive ? '#ccfbf1' : '#f8fafc' },
                  '&:focus-visible': { outline: '2px solid #0d9488', outlineOffset: 2 },
                }}
              >
                {/* dot */}
                <Box aria-hidden sx={{
                  width: dotSize, height: dotSize, borderRadius: '50%', display: 'grid', placeItems: 'center',
                  fontSize: 11.5, fontWeight: 800, lineHeight: 1,
                  color: isActive || isPast ? '#fff' : '#5c7a6c',
                  bgcolor: dotColor,
                  boxShadow: isActive ? '0 2px 8px rgba(23,143,130,0.28)' : 'none',
                  transition: 'all 200ms ease',
                }}>
                  {isPast ? '✓' : index + 1}
                </Box>
                <Typography component="span" sx={{
                  fontSize: { xs: 11.5, sm: 13 }, fontWeight: isActive ? 750 : 650,
                  color: isActive ? '#0f766e' : '#64748b', lineHeight: 1.35,
                  letterSpacing: '-0.01em',
                }}>
                  {stage.title}
                </Typography>

              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}

/* ─── CaseDetail ─── */

function CaseDetail({ recovery }: { recovery: CaseRecovery }) {
  const [stageParams, setStageParams] = useSearchParams();
  const stageNavigation = useRef<HTMLElement | null>(null);
  const requestedStage = stageParams.get('stage');
  const activeStage: RecordStage = requestedStage === 'preparation' || requestedStage === 'visit' ? requestedStage : 'summary';
  const [downloadError, setDownloadError] = useState('');
  const [shareLabel, setShareLabel] = useState('分享');
  const title = caseTitle(recovery.case);

  const selectStage = (stage: RecordStage) => {
    if (stage !== activeStage) {
      const params = new URLSearchParams(stageParams);
      params.set('case_id', recovery.case.id);
      params.set('stage', stage);
      setStageParams(params);
    }
    stageNavigation.current?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };

  const shareCase = async () => {
    const shareText = `医枢问诊记录：${title}（${formatCaseDate(recovery.case.created_at)}）`;
    try {
      if (navigator.share) {
        await navigator.share({ title: '医枢问诊记录', text: shareText });
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(shareText);
        setShareLabel('已复制');
        window.setTimeout(() => setShareLabel('分享'), 1800);
      }
    } catch { /* sharing dismissed */ }
  };

  return <Stack spacing={2.5}>
    {/* ── case header ── */}
    <Box sx={{
      display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
      gap: 1.5, flexWrap: 'wrap', pb: 1,
      borderBottom: '1px solid #f1f5f9',
    }}>
      <Box sx={{ flex: '1 1 240px', minWidth: 0 }}>

        <Typography component="h2" sx={{
          fontFamily: careFonts.serif, fontWeight: 800,
          fontSize: { xs: 22, md: 26 }, lineHeight: 1.4, letterSpacing: '-0.025em',
          color: '#1e293b', overflowWrap: 'anywhere',
        }}>
          {title}
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, color: '#64748b', mt: 1.25, fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
          <EventNoteOutlinedIcon sx={{ fontSize: 15 }} />
          {formatCaseDate(recovery.case.created_at, true)}
        </Box>
      </Box>
      <Stack direction="row" spacing={0.75} sx={{ '@media print': { display: 'none' } }}>
        <Tooltip title="打印记录">
          <IconButton aria-label="打印记录" onClick={() => window.print()}
            sx={{
              width: 40, height: 40, border: '1px solid #e2ebe6',
              borderRadius: '12px', color: '#597276', bgcolor: '#fff',
              transition: 'all 150ms ease',
              '&:hover': { bgcolor: '#f8fafc', borderColor: '#cfe0d8' },
            }}>
            <PrintOutlinedIcon sx={{ fontSize: 17 }} />
          </IconButton>
        </Tooltip>
        <Button variant="outlined" startIcon={<ShareOutlinedIcon sx={{ fontSize: 16 }} />}
          onClick={() => { void shareCase(); }}
          sx={{
            minHeight: 40, borderRadius: '12px', color: '#4d6a6d',
            borderColor: '#e2ebe6', bgcolor: '#fff',
            fontWeight: 650, fontSize: 13,
            transition: 'all 150ms ease',
            '&:hover': { bgcolor: '#f8fafc', borderColor: '#cfe0d8' },
          }}>
          {shareLabel}
        </Button>
      </Stack>
    </Box>

    {/* ── stage stepper ── */}
    <CaseStepper activeStage={activeStage} onSelect={selectStage} />

    {/* ── summary ── */}
    <Box id="case-stage-summary" component="section" aria-labelledby="case-summary-title"
      sx={{ display: activeStage === 'summary' ? 'block' : 'none', '@media print': { display: 'block' } }}>
      <Box sx={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 1, mb: { xs: 1.5, sm: 2 }, pb: 1.25, borderBottom: '1px solid #f1f5f9',
      }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box sx={{
            width: 28, height: 28, display: 'grid', placeItems: 'center',
            borderRadius: '9px', color: carePalette.primaryDark,
            bgcolor: carePalette.primarySoft, '& svg': { fontSize: 16 },
          }}>
            <AssignmentOutlinedIcon />
          </Box>
          <Typography id="case-summary-title" component="h3" sx={{
            fontFamily: careFonts.serif, fontWeight: 750,
            fontSize: { xs: 15, sm: 16.5 }, letterSpacing: '-0.02em',
          }}>
            本次问诊总结
          </Typography>
        </Box>
        <Chip size="small" label="AI 辅助整理"
          sx={{
            height: 24, color: '#3d766d', bgcolor: '#f0fdfa',
            border: '1px solid #dceee6', fontSize: { xs: 10.5, sm: 11 }, fontWeight: 650,
          }} />
      </Box>
      {recovery.report
        ? <PatientReportBody report={recovery.report} presentation="record" />
        : <Alert severity="info" sx={{ borderRadius: '14px' }}>这次问诊暂无总结。</Alert>}
      <Box sx={{
        display: 'flex', justifyContent: 'flex-end', flexWrap: 'wrap', gap: 1.5, mt: 2.5, pt: 2,
        borderTop: '1px solid #f1f5f9',
      }}>
        <Button variant="contained" endIcon={<ArrowForwardIosRoundedIcon sx={{ fontSize: '13px !important' }} />}
          onClick={() => selectStage('preparation')} disabled={!recovery.report}>
          下一步：准备去就诊
        </Button>
      </Box>
    </Box>

    {/* ── preparation ── */}
    <Box id="case-stage-preparation" component="section" aria-label="准备去就诊内容"
      sx={{ display: activeStage === 'preparation' ? 'block' : 'none', '@media print': { display: 'none' } }}>
      <Typography component="h3" sx={{
        fontFamily: careFonts.serif, fontSize: 17, fontWeight: 750, mb: 1.5,
      }}>
        准备去就诊
      </Typography>
      {recovery.report
        ? <CasePreparationPanel key={recovery.case.id} caseId={recovery.case.id} />
        : <Alert severity="info" sx={{ borderRadius: '14px' }}>
            这次问诊暂无总结，暂时无法整理就诊摘要。你仍可直接记录实际就诊结果。
          </Alert>}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mt: 2, justifyContent: 'space-between' }}>
        <Button onClick={() => selectStage('summary')} sx={{ color: carePalette.primaryDark }}>返回问诊总结</Button>
        <Button variant="outlined" onClick={() => selectStage('visit')}
          sx={{ borderColor: '#d9e4df', color: '#3d6a62' }}>
          已就诊？记录就诊结果
        </Button>
      </Stack>
    </Box>

    {/* ── visit feedback ── */}
    <Box id="case-stage-visit" component="section" aria-label="记录就诊结果内容"
      sx={{ display: activeStage === 'visit' ? 'block' : 'none', '& > .MuiPaper-root': { mt: 0 }, '@media print': { display: 'none' } }}>
      <PostVisitFeedbackPanel caseId={recovery.case.id} />
      <Button sx={{ mt: 1.5, color: carePalette.primaryDark }} onClick={() => selectStage('preparation')}>
        返回就诊准备
      </Button>
    </Box>

    {/* ── materials accordion ── */}
    {recovery.materials.length > 0 && (
      <Accordion disableGutters sx={{
        border: '1px solid #e1e9e5', borderRadius: '16px !important',
        '&::before': { display: 'none' },
        boxShadow: 'none',
      }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <FolderOpenOutlinedIcon sx={{ mr: 1.25, color: carePalette.primary, fontSize: 20 }} />
          <Typography sx={{ fontWeight: 650, fontSize: 14 }}>
            上传的检查资料（{recovery.materials.length}）
          </Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0 }}>
          {downloadError && <Alert severity="error" sx={{ mb: 1.5, borderRadius: '12px' }}>{downloadError}</Alert>}
          <Stack spacing={1.25}>
            {recovery.materials.map(material => {
              const report = recovery.lab_reports.find(item => item.file_id === material.file_id);
              return <Box key={material.file_id}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography sx={{ overflowWrap: 'anywhere', fontSize: 14 }}>{material.filename}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {statusLabels[material.status] || material.status}
                    </Typography>
                  </Box>
                  <Button size="small" variant="outlined"
                    onClick={() => {
                      setDownloadError('');
                      void downloadCaseMaterial(recovery.case.id, material.file_id, material.filename)
                        .catch(() => setDownloadError('资料下载失败，请重试。'));
                    }}
                    sx={{ borderRadius: '10px', fontSize: 12.5, minHeight: 32 }}>
                    下载
                  </Button>
                </Box>
                {report && (
                  <Accordion disableGutters elevation={0} sx={{
                    mt: 1, border: '1px solid #e1e8e4', borderRadius: '12px',
                    '&::before': { display: 'none' },
                  }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Typography variant="body2" sx={{ fontWeight: 700 }}>查看解析结果</Typography>
                    </AccordionSummary>
                    <AccordionDetails sx={{ pt: 0 }}>
                      <Alert severity="info" sx={{ mb: 1.25, borderRadius: '10px' }}>
                        AI 对资料的整理仅供对照原件，不代替医生判断。
                      </Alert>
                      <LabReportCard report={report} />
                    </AccordionDetails>
                  </Accordion>
                )}
                {material.status === 'completed' && !report && (
                  <Alert severity="warning" sx={{ mt: 0.75, borderRadius: '10px' }}>
                    解析任务已完成，但这条病例没有可展示的结构化结果。请对照原始资料。
                  </Alert>
                )}
              </Box>;
            })}
          </Stack>
        </AccordionDetails>
      </Accordion>
    )}
  </Stack>;
}

/* ─── Main page ─── */

export default function PatientCasesPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedCaseId = searchParams.get('case_id');
  const [hiddenMobileCaseId, setHiddenMobileCaseId] = useState<string | null>(null);
  const mobileDetailOpen = Boolean(requestedCaseId && hiddenMobileCaseId !== requestedCaseId);
  const [cases, setCases] = useState<MedicalCase[]>([]);
  const activeCaseId = initialCaseSelection(requestedCaseId, cases);
  const [recovery, setRecovery] = useState<CaseRecovery | null>(null);
  const [loadingCases, setLoadingCases] = useState(true);
  const [loadingMoreCases, setLoadingMoreCases] = useState(false);
  const [casePage, setCasePage] = useState(1);
  const [hasMoreCases, setHasMoreCases] = useState(false);
  const [failedCasePage, setFailedCasePage] = useState<number | null>(null);
  const [listError, setListError] = useState('');
  const [detailError, setDetailError] = useState<{ caseId: string; message: string } | null>(null);
  const [materialPollPausedCaseId, setMaterialPollPausedCaseId] = useState<string | null>(null);
  const [materialPollWarningCaseId, setMaterialPollWarningCaseId] = useState<string | null>(null);
  const error = detailError?.caseId === activeCaseId ? detailError.message : '';
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listCases({ page: 1, limit: CASE_PAGE_SIZE }).then(items => {
      if (cancelled) return;
      setCases(items);
      setCasePage(1);
      setHasMoreCases(items.length === CASE_PAGE_SIZE);
      setFailedCasePage(null);
      setListError('');
    }).catch(() => {
      if (!cancelled) { setListError('问诊记录暂时无法读取，请重试。'); setFailedCasePage(1); }
    }).finally(() => { if (!cancelled) setLoadingCases(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const restoreMobileView = () => setHiddenMobileCaseId(null);
    window.addEventListener('popstate', restoreMobileView);
    return () => window.removeEventListener('popstate', restoreMobileView);
  }, []);

  const loadCasePage = async (pageToLoad: number, append: boolean) => {
    if (append) setLoadingMoreCases(true);
    else setLoadingCases(true);
    setListError('');
    try {
      const items = await listCases({ page: pageToLoad, limit: CASE_PAGE_SIZE });
      setCases(current => append ? mergeCasePage(current, items) : items);
      setCasePage(pageToLoad);
      setHasMoreCases(items.length === CASE_PAGE_SIZE);
      setFailedCasePage(null);
    } catch {
      setListError('问诊记录暂时无法读取，请重试。');
      setFailedCasePage(pageToLoad);
    } finally {
      if (append) setLoadingMoreCases(false);
      else setLoadingCases(false);
    }
  };

  useEffect(() => {
    if (!activeCaseId) return;
    let cancelled = false;
    let attempts = 0;
    let latestRecovery: CaseRecovery | null = null;
    let retryTimer: number | undefined;

    const loadRecovery = async () => {
      attempts += 1;
      try {
        const item = await getCaseRecovery(activeCaseId);
        if (cancelled) return;
        if (item.case.id !== activeCaseId) {
          setDetailError({ caseId: activeCaseId, message: '记录不匹配，请重新选择。' });
          return;
        }
        latestRecovery = item;
        setMaterialPollPausedCaseId(null);
        setMaterialPollWarningCaseId(null);
        setRecovery(item);
        setDetailError(null);
        if (shouldPollCaseMaterials(item.materials, attempts)) {
          retryTimer = window.setTimeout(() => void loadRecovery(), CASE_MATERIAL_POLL_INTERVAL_MS);
        } else if (item.materials.some(m => m.status === 'queued' || m.status === 'processing')) {
          setMaterialPollPausedCaseId(activeCaseId);
        }
      } catch (error) {
        if (cancelled) return;
        if (latestRecovery) {
          setMaterialPollWarningCaseId(activeCaseId);
          if (shouldPollCaseMaterials(latestRecovery.materials, attempts)) {
            retryTimer = window.setTimeout(() => void loadRecovery(), CASE_MATERIAL_POLL_INTERVAL_MS);
          } else if (latestRecovery.materials.some(m => m.status === 'queued' || m.status === 'processing')) {
            setMaterialPollPausedCaseId(activeCaseId);
          }
        } else {
          setDetailError({
            caseId: activeCaseId,
            message: error instanceof Error && error.message.includes('HTTP 404')
              ? '未找到属于当前账号的问诊记录。'
              : '这条问诊记录暂时无法读取，请重试。',
          });
        }
      }
    };

    void loadRecovery();
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [activeCaseId, reload]);

  const currentRecovery = recovery?.case.id === activeCaseId ? recovery : null;
  const selectCase = (id: string) => {
    if (id !== activeCaseId) { setRecovery(null); setDetailError(null); }
    setHiddenMobileCaseId(null);
    if (id === requestedCaseId) return;
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('case_id', id);
    nextParams.delete('stage');
    setSearchParams(nextParams);
  };

  const returnToCaseList = () => {
    setHiddenMobileCaseId(requestedCaseId);
    document.getElementById('patient-cases-page')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };

  const retryCaseList = () => {
    void loadCasePage(failedCasePage === 1 || failedCasePage === null ? 1 : failedCasePage, failedCasePage !== 1);
  };

  return (
    <Box id="patient-cases-page" sx={{
      maxWidth: 1440, mx: 'auto',
      p: { xs: 1.5, sm: 2.5, md: 3.5 },
      animation: 'casesFadeIn 320ms ease both',
      '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
      '@keyframes casesFadeIn': { from: { opacity: 0, transform: 'translateY(6px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
    }}>
      {/* ─── page header ─── */}
      <Box sx={{
        mb: { xs: 2, md: 3 }, pb: 2.25, borderBottom: '1px solid #e2e8f0',
        display: { xs: mobileDetailOpen ? 'none' : 'flex', md: 'flex' },
        alignItems: 'center', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap',
      }}>
        <Box>

          <Typography component="h1" sx={{
            fontFamily: careFonts.serif, fontSize: { xs: 26, md: 30 },
            color: '#1e293b', fontWeight: 700, lineHeight: 1.35, letterSpacing: '-0.025em',
          }}>
            问诊记录
          </Typography>

        </Box>
        <Button variant="contained" startIcon={<AddRoundedIcon />} onClick={() => navigate('/chat')}
          sx={{
            borderRadius: '12px', px: 2.25, minHeight: 44, flexShrink: 0,
            boxShadow: '0 4px 14px rgba(23,143,130,0.24)', fontWeight: 650,
          }}>
          发起新问诊
        </Button>
      </Box>

      {/* ─── alerts ─── */}
      {listError && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: '14px' }}
          action={<Button color="inherit" size="small" onClick={retryCaseList}>重试</Button>}>
          {listError}
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2, borderRadius: '14px' }}
          action={<Button color="inherit" size="small"
            onClick={() => { setDetailError(null); setRecovery(null); setMaterialPollPausedCaseId(null); setReload(v => v + 1); }}>
            重试
          </Button>}>
          {error}
        </Alert>
      )}
      {(materialPollPausedCaseId === activeCaseId || materialPollWarningCaseId === activeCaseId) && (
        <Alert severity="info" sx={{ mb: 2, borderRadius: '14px' }}
          action={<Button color="inherit" size="small"
            onClick={() => { setMaterialPollPausedCaseId(null); setMaterialPollWarningCaseId(null); setReload(v => v + 1); }}>
            刷新状态
          </Button>}>
          {materialPollPausedCaseId === activeCaseId
            ? '资料状态未能自动更新，或仍在处理中；自动检查已暂停。'
            : '资料状态暂时无法更新，页面保留上次结果并继续重试。'}
        </Alert>
      )}

      {/* ─── empty state ─── */}
      {loadingCases && cases.length === 0 && !activeCaseId ? (
        <CircularProgress aria-label="加载问诊记录" sx={{ display: 'block', mx: 'auto', mt: 6 }} />
      ) : cases.length === 0 && !activeCaseId && !listError ? (
        <Card sx={{
          p: { xs: 2.5, md: 3.5 }, borderRadius: '20px', textAlign: 'center',
          border: 0,
          boxShadow: '0 10px 40px -10px rgba(15,23,42,.06)',
        }}>
          <Typography sx={{ fontFamily: careFonts.serif, fontWeight: 750, fontSize: 17, mb: 0.75 }}>
            暂无问诊记录
          </Typography>

          <Button variant="contained" onClick={() => navigate('/chat')}>开始问诊</Button>
        </Card>
      ) : (
        /* ─── list + detail grid ─── */
        <Box sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '300px minmax(0, 1fr)', xl: '320px minmax(0, 1fr)' },
          alignItems: 'start', gap: { xs: 2, md: 2.5 },
        }}>
          {/* ─── case list panel ─── */}
          <Card sx={{
            overflow: 'hidden', borderRadius: '24px', bgcolor: '#fff',
            border: 0,
            boxShadow: '0 10px 40px -10px rgba(15,23,42,.06)',
            display: { xs: mobileDetailOpen ? 'none' : 'block', md: 'block' },
          }}>
            <Box sx={{
              px: 2.25, py: 2,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              borderBottom: '1px solid #f1f5f9',
            }}>
              <Typography sx={{
                fontFamily: careFonts.serif, fontWeight: 750,
                fontSize: 15, letterSpacing: '-0.02em',
              }}>
                全部记录
              </Typography>
              <Chip size="small"
                label={hasMoreCases ? `已加载 ${cases.length} 条` : `${cases.length} 条`}
                sx={{ height: 22, color: '#5f7b78', bgcolor: '#f1f5f9', fontSize: 11, fontWeight: 600 }} />
            </Box>
            <Box aria-label="问诊记录列表" component="ul" sx={{ listStyle: 'none', p: 1, m: 0 }}>
              {cases.map(item => {
                const isActive = item.id === activeCaseId;
                const iconType = caseIcon(item);
                const meta = caseTypeMeta[iconType] || caseTypeMeta.stomach;
                return (
                  <Box component="li" key={item.id} sx={{ mb: 0.5 }}>
                    <Box onClick={() => selectCase(item.id)}
                      role="button" tabIndex={0} aria-current={isActive ? 'true' : undefined}
                      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectCase(item.id); } }}
                      sx={{
                        position: 'relative', display: 'flex', gap: 1.25,
                        py: 1.6, px: 1.5,
                        borderRadius: '12px',
                        cursor: 'pointer',
                        transition: 'all 180ms ease',
                        bgcolor: isActive ? '#f0fdfa' : 'transparent',
                        border: '1px solid',
                        borderColor: isActive ? '#bfe0d6' : 'transparent',
                        boxShadow: isActive ? '0 2px 8px rgba(23,143,130,0.06)' : 'none',
                        '&:hover': { bgcolor: isActive ? '#f0fdfa' : '#f8fafc' },
                        '&:focus-visible': { outline: '2px solid #0d9488', outlineOffset: -2 },
                        overflow: 'hidden',
                      }}>
                      {/* accent strip */}
                      <Box aria-hidden sx={{
                        position: 'absolute', left: 0, top: 0, bottom: 0, width: 3,
                        bgcolor: isActive ? meta.css.color : 'transparent',
                        transition: 'background-color 200ms ease',
                        borderTopLeftRadius: 12, borderBottomLeftRadius: 12,
                      }} />
                      <CaseBadge type={iconType} />
                      <Box sx={{ minWidth: 0, flex: 1 }}>
                        <Typography sx={{
                          fontWeight: isActive ? 700 : 650,
                          fontSize: 14, lineHeight: 1.5,
                          color: isActive ? '#0a3a33' : '#2a4a4c',
                          display: '-webkit-box',
                          WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                          overflow: 'hidden', overflowWrap: 'anywhere',
                        }}>
                          {caseTitle(item)}
                        </Typography>
                        <Typography noWrap variant="caption" sx={{
                          display: 'block', mt: 0.4, color: '#6d8580', fontSize: 12,
                        }}>
                          {casePreview(item)}
                        </Typography>
                        <Typography component="time" dateTime={item.created_at || undefined}
                          sx={{
                            display: 'block', color: '#8aa099', fontSize: 11, mt: 0.75,
                            fontVariantNumeric: 'tabular-nums',
                          }}>
                          {formatCaseDate(item.created_at)}
                        </Typography>
                      </Box>
                      <ArrowForwardIosRoundedIcon sx={{
                        flex: '0 0 auto', mt: 1.1, fontSize: 12,
                        color: isActive ? meta.css.color : '#b3c1be',
                        transition: 'color 160ms ease',
                      }} />
                    </Box>
                  </Box>
                );
              })}
            </Box>
            {cases.length === 0 && activeCaseId && (
              <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                这条记录不在当前已加载的列表页中。
              </Typography>
            )}
            {loadingCases && cases.length === 0 && (
              <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
                <CircularProgress size={22} />
              </Box>
            )}
            {hasMoreCases && (
              <Box sx={{ display: 'flex', justifyContent: 'center', p: 1.25, borderTop: '1px solid #f1f5f9' }}>
                <Button size="small" disabled={loadingMoreCases}
                  onClick={() => void loadCasePage(casePage + 1, true)}
                  sx={{ fontSize: 13, color: carePalette.primaryDark }}>
                  {loadingMoreCases && <CircularProgress size={14} sx={{ mr: 0.75 }} />}
                  加载更多记录
                </Button>
              </Box>
            )}
          </Card>

          {/* ─── detail panel ─── */}
          <Box sx={{
            minWidth: 0,
            display: { xs: mobileDetailOpen ? 'block' : 'none', md: 'block' },
          }}>
            <Box sx={{
              bgcolor: '#fff', borderRadius: '24px',
              border: 0,
              boxShadow: '0 10px 40px -10px rgba(15,23,42,.06)',
              p: { xs: 1.75, sm: 2.75, md: 3.25 },
              minHeight: 220,
            }}>
              {/* mobile back button */}
              {mobileDetailOpen && (
                <Button size="small" startIcon={<ArrowBackRoundedIcon />}
                  onClick={returnToCaseList}
                  sx={{ display: { xs: 'inline-flex', md: 'none' }, mb: 1.5, color: carePalette.primaryDark }}>
                  返回问诊记录
                </Button>
              )}
              {activeCaseId && !currentRecovery && !error ? (
                <Box sx={{ display: 'grid', placeItems: 'center', minHeight: 260 }}>
                  <CircularProgress aria-label="加载问诊详情" />
                </Box>
              ) : currentRecovery ? (
                <CaseDetail key={activeCaseId} recovery={currentRecovery} />
              ) : !error && (
                <Box sx={{ display: 'grid', placeItems: 'center', minHeight: 260, textAlign: 'center' }}>
                  <Box>
                    <CheckCircleRoundedIcon sx={{ fontSize: 44, color: '#c3e0d7', mb: 1.25 }} />
                    <Typography sx={{ fontFamily: careFonts.serif, fontWeight: 700, color: '#587171', letterSpacing: '-0.02em' }}>
                      请选择一条问诊记录
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.6, color: '#91a3a1' }}>
                      在左侧查看每次问诊的详细总结
                    </Typography>
                  </Box>
                </Box>
              )}
            </Box>
          </Box>
        </Box>
      )}
    </Box>
  );
}
