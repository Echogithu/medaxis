import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Typography } from '@mui/material';
import ExpandMoreRounded from '@mui/icons-material/ExpandMoreRounded';
import type { SharedSnapshot } from '../api/consultations';
import PatientReportBody from './PatientReportBody';
import LabReportCard from './LabReportCard';

export default function ConsultationSharedRecord({ snapshot }: { snapshot: SharedSnapshot }) {
  return <Accordion disableGutters elevation={0} sx={{ border: '1px solid #e4ece9', borderRadius: '16px !important', '&:before': { display: 'none' } }}>
    <AccordionSummary expandIcon={<ExpandMoreRounded />}><Typography sx={{ fontWeight: 650 }}>查看共享资料 · {snapshot.materials.length} 份报告</Typography></AccordionSummary>
    <AccordionDetails>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>{snapshot.case_title || '本次问诊'}</Typography>
      {snapshot.chief_complaint && <Typography variant="body2" sx={{ mb: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{snapshot.chief_complaint}</Typography>}
      {snapshot.description && <Typography variant="body2" sx={{ mb: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{snapshot.description}</Typography>}
      <Typography variant="caption" color="text.secondary">AI 整理摘要</Typography>
      {snapshot.report ? <PatientReportBody report={snapshot.report} presentation="record" /> : <Typography variant="body2" sx={{ mt: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{snapshot.ai_summary || '暂无摘要'}</Typography>}
      {snapshot.materials.map(material => <Box key={material.file_id} sx={{ mt: 2, minWidth: 0 }}>
        <Typography variant="body2" sx={{ mb: 1, overflowWrap: 'anywhere' }}>{material.filename}</Typography>
        {Array.isArray(material.result.indicators) && Number.isFinite(material.result.overall_confidence)
          ? <LabReportCard report={material.result} /> : <Alert severity="info">这份报告的解析结果暂不支持展示，请由患者补充说明。</Alert>}
      </Box>)}
    </AccordionDetails>
  </Accordion>;
}
