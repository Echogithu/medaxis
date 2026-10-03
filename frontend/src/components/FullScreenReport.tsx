import { useRef, useState } from 'react';
import { Box, Button, Dialog, DialogContent, Fab, IconButton, Tooltip, Typography, useMediaQuery } from '@mui/material';
import KeyboardArrowUpRoundedIcon from '@mui/icons-material/KeyboardArrowUpRounded';
import CloseIcon from '@mui/icons-material/Close';
import FolderSharedOutlinedIcon from '@mui/icons-material/FolderSharedOutlined';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import MonitorHeartRoundedIcon from '@mui/icons-material/MonitorHeartRounded';
import type { DiagnosisReport } from '../types/agent';
import PatientReportBody from './PatientReportBody';
import { careFonts, carePalette, careShadows } from '../theme';

const REPORT_MAX_WIDTH = 820;

interface Props {
  report: DiagnosisReport;
  visible: boolean;
  onClose: () => void;
  caseId?: string | null;
  canOpenCase?: boolean;
  onOpenCase?: () => void;
  onSupplement?: () => void;
}

export default function FullScreenReport({ report, visible, onClose, caseId, canOpenCase, onOpenCase, onSupplement }: Props) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [showScrollTop, setShowScrollTop] = useState(false);
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const handleClose = () => { setShowScrollTop(false); onClose(); };
  if (!visible || !report) return null;
  const issuedAt = new Date();

  return (
    <Dialog
      fullScreen
      open={visible}
      onClose={handleClose}
      aria-labelledby="patient-report-title"
      slotProps={{
        paper: {
          sx: {
            bgcolor: carePalette.page,
            backgroundImage: 'radial-gradient(900px 320px at 100% -8%, rgba(23,143,130,0.08), transparent 55%), radial-gradient(700px 280px at -8% 108%, rgba(229,138,104,0.08), transparent 50%)',
          },
        },
      }}
    >
      <Box sx={{
        position: 'sticky',
        top: 0,
        zIndex: 2,
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        px: { xs: 1.5, sm: 3 },
        py: 1.25,
        borderBottom: '1px solid #e6ebe8',
        bgcolor: 'rgba(255,255,255,0.92)',
        backdropFilter: 'blur(12px)',
      }}>
        <Button startIcon={<ArrowBackRoundedIcon />} onClick={handleClose} sx={{ color: carePalette.ink }}>
          返回问诊
        </Button>
        <Typography id="patient-report-title" component="h1" sx={{ flex: 1, minWidth: 0, fontFamily: careFonts.serif, fontWeight: 700, fontSize: { xs: 16, sm: 18 } }}>
          本次问诊总结
        </Typography>
        {canOpenCase && caseId && (
          <Button variant="contained" startIcon={<FolderSharedOutlinedIcon />} onClick={onOpenCase} sx={{ display: { xs: 'none', sm: 'inline-flex' } }}>
            查看问诊记录
          </Button>
        )}
        <IconButton aria-label="关闭问诊总结" onClick={handleClose} sx={{ color: '#5d7477' }}>
          <CloseIcon />
        </IconButton>
      </Box>

      <DialogContent ref={contentRef} role="region" aria-label="问诊总结正文" tabIndex={-1}
        onScroll={event => setShowScrollTop(event.currentTarget.scrollTop > 240)}
        sx={{ px: { xs: 1.5, sm: 3 }, pt: { xs: 2.5, sm: 4 }, pb: { xs: 10, sm: 12 }, outline: 'none' }}>
        <Box component="article" aria-label="问诊总结报告" sx={{
          position: 'relative',
          maxWidth: REPORT_MAX_WIDTH,
          mx: 'auto',
          overflow: 'hidden',
          px: { xs: 2, sm: 4 },
          py: { xs: 2.5, sm: 4 },
          border: '1px solid #e1e8e4',
          borderRadius: '28px',
          bgcolor: '#fff',
          boxShadow: careShadows.paper,
          '&::before': {
            content: '""',
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: 7,
            background: 'linear-gradient(180deg, #178f82 0%, #3aa394 58%, #e58a68 100%)',
          },
        }}>
          <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 2, mb: 3, pb: 2.25, borderBottom: '1px solid #edf1ee' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
              <Box sx={{ width: 42, height: 42, display: 'grid', placeItems: 'center', borderRadius: '14px', color: '#fff', bgcolor: carePalette.primary, boxShadow: careShadows.brand }}>
                <MonitorHeartRoundedIcon />
              </Box>
              <Box>
                <Typography sx={{ fontFamily: careFonts.serif, fontWeight: 800, fontSize: 18, letterSpacing: '-0.03em' }}>
                  医枢 MedAxis
                </Typography>
                <Typography variant="caption" sx={{ color: carePalette.muted }}>患者问诊总结 · AI 辅助整理</Typography>
              </Box>
            </Box>
            <Box sx={{ textAlign: 'right' }}>
              <Typography sx={{ fontFamily: careFonts.serif, fontSize: 13, fontWeight: 700, color: '#455f63' }}>
                {issuedAt.toLocaleDateString('zh-CN')}
              </Typography>
              <Typography variant="caption" sx={{ color: '#98a3a3' }}>仅供健康参考</Typography>
            </Box>
          </Box>

          <PatientReportBody report={report} />

          {report.interview_is_sufficient === false && onSupplement && (
            <Box sx={{ mt: 2 }}>
              <Button fullWidth variant="outlined" onClick={onSupplement}>补充信息并追问</Button>
              <Typography variant="caption" component="p" sx={{ mt: 1, color: carePalette.muted }}>
                您可以补充尚未确认的信息并获取回复。本次总结会保留。
              </Typography>
            </Box>
          )}

          <Box sx={{ mt: 3.5, pt: 2, borderTop: '1px dashed #e2eae6' }}>
            {canOpenCase && caseId ? (
              <Button fullWidth variant="contained" startIcon={<FolderSharedOutlinedIcon />} onClick={onOpenCase}>
                查看问诊记录并准备就诊
              </Button>
            ) : (
              <Box sx={{ px: 1.5, py: 1.25, borderRadius: '14px', bgcolor: '#f4f8f6', border: '1px solid #e2ebe6' }}>
                <Typography variant="body2" color="text.secondary">
                  此总结尚未保存到问诊记录。登录后完成问诊，即可保存并在下次查看。
                </Typography>
              </Box>
            )}
          </Box>
        </Box>
      </DialogContent>
      {showScrollTop && <Tooltip title="回到总结顶部">
        <Fab size="small" aria-label="回到总结顶部" onClick={() => {
          contentRef.current?.scrollTo({ top: 0, behavior: reduceMotion ? 'instant' : 'smooth' });
          contentRef.current?.focus({ preventScroll: true });
        }} sx={{
          position: 'fixed',
          // 40px 按钮紧邻报告右侧，留出 16px 间距；窄屏至少保留 18px 边距。
          right: { xs: 18, md: `max(18px, calc((100% - ${REPORT_MAX_WIDTH}px) / 2 - 56px))` },
          bottom: 'calc(20px + env(safe-area-inset-bottom))', zIndex: 3, bgcolor: '#fff', color: carePalette.primary,
          border: '1px solid #dce9e3', boxShadow: '0 6px 20px rgba(34,61,55,.16)', '&:hover': { bgcolor: '#eef7f3' },
        }}>
          <KeyboardArrowUpRoundedIcon />
        </Fab>
      </Tooltip>}
    </Dialog>
  );
}
