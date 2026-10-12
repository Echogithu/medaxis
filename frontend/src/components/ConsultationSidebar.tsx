import type { ReactNode } from 'react';
import { Box, Button, Chip, Paper, Stack, Typography } from '@mui/material';
import ChatBubbleOutlineRoundedIcon from '@mui/icons-material/ChatBubbleOutlineRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import PersonOutlineRoundedIcon from '@mui/icons-material/PersonOutlineRounded';
import type { ChatMessageItem, DiagnosisReport } from '../types/agent';
import { consultationContext } from '../state/consultationContext';
import { careFonts, carePalette, careShadows } from '../theme';

function ContextCard({ title, icon, children, warning = false, badge }: {
  title: string; icon: ReactNode; children: ReactNode; warning?: boolean; badge?: string;
}) {
  return (
    <Paper component="section" elevation={0} aria-label={title} sx={{
      p: 2.5, borderRadius: '24px', border: warning ? '1px solid #f6dedd' : 'none',
      bgcolor: warning ? '#fffafa' : '#fff', boxShadow: careShadows.card,
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Box aria-hidden="true" sx={{ display: 'grid', color: warning ? carePalette.danger : carePalette.primary, '& svg': { fontSize: 21 } }}>{icon}</Box>
        <Typography component="h2" sx={{ fontFamily: careFonts.serif, color: carePalette.ink, fontSize: 16, fontWeight: 750 }}>{title}</Typography>
        {badge && <Chip label={badge} size="small" sx={{ ml: 'auto', height: 23, fontSize: 10, bgcolor: '#fbe4e4', color: '#b14c4c' }} />}
      </Box>
      {children}
    </Paper>
  );
}

function ContextList({ items, warning = false }: { items: string[]; warning?: boolean }) {
  return (
    <Box component="ul" sx={{ p: 0, m: 0, display: 'grid', gap: 1, listStyle: 'none' }}>
      {items.map((item, index) => (
        <Box component="li" key={index} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
          <Box aria-hidden="true" sx={{ width: 6, height: 6, mt: '8px', flexShrink: 0, borderRadius: '50%', bgcolor: warning ? carePalette.danger : carePalette.primary }} />
          <Typography sx={{ color: carePalette.muted, fontSize: 12, lineHeight: 1.8, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{item}</Typography>
        </Box>
      ))}
    </Box>
  );
}

export default function ConsultationSidebar({ messages, report, onOpenReport, onRequestHelp }: {
  messages: ChatMessageItem[]; report: DiagnosisReport | null;
  onOpenReport: () => void; onRequestHelp: () => void;
}) {
  const context = consultationContext(messages, report);
  return (
    <Stack component="aside" aria-label="问诊辅助信息" spacing={1.75} sx={{ minWidth: 0 }}>
      <ContextCard title="本次问诊摘要" icon={<ChatBubbleOutlineRoundedIcon />}>
        {context.summary.length ? <>
          <Typography sx={{ mb: 1, color: carePalette.muted, fontSize: 11 }}>{context.summarySource}</Typography>
          <ContextList items={context.summary} />
          {context.hasNewInformation && <Typography role="status" sx={{ mt: 1.25, color: '#8f6a30', fontSize: 11, lineHeight: 1.8 }}>安全提示和下一步仍来自上一份总结，新补充尚未纳入评估。</Typography>}
        </> : <Typography sx={{ fontSize: 12, color: carePalette.muted, lineHeight: 1.8 }}>暂无问诊摘要</Typography>}
        {report && <Button size="small" onClick={onOpenReport} sx={{ mt: 1.25, px: 0, minHeight: 28, fontSize: 11 }}>查看完整总结与来源</Button>}
      </ContextCard>
      <ContextCard title="安全提示" icon={<WarningAmberRoundedIcon />} warning badge={context.urgent ? '需关注' : '通用提醒'}>
        <ContextList items={context.safety} warning />
      </ContextCard>
      <ContextCard title="接下来可以做什么" icon={<CheckRoundedIcon />}>
        {context.actions.length ? <ContextList items={context.actions} /> : <Typography sx={{ fontSize: 12, color: carePalette.muted, lineHeight: 1.8 }}>
          {context.summary.length ? '继续回答问诊问题，完成后查看本次建议。' : '先描述症状、持续时间，或上传检查报告。'}
        </Typography>}
      </ContextCard>
      <ContextCard title="需要专业帮助？" icon={<PersonOutlineRoundedIcon />}>
        <Box sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 1.1, borderRadius: '16px', bgcolor: carePalette.mint }}>
          <Box aria-hidden="true" sx={{ width: 36, height: 38, flexShrink: 0, display: 'grid', placeItems: 'center', borderRadius: '12px', bgcolor: '#fff', color: carePalette.primary }}><PersonOutlineRoundedIcon sx={{ fontSize: 21 }} /></Box>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography sx={{ fontSize: 12, fontWeight: 600, color: carePalette.ink }}>与真实医生交流</Typography>
          </Box>
          <Button variant="outlined" size="small" aria-label="转接真实医生" onClick={onRequestHelp} sx={{ flexShrink: 0, minWidth: 48, minHeight: 36, px: 1, borderRadius: '12px', fontSize: 12, bgcolor: '#fff', borderColor: carePalette.line }}>转接</Button>
        </Box>
      </ContextCard>
    </Stack>
  );
}
