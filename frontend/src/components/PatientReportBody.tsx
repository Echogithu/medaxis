import type { ReactNode } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Stack,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import PriorityHighRoundedIcon from '@mui/icons-material/PriorityHighRounded';
import FavoriteBorderRoundedIcon from '@mui/icons-material/FavoriteBorderRounded';
import MedicalInformationOutlinedIcon from '@mui/icons-material/MedicalInformationOutlined';
import TaskAltRoundedIcon from '@mui/icons-material/TaskAltRounded';
import ScienceOutlinedIcon from '@mui/icons-material/ScienceOutlined';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import EventNoteOutlinedIcon from '@mui/icons-material/EventNoteOutlined';
import MenuBookOutlinedIcon from '@mui/icons-material/MenuBookOutlined';
import type { DiagnosisReport } from '../types/agent';
import { patientList, patientText } from '../state/patientText';
import { careFonts, carePalette } from '../theme';

const severityCopy: Record<string, { label: string; color: string; background: string }> = {
  mild: { label: '情况相对平稳', color: '#0c635b', background: '#e8f6f2' },
  moderate: { label: '建议尽快就诊', color: '#8f6a30', background: '#f6ecd9' },
  severe: { label: '需要尽快就医', color: '#a24d32', background: '#f8e0d2' },
  emergency: { label: '请立即就医', color: '#9b1c1c', background: '#fde8e6' },
  unknown: { label: '待医生评估', color: '#5d7477', background: '#eef2f0' },
};

const confidenceCopy: Record<string, string> = {
  high: '参考把握较高',
  medium: '参考把握一般',
  low: '参考把握有限',
};

function ReportSection({ icon, title, hint, children }: { icon: ReactNode; title: string; hint?: string; children: ReactNode }) {
  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: hint ? 0.4 : 1.1 }}>
        <Box sx={{
          width: 28, height: 28, display: 'grid', placeItems: 'center', borderRadius: '9px',
          color: carePalette.primaryDark, bgcolor: carePalette.primarySoft, '& svg': { fontSize: 16 },
        }}>
          {icon}
        </Box>
        <Typography sx={{ fontFamily: careFonts.serif, fontWeight: 700, fontSize: 15.5, letterSpacing: '-0.02em' }}>
          {title}
        </Typography>
      </Box>
      {hint && (
        <Typography variant="caption" sx={{ display: 'block', mb: 1.1, ml: { xs: 0, sm: 4.5 }, color: carePalette.muted }}>
          {hint}
        </Typography>
      )}
      <Box sx={{ pl: { xs: 0, sm: 4.5 } }}>{children}</Box>
    </Box>
  );
}

function NumberedList({ items }: { items: string[] }) {
  return (
    <Stack spacing={1}>
      {items.map((item, index) => (
        <Box key={`${item}-${index}`} sx={{ display: 'flex', gap: 1.25, alignItems: 'flex-start' }}>
          <Box sx={{
            width: 22, height: 22, flex: '0 0 auto', mt: '1px', display: 'grid', placeItems: 'center',
            borderRadius: '999px', color: carePalette.primaryDark, bgcolor: carePalette.mint, fontSize: 11, fontWeight: 800,
          }}>
            {index + 1}
          </Box>
          <Typography variant="body2" sx={{ color: carePalette.ink, whiteSpace: 'pre-wrap' }}>{item}</Typography>
        </Box>
      ))}
    </Stack>
  );
}

/** 聊天卡片、报告详情和问诊记录共用同一份患者可读内容。 */
export default function PatientReportBody({
  report,
  compact = false,
}: {
  report: DiagnosisReport | Record<string, unknown>;
  compact?: boolean;
}) {
  const data = report as unknown as Record<string, unknown>;
  const flags = patientList(data.red_flags);
  const primary = patientText(data.primary_diagnosis);
  const findings = patientList(data.key_findings);
  const actions = patientList(data.recommended_actions ?? data.treatment_suggestions);
  const tests = patientList(data.recommended_tests ?? data.recommended_exams);
  const precautions = patientList(data.contraindications);
  const followUp = patientText(data.follow_up_timeline ?? data.follow_up_plan);
  const sources = patientList(data.knowledge_sources);
  const alternatives = Array.isArray(data.differential_diagnoses) ? data.differential_diagnoses : [];
  const severity = typeof data.severity === 'string' ? data.severity : '';
  const confidence = typeof data.confidence === 'string' ? data.confidence : '';
  const severityStyle = severityCopy[severity] || null;
  const referralNeeded = data.referral_needed === true;
  const referralReason = patientText(data.referral_reason);
  const disclaimer = patientText(data.disclaimer) || '本次总结由 AI 生成，用于帮助你整理情况，不能替代面诊、检查或处方。';

  return (
    <Stack spacing={compact ? 2.25 : 2.75}>
      {(flags.length > 0 || referralNeeded) && (
        <Box sx={{ display: 'flex', gap: 1.25, p: 1.6, borderRadius: '16px', border: '1px solid #f0c9c4', bgcolor: carePalette.dangerSoft }}>
          <Box sx={{
            width: 32, height: 32, flex: '0 0 auto', display: 'grid', placeItems: 'center',
            borderRadius: '10px', color: '#fff', bgcolor: carePalette.danger,
          }}>
            <PriorityHighRoundedIcon sx={{ fontSize: 18 }} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 800, color: '#9b1c1c', mb: 0.4 }}>需要优先注意</Typography>
            {flags.map((flag, index) => (
              <Typography key={index} variant="body2" sx={{ color: '#7a2a24', whiteSpace: 'pre-wrap' }}>{flag}</Typography>
            ))}
            {referralNeeded && (
              <Typography variant="body2" sx={{ mt: flags.length ? 0.5 : 0, color: '#7a2a24' }}>
                {referralReason || '请尽早就医，由医生当面评估。'}
              </Typography>
            )}
          </Box>
        </Box>
      )}

      {primary && (
        <Box>
          <Typography variant="caption" sx={{ color: carePalette.muted, letterSpacing: '0.08em', fontWeight: 700 }}>
            可能原因
          </Typography>
          <Typography sx={{
            mt: 0.6, fontFamily: careFonts.serif, fontWeight: 700, fontSize: compact ? 22 : 26,
            lineHeight: 1.3, letterSpacing: '-0.03em', color: carePalette.ink,
          }}>
            {primary}
          </Typography>
          <Stack direction="row" spacing={0.8} useFlexGap sx={{ mt: 1.1, flexWrap: 'wrap' }}>
            {severityStyle && (
              <Chip size="small" label={severityStyle.label} sx={{ height: 26, color: severityStyle.color, bgcolor: severityStyle.background }} />
            )}
            {confidenceCopy[confidence] && (
              <Chip size="small" label={confidenceCopy[confidence]} sx={{ height: 26, color: '#3d766d', bgcolor: carePalette.primarySoft }} />
            )}
            <Chip size="small" label="AI 辅助参考" sx={{ height: 26, color: '#8a5a3a', bgcolor: carePalette.coralSoft }} />
          </Stack>
        </Box>
      )}

      {findings.length > 0 && (
        <ReportSection icon={<FavoriteBorderRoundedIcon />} title="你描述的情况与本次发现">
          <Stack spacing={0.9}>
            {findings.map((item, index) => (
              <Box key={`${item}-${index}`} sx={{ px: 1.4, py: 1.05, borderRadius: '12px', bgcolor: '#f7faf8', border: '1px solid #e7eeea' }}>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{item}</Typography>
              </Box>
            ))}
          </Stack>
        </ReportSection>
      )}

      {actions.length > 0 && (
        <ReportSection icon={<TaskAltRoundedIcon />} title="建议下一步" hint="可与医生讨论的行动，不是已确认的治疗方案">
          <NumberedList items={actions} />
        </ReportSection>
      )}

      {tests.length > 0 && (
        <ReportSection icon={<ScienceOutlinedIcon />} title="可与医生讨论的检查" hint="是否需要检查，由接诊医生决定">
          <Stack direction="row" useFlexGap sx={{ flexWrap: 'wrap', gap: 0.8 }}>
            {tests.map((item, index) => (
              <Chip
                key={`${item}-${index}`}
                label={item}
                sx={{
                  height: 'auto', py: 0.7, px: 0.4, borderRadius: '12px', color: '#3d5a63', bgcolor: '#e7f2f5',
                  '& .MuiChip-label': { whiteSpace: 'normal', lineHeight: 1.45 },
                }}
              />
            ))}
          </Stack>
        </ReportSection>
      )}

      {precautions.length > 0 && (
        <ReportSection icon={<WarningAmberRoundedIcon />} title="需要注意的情况">
          <NumberedList items={precautions} />
        </ReportSection>
      )}

      {followUp && (
        <ReportSection icon={<EventNoteOutlinedIcon />} title="后续关注">
          <Box sx={{ px: 1.5, py: 1.25, borderRadius: '14px', border: '1px dashed #d7e4df', bgcolor: '#f7fbf9' }}>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{followUp}</Typography>
          </Box>
        </ReportSection>
      )}

      {alternatives.length > 0 && (
        <Accordion disableGutters elevation={0} sx={{
          border: '1px solid #e6eeea', borderRadius: '14px !important', bgcolor: '#fcfdfc', '&::before': { display: 'none' },
        }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.5, minHeight: 48 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <MedicalInformationOutlinedIcon sx={{ fontSize: 18, color: carePalette.primary }} />
              <Typography sx={{ fontWeight: 700, fontSize: 14 }}>其他需要考虑的可能原因</Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 1.5, pt: 0, pb: 1.5 }}>
            {alternatives.map((item, index) => {
              if (!item || typeof item !== 'object') return null;
              const diagnosis = patientText((item as { diagnosis?: unknown }).diagnosis);
              const reasoning = patientText((item as { reasoning?: unknown }).reasoning);
              if (!diagnosis && !reasoning) return null;
              return (
                <Box key={index} sx={{ mb: index === alternatives.length - 1 ? 0 : 1.25, pb: index === alternatives.length - 1 ? 0 : 1.25, borderBottom: index === alternatives.length - 1 ? 0 : '1px solid #edf1ee' }}>
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>{diagnosis}</Typography>
                  {reasoning && <Typography variant="body2" color="text.secondary">{reasoning}</Typography>}
                </Box>
              );
            })}
          </AccordionDetails>
        </Accordion>
      )}

      <Box sx={{ pt: 0.5, borderTop: '1px solid #edf1ee' }}>
        <Typography variant="caption" sx={{ display: 'block', color: carePalette.muted, lineHeight: 1.7 }}>
          {disclaimer}
        </Typography>
      </Box>

      <Accordion disableGutters elevation={0} sx={{
        border: '1px solid #e6eeea', borderRadius: '14px !important', bgcolor: '#fcfdfc', '&::before': { display: 'none' },
      }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.5, minHeight: 48 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <MenuBookOutlinedIcon sx={{ fontSize: 18, color: carePalette.primary }} />
            <Typography sx={{ fontWeight: 700, fontSize: 14 }}>参考资料与说明</Typography>
          </Box>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 1.5, pt: 0, pb: 1.5 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {sources.length ? '以下为报告列出的资料名称，尚未逐条核验。' : '本次总结未附可核验的参考资料。'}
          </Typography>
          {sources.map((source, index) => (
            <Typography key={index} variant="body2" sx={{ py: 0.35 }}>{source}</Typography>
          ))}
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
