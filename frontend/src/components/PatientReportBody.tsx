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
  high: '参考把握较高',
  medium: '参考把握一般',
  low: '参考把握有限',
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
        <Typography id={headingId} component="h3" sx={{ fontFamily: careFonts.serif, fontWeight: 700, fontSize: { xs: 16, sm: 16.5 }, letterSpacing: '-0.02em' }}>
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
          <Typography sx={{ color: carePalette.ink, fontSize: { xs: summarize ? 14 : 15.5, sm: summarize ? 14.5 : 15 }, lineHeight: 1.8, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
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
      flex: '1 1 170px',
      p: { xs: 1.35, sm: 1.5 },
      border: `1px solid ${toneStyles.border}`,
      borderRadius: '14px',
      bgcolor: toneStyles.background,
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.8, mb: 0.55, color: toneStyles.icon }}>
        <Box aria-hidden="true" sx={{ display: 'grid', placeItems: 'center', '& svg': { fontSize: 17 } }}>{icon}</Box>
        <Typography sx={{ fontSize: 12, fontWeight: 800, letterSpacing: '0.02em' }}>{label}</Typography>
      </Box>
      <Typography sx={{ color: carePalette.ink, fontSize: { xs: 15, sm: 15.5 }, lineHeight: 1.55, fontWeight: 700 }}>
        {value}
      </Typography>
      {detail && (
        <Typography sx={{ mt: 0.25, color: carePalette.muted, fontSize: 12.5, lineHeight: 1.55 }}>
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
  const disclaimer = patientText(data.disclaimer) || '本次总结由 AI 生成，用于帮助你整理情况，不能替代面诊、检查或处方。';
  const hasPriorityNotice = flags.length > 0 || referralNeeded;

  return (
    <Stack spacing={isRecord ? 2.5 : compact ? 2.25 : 2.75} sx={{ overflowWrap: 'anywhere' }}>
      {hasPriorityNotice && (
        <Box role="alert" sx={{ display: 'flex', gap: 1.25, p: { xs: 1.45, sm: 1.6 }, borderRadius: '16px', border: '1px solid #f0c9c4', bgcolor: carePalette.dangerSoft }}>
          <Box sx={{
            width: 32, height: 32, flex: '0 0 auto', display: 'grid', placeItems: 'center',
            borderRadius: '10px', color: '#fff', bgcolor: carePalette.danger,
          }}>
            <PriorityHighRoundedIcon sx={{ fontSize: 18 }} />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 800, color: '#9b1c1c', mb: 0.4 }}>需要优先注意</Typography>
            {flags.map((flag, index) => (
              <Typography key={index} variant="body2" sx={{ color: '#7a2a24', whiteSpace: 'pre-wrap' }}>
                <CitationText text={flag} anchors={citationAnchors} onNavigate={openCitationList} />
              </Typography>
            ))}
            {referralNeeded && (
              <Typography variant="body2" sx={{ mt: flags.length ? 0.5 : 0, color: '#7a2a24' }}>
                {referralReason || '请尽早就医，由医生当面评估。'}
              </Typography>
            )}
          </Box>
        </Box>
      )}

      {data.interview_is_sufficient === false && informationGaps.length > 0 && (
        <Box role="status" sx={{ p: 1.75, borderRadius: '14px', bgcolor: '#fff8ee', border: '1px solid #f0dfc3' }}>
          <Typography sx={{ fontWeight: 750, color: '#805e2b', mb: 0.5 }}>仍需确认的信息</Typography>
          <Typography variant="body2">以下信息尚未确认，请结合已有回答阅读本次建议。</Typography>
          {informationGaps.map((gap, index) => (
            <Typography key={index} variant="body2" sx={{ mt: 0.35 }}>{gap}</Typography>
          ))}
        </Box>
      )}

      {primary && (
        <Box component="section" aria-labelledby={`${citationPrefix}-primary-title`} sx={{
          p: { xs: 1.65, sm: 2.2 },
          border: '1px solid #cfe6dc',
          borderRadius: '18px',
          bgcolor: '#f1faf6',
          backgroundImage: 'linear-gradient(135deg, rgba(255,255,255,0.72), rgba(231,247,240,0.72))',
        }}>
          <Typography sx={{ color: carePalette.primaryDark, fontSize: 12, fontWeight: 800, letterSpacing: '0.08em' }}>
            {isRecord ? '本次初步参考' : '先看这里'}
          </Typography>
          <Typography id={`${citationPrefix}-primary-title`} sx={{
            mt: 0.5, fontFamily: careFonts.serif, fontWeight: 800, fontSize: { xs: 20, sm: isRecord ? 23 : compact ? 22 : 25 },
            lineHeight: 1.42, letterSpacing: '-0.03em', color: carePalette.ink,
            overflowWrap: 'anywhere',
          }}>
            <CitationText text={primary} anchors={citationAnchors} onNavigate={openCitationList} />
          </Typography>
          <Typography sx={{ mt: 0.75, color: '#4a6968', fontSize: { xs: 14, sm: 14.5 }, lineHeight: 1.65 }}>
            {isRecord ? '基于本次描述的 AI 参考，需由医生结合面诊与检查确认。' : '这是基于当前描述整理出的初步参考，不等同于确诊结果；请结合症状变化和医生面诊判断。'}
          </Typography>
          <Stack direction="row" spacing={0.8} useFlexGap sx={{ mt: 1.25, flexWrap: 'wrap' }}>
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

      {!isRecord && (actions.length > 0 || followUp || !hasPriorityNotice) && (
        <Box component="section" aria-label="快速查看" sx={{ mt: compact ? -0.35 : -0.2 }}>
          <Typography sx={{ mb: 1, color: carePalette.ink, fontSize: 15.5, fontWeight: 800 }}>
            快速查看
          </Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap>
            {actions.length > 0 && (
              <QuickReadCard
                icon={<TaskAltRoundedIcon />}
                label="下一步"
                value={`${actions.length} 项可与医生讨论`}
                detail="先按顺序查看下方建议"
                tone="positive"
              />
            )}
            {followUp && (
              <QuickReadCard
                icon={<EventNoteOutlinedIcon />}
                label="后续关注"
                value="记下变化，再带去复诊"
                detail="具体时间以医生建议为准"
              />
            )}
            {!hasPriorityNotice && (
              <QuickReadCard
                icon={<MedicalInformationOutlinedIcon />}
                label="阅读提示"
                value="请从上到下逐项阅读"
                detail="没有标记紧急事项，不代表可以忽略症状变化"
              />
            )}
          </Stack>
        </Box>
      )}

      {(findings.length > 0 || actions.length > 0) && <Box sx={{ display: 'grid', gridTemplateColumns: isRecord && findings.length > 0 && actions.length > 0 ? { xs: '1fr', lg: 'minmax(0, 1fr) minmax(0, 1fr)' } : '1fr', gap: 2.5 }}>
      {findings.length > 0 && (
        <ReportSection icon={<FavoriteBorderRoundedIcon />} title={isRecord ? '症状与发现' : '你描述的情况与本次发现'}>
          <ReportItems items={findings} label="症状要点" summarize={isRecord} renderItem={item => (
              <Box sx={{ px: { xs: 1.35, sm: 1.5 }, py: 1.15, borderRadius: '12px', bgcolor: '#f7faf8', border: '1px solid #e7eeea' }}>
                <Typography sx={{ fontSize: { xs: isRecord ? 14 : 15.5, sm: isRecord ? 14.5 : 15 }, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                  <CitationText text={item} anchors={citationAnchors} onNavigate={openCitationList} />
                </Typography>
              </Box>
            )} />
        </ReportSection>
      )}

      {actions.length > 0 && (
        <ReportSection icon={<TaskAltRoundedIcon />} title="建议下一步" hint="可与医生讨论的行动，不是已确认的治疗方案">
          <NumberedList items={actions} anchors={citationAnchors} onNavigate={openCitationList} summarize={isRecord} />
        </ReportSection>
      )}
      </Box>}

      {(tests.length > 0 || followUp) && <Box sx={{ display: 'grid', gridTemplateColumns: isRecord && tests.length > 0 && followUp ? { xs: '1fr', lg: 'minmax(0, 1fr) minmax(0, 1fr)' } : '1fr', gap: 2.5 }}>
      {tests.length > 0 && (
        <ReportSection icon={<ScienceOutlinedIcon />} title="可与医生讨论的检查" hint="是否需要检查，由接诊医生决定">
          <ReportItems items={tests} label="检查建议" summarize={isRecord} layout={isRecord ? 'stack' : 'wrap'} renderItem={item => (
              <Chip
                label={<CitationText text={item} anchors={citationAnchors} onNavigate={openCitationList} />}
                sx={{
                  maxWidth: '100%', height: 'auto', py: 0.75, px: 0.45, borderRadius: '10px', color: '#3d5a63', bgcolor: '#edf4f6',
                  fontSize: isRecord ? 13 : { xs: 14.5, sm: 14 },
                  '& .MuiChip-label': { whiteSpace: 'normal', lineHeight: 1.55 },
                }}
              />
            )} />
        </ReportSection>
      )}

      {followUp && (
        <ReportSection icon={<EventNoteOutlinedIcon />} title="后续关注">
          <Box sx={{ px: 1.5, py: 1.25, borderRadius: '14px', border: '1px dashed #d7e4df', bgcolor: '#f7fbf9' }}>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              <CitationText text={followUp} anchors={citationAnchors} onNavigate={openCitationList} />
            </Typography>
          </Box>
        </ReportSection>
      )}
      </Box>}

      {precautions.length > 0 && (
        <Box sx={isRecord ? { p: 1.75, borderRadius: '14px', bgcolor: '#fffaf2', border: '1px solid #f0e4ce' } : {}}>
          <ReportSection icon={<WarningAmberRoundedIcon />} title="需要注意的情况">
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
        <Typography variant="caption" sx={{ display: 'block', color: carePalette.muted, lineHeight: 1.7 }}>
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
            <Typography sx={{ fontWeight: 700, fontSize: 14 }}>参考资料与说明</Typography>
            {citations.length > 0 && <Chip size="small" label={`${citations.length} 条来源`} sx={{ height: 23, fontSize: 11, bgcolor: '#eef5f1', color: carePalette.primaryDark }} />}
          </Box>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 1.5, pt: 0, pb: 1.5 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {citations.length
              ? '以下为本次检索的参考资料。正文引用保留原编号，点击可查看对应原文；其余资料也可展开阅读。'
              : sources.length
                ? '这份旧报告只有模型返回的来源名称，没有绑定实际检索记录，不能作为已核验引用。'
                : retrievalStatus === 'retrieved_not_cited'
                  ? `这份历史报告记录了 ${retrievalCount} 个来源，但当前记录中缺少原文；无法恢复的来源不会补造。`
                  : retrievalStatus === 'failed'
                    ? '本次知识检索失败或超时；报告未附知识来源。'
                    : '本次检索没有返回可核验来源；报告中的医学判断未附知识库引文。'}
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
                {allCitationsExpanded ? '收起更多来源' : `展开全部参考资料（${citations.length} 条）`}
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
