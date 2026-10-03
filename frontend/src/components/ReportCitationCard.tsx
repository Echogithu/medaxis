import { useState } from 'react';
import { Box, Button, Chip, Collapse, Stack, Typography } from '@mui/material';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import type { KnowledgeCitation, KnowledgeEvidence } from '../types/agent';
import { citationExcerptPreview, isSafeCitationUrl, evidenceMatchesExcerpt, citationEvidenceLabel, citationRelevanceLabel } from '../state/reportCitations';
import { carePalette } from '../theme';

/** 引用概览与完整原文分层；来源定位只在需要核对时展开。 */
export default function ReportCitationCard({ citation, anchorId, evidence = [] }: {
  citation: KnowledgeCitation;
  anchorId: string;
  evidence?: KnowledgeEvidence[];
}) {
  const [excerptOpen, setExcerptOpen] = useState(false);
  const isInternal = citation.source_type === 'internal';
  const hasLink = isSafeCitationUrl(citation.url);
  const excerptId = `${anchorId}-excerpt`;
  const rows = evidence.filter(row => row && row.citation_id === citation.citation_id && typeof row.claim === 'string');
  const metadata = isInternal
    ? [
      ['文档 ID', citation.document_id],
      ['内容片段', citation.chunk_index == null ? '未提供序号' : String(citation.chunk_index + 1)],
      ['片段 ID', citation.chunk_id],
      ['文档类型', citation.document_type],
    ]
    : [
      ['检索来源', citation.source_engine],
      ['平台来源规则', citation.is_trusted == null ? undefined : citation.is_trusted ? '已匹配' : '未匹配'],
    ];

  return (
    <Box component="article" id={anchorId} tabIndex={-1} aria-label={`参考资料 ${citation.citation_id}`} sx={{
      p: { xs: 1.5, sm: 1.75 }, minWidth: 0, border: '1px solid #e3ebe6', borderRadius: '14px',
      bgcolor: '#fff', scrollMarginTop: 20, outline: 'none',
      '&:focus': { borderColor: carePalette.primary, boxShadow: '0 0 0 3px rgba(23,143,130,.1)' },
    }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: 'flex-start', mb: 0.65 }}>
        <Chip size="small" label={`[${citation.citation_id}] ${isInternal ? '内部知识库' : '外部来源'}`} sx={{ flexShrink: 0, height: 24, color: carePalette.primaryDark, bgcolor: carePalette.primarySoft, fontSize: 11, fontWeight: 800 }} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography component="h4" sx={{ color: carePalette.ink, fontSize: 14, lineHeight: 1.65, fontWeight: 750, overflowWrap: 'anywhere' }}>{citation.title}</Typography>
          {!isInternal && hasLink && <Typography sx={{ mt: 0.2, fontSize: 11, color: carePalette.muted, overflowWrap: 'anywhere' }}>
            {new URL(citation.url!).hostname}
          </Typography>}
        </Box>
      </Stack>
      <Typography variant="caption" sx={{ display: 'block', color: carePalette.primaryDark }}>{citationRelevanceLabel(citation)}</Typography>
      {citation.relevance_reason && <Typography variant="caption" sx={{ display: 'block', color: carePalette.muted }}>{citation.relevance_reason}</Typography>}
      {rows.length > 0 && <Typography variant="body2" sx={{ mt: 0.65, fontSize: 12.5 }}>对应报告陈述：{citationExcerptPreview(rows[0].claim)}</Typography>}
      <Typography variant="caption" color="text.secondary">
        {citation.used_in_report === false ? '本次检索参考资料，可查看原文；未作为正文引文' : citationEvidenceLabel(rows, citation)}
      </Typography>
      <Typography sx={{ mt: 1, color: '#647b7c', fontSize: 12.5, lineHeight: 1.8, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', overflowWrap: 'anywhere' }}>
        {citationExcerptPreview(citation.excerpt)}
      </Typography>
      <Stack direction="row" spacing={1.25} useFlexGap sx={{ mt: 0.75, alignItems: 'center', flexWrap: 'wrap' }}>
        <Button size="small" aria-label={`${excerptOpen ? '收起' : '查看'} ${citation.citation_id} 原文片段`} aria-expanded={excerptOpen} aria-controls={excerptId}
          onClick={() => setExcerptOpen(value => !value)} sx={{ px: 0.5, minHeight: 32, fontSize: 12 }}>
          {excerptOpen ? '收起原文' : '查看原文片段'}
        </Button>
        {hasLink && <Button component="a" href={citation.url!} target="_blank" rel="noopener noreferrer" size="small" endIcon={<OpenInNewRoundedIcon sx={{ fontSize: '14px !important' }} />} sx={{ px: 0.5, minHeight: 32, fontSize: 12 }}>打开来源</Button>}
      </Stack>
      <Collapse in={excerptOpen}>
        <Box id={excerptId} sx={{ pt: 1 }}>
          {rows.length > 0 && <Stack spacing={0.75} role="region" aria-label={`${citation.citation_id} 逐条原文核对`} sx={{ mb: 1 }}>
            {rows.map((row, index) => <Box key={`${row.claim_path}-${index}`}>
              <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>报告陈述：{row.claim}</Typography>
              <Typography variant="caption" color="text.secondary">
                {evidenceMatchesExcerpt(row, citation) ? '原文一致，适用性仍需专业核对' : '待核对：尚不能据此认定原文支持该陈述'}
              </Typography>
              {row.reason && <Typography variant="caption" sx={{ display: 'block', color: carePalette.muted }}>核对说明：{row.reason}</Typography>}
              {evidenceMatchesExcerpt(row, citation) && <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>对应原文：{row.quote}</Typography>}
            </Box>)}
          </Stack>}
          <Typography sx={{ mb: 0.65, color: carePalette.muted, fontSize: 11 }}>检索返回的原文片段</Typography>
          <Box component="blockquote" role="region" tabIndex={0} aria-label={`${citation.citation_id} 原文片段`} sx={{
            m: 0, px: 1.5, py: 1.25, maxHeight: { xs: 280, sm: 340 }, overflowY: 'auto',
            borderLeft: '3px solid #bfdfd3', borderRadius: '0 10px 10px 0', bgcolor: '#f6faf8',
            color: carePalette.ink, fontSize: 13.5, lineHeight: 1.9, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
          }}>{citation.excerpt}</Box>
        </Box>
      </Collapse>
      <Box component="details" sx={{ mt: 0.75, color: carePalette.muted, fontSize: 11 }}>
        <Box component="summary" sx={{ cursor: 'pointer', width: 'fit-content', py: 0.5, '&:focus-visible': { outline: `2px solid ${carePalette.primary}`, outlineOffset: 3 } }}>来源详情</Box>
        <Box component="dl" sx={{ m: 0, mt: 0.75, display: 'grid', gridTemplateColumns: '78px minmax(0, 1fr)', columnGap: 1, rowGap: 0.65, p: 1.25, bgcolor: '#f8faf9', borderRadius: '10px' }}>
          {metadata.filter(([, value]) => value).map(([label, value]) => (
            <Box key={label} sx={{ display: 'contents' }}>
              <Typography component="dt" sx={{ fontSize: 11, color: carePalette.muted }}>{label}</Typography>
              <Typography component="dd" sx={{ m: 0, fontSize: 11, color: '#5d7477', overflowWrap: 'anywhere' }}>{value}</Typography>
            </Box>
          ))}
          {hasLink && <>
            <Typography component="dt" sx={{ fontSize: 11 }}>来源地址</Typography>
            <Typography component="dd" sx={{ m: 0, fontSize: 11, overflowWrap: 'anywhere' }}>{citation.url}</Typography>
          </>}
        </Box>
      </Box>
    </Box>
  );
}
