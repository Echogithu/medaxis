import { useId, useState, type ReactNode } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
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
import type { DiagnosisReport, KnowledgeCitation } from '../types/agent';
import { patientList, patientText } from '../state/patientText';
import { isCitationId, isSafeCitationUrl, splitCitationMarkers, sortReportCitations } from '../state/reportCitations';
import { careFonts, carePalette } from '../theme';
import ReportCitationCard from './ReportCitationCard';

const severityCopy: Record<string, { label: string; color: string; background: string }> = {
  mild: { label: '情况相对平稳', color: '#0c635b', background: '#e8f6f2' },
  moderate: { label: '建议尽快就诊', color: '#8f6a30', background: '#f6ecd9' },
  severe: { label: '需要尽快就医', color: '#a24d32', background: '#f8e0d2' },
  emergency: { label: '请立即就医', color: '#9b1c1c', background: '#fde8e6' },
  unknown: { label: '待医生评估', color: '#5d7477', background: '#eef2f0' },
};

const confidenceCopy: Record<string, string> = {
  high: 'AI 对这个判断的把握：较高',
  medium: 'AI 对这个判断的把握：一般',
  low: 'AI 对这个判断的把握：有限',
};

function ReportSection({ icon, title, hint, children }: { icon: ReactNode; title: string; hint?: string; children: ReactNode }) {
  const headingId = useId();
  return (
    <Box component="section" aria-labelledby={headingId} sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: hint ? 0.4 : 1.1 }}>
        <Box sx={{
          width: 28, height: 28, display: 'grid', placeItems: 'center', borderRadius: '9px',
          color: carePalette.primaryDark, bgcolor: carePalette.primarySoft, '& svg': { fontSize: 16 },
        }}>
          {icon}
        </Box>
        <Typography id={headingId} component="h3" sx={{ fontFamily: careFonts.serif, fontWeight: 750, fontSize: { xs: 17, sm: 18 }, lineHeight: 1.5, letterSpacing: '-0.02em' }}>
          {title}
        </Typography>
      </Box>
      {hint && (
        <Typography variant="body2" sx={{ display: 'block', mb: 1.4, ml: { xs: 0, sm: 4.5 }, color: carePalette.muted, lineHeight: 1.7 }}>
          {hint}
        </Typography>
      )}
      <Box sx={{ pl: { xs: 0, sm: 4.5 } }}>{children}</Box>
    </Box>
  );
}

/** 只收起完整条目，不截断症状、数值或建议中的限定条件。 */
function ReportItems({ items, label, summarize, renderItem, layout = 'stack' }: {
  items: string[];
  label: string;
  summarize: boolean;
  renderItem: (item: string, index: number) => ReactNode;
  layout?: 'stack' | 'wrap';
}) {
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const hasMore = summarize && items.length > 3;
  return <Box>
    <Stack id={listId} direction={layout === 'wrap' ? 'row' : 'column'} useFlexGap spacing={0.9} sx={{ flexWrap: layout === 'wrap' ? 'wrap' : 'nowrap' }}>
      {items.map((item, index) => <Box key={`${item}-${index}`} sx={{
        display: hasMore && !expanded && index >= 3 ? 'none' : 'block',
        '@media print': { display: 'block' },
      }}>{renderItem(item, index)}</Box>)}
    </Stack>
    {hasMore && <Button size="small" aria-expanded={expanded} aria-controls={listId}
      onClick={() => setExpanded(value => !value)}
      sx={{ mt: 1, px: 0.5, minHeight: 36, fontSize: 12.5, '@media print': { display: 'none' } }}>
      {expanded ? `收起${label}` : `展开全部${label}（${items.length} 项）`}
    </Button>}
  </Box>;
}

function CitationText({
  text,
  anchors,
  onNavigate,
}: {
  text: string;
  anchors: Map<string, string>;
  onNavigate: (citationId: string) => void;
}) {
  return <>
    {splitCitationMarkers(text).map((part, index) => {
      if (part.type === 'text') return part.value;
      const anchor = anchors.get(part.value);
      return anchor
        ? <a key={`${part.value}-${index}`} href={`#${anchor}`} aria-label={`引用 ${part.value}，查看来源`} onClick={event => { event.preventDefault(); onNavigate(part.value); }} style={{ marginLeft: 3, color: '#166b62', fontSize: '0.78em', verticalAlign: 'super' }}>[{part.value}]</a>
        : `[${part.value}]`;
    })}
  </>;
}

function NumberedList({
  items,
  anchors,
  onNavigate,
  summarize = false,
  label = '建议',
}: {
  items: string[];
  anchors: Map<string, string>;
  onNavigate: (citationId: string) => void;
  summarize?: boolean;
  label?: string;
}) {
  return (
    <ReportItems items={items} summarize={summarize} label={label} renderItem={(item, index) => (
        <Box sx={{ display: 'flex', gap: 1.25, alignItems: 'flex-start' }}>
          <Box sx={{
            width: 22, height: 22, flex: '0 0 auto', mt: '1px', display: 'grid', placeItems: 'center',
            borderRadius: '999px', color: carePalette.primaryDark, bgcolor: carePalette.mint, fontSize: 11, fontWeight: 800,
          }}>
            {index + 1}
          </Box>
          <Typography sx={{ color: carePalette.ink, fontSize: { xs: 15, sm: 15.5 }, lineHeight: 1.8, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
            <CitationText text={item} anchors={anchors} onNavigate={onNavigate} />
          </Typography>
        </Box>
      )} />
  );
}

function QuickReadCard({
  icon,
  label,
  value,
  detail,
  tone = 'neutral',
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail?: string;
  tone?: 'neutral' | 'warning' | 'positive';
}) {
  const toneStyles = {
    neutral: { background: '#f7faf8', border: '#e2ece7', icon: carePalette.primaryDark },
    warning: { background: '#fff8ee', border: '#f0dfc3', icon: '#996b2f' },
    positive: { background: '#eef8f4', border: '#d4ebe1', icon: '#23786b' },
  }[tone];

  return (
    <Box sx={{
      minWidth: 0,
      flex: { xs: '0 1 auto', sm: '1 1 0' },
      p: { xs: 1.35, sm: 1.5 },
      border: `1px solid ${toneStyles.border}`,
      borderRadius: '14px',
      bgcolor: toneStyles.background,
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.8, mb: 0.55, color: toneStyles.icon }}>
        <Box aria-hidden="true" sx={{ display: 'grid', placeItems: 'center', '& svg': { fontSize: 17 } }}>{icon}</Box>
        <Typography sx={{ fontSize: 12, fontWeight: 800, letterSpacing: '0.02em' }}>{label}</Typography>
      </Box>
      <Typography sx={{ color: carePalette.ink, fontSize: tone === 'positive' ? 15.5 : 14, lineHeight: 1.6, fontWeight: tone === 'positive' ? 750 : 600 }}>
        {value}
      </Typography>
      {detail && (
        <Typography sx={{ mt: 0.4, color: carePalette.muted, fontSize: 13, lineHeight: 1.65 }}>
          {detail}
        </Typography>
      )}
    </Box>
  );
}

/** 聊天卡片、报告详情和问诊记录共用同一份患者可读内容。 */
export default function PatientReportBody({
  report,
  compact = false,
  presentation = 'full',
}: {
  report: DiagnosisReport | Record<string, unknown>;
  compact?: boolean;
  presentation?: 'full' | 'record';
}) {
  const isRecord = presentation === 'record';
  const data = report as unknown as Record<string, unknown>;
  const flags = patientList(data.red_flags);
  const primary = patientText(data.primary_diagnosis);
  const findings = patientList(data.key_findings);
  const actions = patientList(data.recommended_actions ?? data.treatment_suggestions);
  const tests = patientList(data.recommended_tests ?? data.recommended_exams);
  const precautions = patientList(data.contraindications);
  const followUp = patientText(data.follow_up_timeline ?? data.follow_up_plan);
  const sources = patientList(data.knowledge_sources);
  const informationGaps = patientList(data.interview_information_gaps);
  const retrievalStatus = typeof data.knowledge_retrieval_status === 'string'
    ? data.knowledge_retrieval_status
    : '';
  const retrievalCount = typeof data.knowledge_retrieval_count === 'number'
    ? data.knowledge_retrieval_count
    : 0;
  const citationPrefix = `patient-report-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const citations = sortReportCitations((Array.isArray(data.knowledge_citations) ? data.knowledge_citations : [])
    .filter((value): value is KnowledgeCitation => {
      if (!value || typeof value !== 'object') return false;
      const citation = value as Partial<KnowledgeCitation>;
      if (!isCitationId(citation.citation_id) || typeof citation.title !== 'string' || !citation.title.trim()
        || typeof citation.excerpt !== 'string' || !citation.excerpt.trim()) return false;
      if (citation.source_type === 'internal') return Boolean(citation.document_id && citation.chunk_id);
      return citation.source_type === 'external' && isSafeCitationUrl(citation.url);
    }));
  const citationAnchors = new Map(
    citations.map(citation => [citation.citation_id, `${citationPrefix}-${citation.citation_id}`]),
  );
  const [citationsExpanded, setCitationsExpanded] = useState(false);
  const [allCitationsExpanded, setAllCitationsExpanded] = useState(false);
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(null);
  const scrollToCitation = (citationId: string) => {
    const anchor = citationAnchors.get(citationId);
    if (!anchor) return;
    const node = document.getElementById(anchor);
    node?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    node?.focus({ preventScroll: true });
  };
  const openCitationList = (citationId: string) => {
    setSelectedCitationId(citationId);
    if (citations.findIndex(citation => citation.citation_id === citationId) >= 3) setAllCitationsExpanded(true);
    setCitationsExpanded(true);
    // 已打开时无需等待展开动画；下一帧确保隐藏的来源已进入布局。
    if (citationsExpanded) requestAnimationFrame(() => scrollToCitation(citationId));
  };
  const alternatives = Array.isArray(data.differential_diagnoses) ? data.differential_diagnoses : [];
  const severity = typeof data.severity === 'string' ? data.severity : '';
  const confidence = typeof data.confidence === 'string' ? data.confidence : '';
  const severityStyle = severityCopy[severity] || null;
  const referralNeeded = data.referral_needed === true;
  const referralReason = patientText(data.referral_reason);
  const disclaimer = patientText(data.disclaimer) || 'AI 帮你整理了这次问诊的情况。这份总结不能代替医生当面问诊、检查或开药。';
  const hasPriorityNotice = flags.length > 0 || referralNeeded;

  return (
    <Stack spacing={isRecord ? 2.5 : compact ? 2.25 : 2.75} sx={{ overflowWrap: 'anywhere' }}>
      {primary && (
        <Box component="section" aria-labelledby={`${citationPrefix}-primary-title`} sx={{
          p: { xs: 1.65, sm: 2.2 },
          border: '1px solid #cfe6dc',
          borderRadius: '18px',
          bgcolor: '#f1faf6',
          backgroundImage: 'linear-gradient(135deg, rgba(255,255,255,0.72), rgba(231,247,240,0.72))',
        }}>
          <Typography sx={{ color: carePalette.primaryDark, fontSize: 14, fontWeight: 750 }}>
            可能是什么问题
          </Typography>
          <Typography id={`${citationPrefix}-primary-title`} sx={{
            mt: 0.5, fontFamily: careFonts.serif, fontWeight: 800, fontSize: { xs: 20, sm: isRecord ? 23 : compact ? 22 : 25 },
            lineHeight: 1.42, letterSpacing: '-0.03em', color: carePalette.ink,
            overflowWrap: 'anywhere',
          }}>
            <CitationText text={primary} anchors={citationAnchors} onNavigate={openCitationList} />
          </Typography>
          <Typography sx={{ mt: 0.75, color: '#4a6968', fontSize: { xs: 14, sm: 14.5 }, lineHeight: 1.65 }}>
            {isRecord ? '这是 AI 根据你描述的情况作出的初步判断，不是确诊。还需医生结合当面问诊和检查确认。' : '这是 AI 根据你描述的情况作出的初步判断，不是确诊。请留意症状变化，具体情况还需医生当面判断。'}
          </Typography>
          <Stack direction="row" spacing={0.8} useFlexGap sx={{ mt: 1.25, flexWrap: 'wrap', '& .MuiChip-root': { maxWidth: '100%', height: 'auto', minHeight: 28 }, '& .MuiChip-label': { whiteSpace: 'normal', py: 0.4, lineHeight: 1.5 } }}>
            {severityStyle && (
              <Chip size="small" label={severityStyle.label} sx={{ height: 28, color: severityStyle.color, bgcolor: severityStyle.background }} />
            )}
            {confidenceCopy[confidence] && (
              <Chip size="small" label={confidenceCopy[confidence]} sx={{ height: 28, color: '#3d766d', bgcolor: carePalette.primarySoft }} />
            )}
            <Chip size="small" label="AI 辅助参考" sx={{ height: 28, color: '#8a5a3a', bgcolor: carePalette.coralSoft }} />
          </Stack>
        </Box>
      )}

      {data.interview_is_sufficient === false && informationGaps.length > 0 && (
        <Box role="status" sx={{ p: 1.75, borderRadius: '14px', bgcolor: '#fff8ee', border: '1px solid #f0dfc3' }}>
          <Typography sx={{ fontWeight: 750, color: '#805e2b', mb: 0.5 }}>还有这些情况没确认</Typography>
          <Typography variant="body2">下面这些情况还没确认。这次建议只依据目前已了解的信息。</Typography>
          {informationGaps.map((gap, index) => (
            <Typography key={index} variant="body2" sx={{ mt: 0.35 }}>{gap}</Typography>
          ))}
        </Box>
      )}

      {!isRecord && (actions.length > 0 || followUp || !hasPriorityNotice) && (
        <Box component="section" aria-label="一眼看重点" sx={{ mt: compact ? -0.35 : -0.2 }}>
          <Typography sx={{ mb: 1, color: carePalette.ink, fontSize: 15.5, fontWeight: 800 }}>
            一眼看重点
          </Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap>
            {actions.length > 0 && (
              <QuickReadCard
                icon={<TaskAltRoundedIcon />}
                label="下一步"
                value={`有 ${actions.length} 件事可以和医生讨论`}
                detail="按顺序看看下面的建议"
                tone="positive"
              />
            )}
            {followUp && (
              <QuickReadCard
                icon={<EventNoteOutlinedIcon />}
                label="接下来要留意什么"
                value="记下身体变化，再次就诊时告诉医生"
                detail="什么时候再去看医生，以医生建议为准"
              />
            )}
            {!hasPriorityNotice && (
              <QuickReadCard
                icon={<MedicalInformationOutlinedIcon />}
                label="阅读提示"
                value="请从上到下逐项阅读"
                detail="即使没有紧急提醒，也要留意症状变化。"
              />
            )}
          </Stack>
        </Box>
      )}

      {(findings.length > 0 || actions.length > 0) && <Box sx={{ display: 'grid', gridTemplateColumns: isRecord && findings.length > 0 && actions.length > 0 ? { xs: '1fr', lg: 'minmax(0, 1fr) minmax(0, 1fr)' } : '1fr', gap: 2.5 }}>
      {actions.length > 0 && (
        <ReportSection icon={<TaskAltRoundedIcon />} title="接下来可以做什么" hint="这些建议可以和医生讨论，不能当作已经确定的治疗安排。">
          <NumberedList items={actions} anchors={citationAnchors} onNavigate={openCitationList} summarize={isRecord} />
        </ReportSection>
      )}
      {findings.length > 0 && (
        <ReportSection icon={<FavoriteBorderRoundedIcon />} title="这次了解到的情况">
          <ReportItems items={findings} label="症状要点" summarize={isRecord} renderItem={item => (
              <Box sx={{ px: { xs: 1.35, sm: 1.5 }, py: 1.15, borderRadius: '12px', bgcolor: '#f7faf8', border: '1px solid #e7eeea' }}>
                <Typography sx={{ fontSize: { xs: 15, sm: 15.5 }, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                  <CitationText text={item} anchors={citationAnchors} onNavigate={openCitationList} />
                </Typography>
              </Box>
            )} />
        </ReportSection>
      )}

      </Box>}

      {(tests.length > 0 || followUp) && <Box sx={{ display: 'grid', gridTemplateColumns: isRecord && tests.length > 0 && followUp ? { xs: '1fr', lg: 'minmax(0, 1fr) minmax(0, 1fr)' } : '1fr', gap: 2.5 }}>
      {tests.length > 0 && (
        <ReportSection icon={<ScienceOutlinedIcon />} title="可以和医生讨论哪些检查" hint="要不要做这些检查，由接诊医生决定。">
          <ReportItems items={tests} label="检查建议" summarize={isRecord} layout={isRecord ? 'stack' : 'wrap'} renderItem={item => (
              <Chip
                label={<CitationText text={item} anchors={citationAnchors} onNavigate={openCitationList} />}
                sx={{
                  maxWidth: '100%', height: 'auto', py: 0.75, px: 0.45, borderRadius: '10px', color: '#3d5a63', bgcolor: '#edf4f6',
                  fontSize: 14.5,
                  '& .MuiChip-label': { whiteSpace: 'normal', lineHeight: 1.55 },
                }}
              />
            )} />
        </ReportSection>
      )}

      {followUp && (
        <ReportSection icon={<EventNoteOutlinedIcon />} title="接下来要留意什么">
          <Box sx={{ px: 1.5, py: 1.25, borderRadius: '14px', border: '1px dashed #d7e4df', bgcolor: '#f7fbf9' }}>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              <CitationText text={followUp} anchors={citationAnchors} onNavigate={openCitationList} />
            </Typography>
          </Box>
        </ReportSection>
      )}
      </Box>}

      {hasPriorityNotice && (
        <Box role="alert" sx={{ display: 'flex', gap: 1.25, p: { xs: 1.45, sm: 1.6 }, borderRadius: '16px', border: '1px solid #f0c9c4', bgcolor: carePalette.dangerSoft }}>
          <Box sx={{
            width: 32, height: 32, flex: '0 0 auto', display: 'grid', placeItems: 'center',
            borderRadius: '10px', color: '#fff', bgcolor: carePalette.danger,
          }}>
            <PriorityHighRoundedIcon sx={{ fontSize: 18 }} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 800, color: '#9b1c1c', mb: 0.4 }}>请先注意这些情况</Typography>
            {flags.map((flag, index) => (
              <Typography key={index} variant="body2" sx={{ color: '#7a2a24', whiteSpace: 'pre-wrap' }}>
                <CitationText text={flag} anchors={citationAnchors} onNavigate={openCitationList} />
              </Typography>
            ))}
            {referralNeeded && (
              <Typography variant="body2" sx={{ mt: flags.length ? 0.5 : 0, color: '#7a2a24' }}>
                {referralReason || '请尽早就医，让医生当面判断你的情况。'}
              </Typography>
            )}
          </Box>
        </Box>
      )}

      {precautions.length > 0 && (
        <Box sx={isRecord ? { p: 1.75, borderRadius: '14px', bgcolor: '#fffaf2', border: '1px solid #f0e4ce' } : {}}>
          <ReportSection icon={<WarningAmberRoundedIcon />} title="还要注意什么">
            <NumberedList items={precautions} anchors={citationAnchors} onNavigate={openCitationList} />
          </ReportSection>
        </Box>
      )}

      {alternatives.length > 0 && (
        <Accordion disableGutters elevation={0} sx={{
          border: '1px solid #e6eeea', borderRadius: '14px !important', bgcolor: '#fcfdfc', '&::before': { display: 'none' },
        }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.5, minHeight: 48 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <MedicalInformationOutlinedIcon sx={{ fontSize: 18, color: carePalette.primary }} />
              <Typography sx={{ fontWeight: 700, fontSize: 14 }}>还可能有哪些原因</Typography>
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
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                    <CitationText text={diagnosis} anchors={citationAnchors} onNavigate={openCitationList} />
                  </Typography>
                  {reasoning && (
                    <Typography variant="body2" color="text.secondary">
                      <CitationText text={reasoning} anchors={citationAnchors} onNavigate={openCitationList} />
                    </Typography>
                  )}
                </Box>
              );
            })}
          </AccordionDetails>
        </Accordion>
      )}

      <Box sx={{ pt: 0.5, borderTop: '1px solid #edf1ee' }}>
        <Typography variant="body2" sx={{ display: 'block', color: carePalette.muted, lineHeight: 1.7 }}>
          {disclaimer}
        </Typography>
      </Box>

      <Accordion
        expanded={citationsExpanded}
        onChange={(_, expanded) => { setSelectedCitationId(null); setCitationsExpanded(expanded); }}
        slotProps={{ transition: { onEntered: () => { if (selectedCitationId) scrollToCitation(selectedCitationId); } } }}
        disableGutters
        elevation={0}
        sx={{
        border: '1px solid #e6eeea', borderRadius: '14px !important', bgcolor: '#fcfdfc', '&::before': { display: 'none' },
      }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.5, minHeight: 48 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <MenuBookOutlinedIcon sx={{ fontSize: 18, color: carePalette.primary }} />
            <Typography sx={{ fontWeight: 700, fontSize: 14 }}>参考资料</Typography>
            {citations.length > 0 && <Chip size="small" label={`${citations.length} 份资料`} sx={{ height: 23, fontSize: 11, bgcolor: '#eef5f1', color: carePalette.primaryDark }} />}
          </Box>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 1.5, pt: 0, pb: 1.5 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {citations.length
              ? '这些是这次查到的参考资料。点击正文中的编号可查看对应原文，也可以展开其他资料。'
              : sources.length
                ? '这份旧总结只留有 AI 提供的资料名称，没有对应的查找记录，无法核对来源。'
                : retrievalStatus === 'retrieved_not_cited'
                  ? `这份旧总结记录了 ${retrievalCount} 份资料，但原文缺失，无法核对。找不回的资料不会补写。`
                  : retrievalStatus === 'failed'
                    ? '这次查找参考资料失败或超时，总结中没有附上资料来源。'
                    : '这次没有找到能核对的参考资料，因此没有附上支持医学判断的资料原文。'}
          </Typography>
          {citations.length > 0 ? (
            <Box>
              <Stack spacing={1}>
                {citations.map((citation, index) => (
                  <Box key={citation.citation_id} sx={{ display: index >= 3 && !allCitationsExpanded ? 'none' : 'block' }}>
                    <ReportCitationCard citation={citation} anchorId={citationAnchors.get(citation.citation_id)!} evidence={Array.isArray(data.knowledge_evidence) ? data.knowledge_evidence : []} />
                  </Box>
                ))}
              </Stack>
              {citations.length > 3 && <Button size="small" aria-expanded={allCitationsExpanded} onClick={() => setAllCitationsExpanded(value => !value)} sx={{ mt: 1, fontSize: 12 }}>
                {allCitationsExpanded ? '收起更多资料' : `展开全部参考资料（${citations.length} 份）`}
              </Button>}
            </Box>
          ) : (
            sources.map((source, index) => (
              <Typography key={index} variant="body2" sx={{ py: 0.35 }}>{source}</Typography>
            ))
          )}
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
