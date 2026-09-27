import { Box, Button, Typography } from '@mui/material';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import type { DiagnosisReport } from '../types/agent';
import PatientReportBody from './PatientReportBody';
import { careFonts, carePalette, careShadows } from '../theme';

export default function DiagnosisCard({
  report,
  onOpen,
}: {
  report: DiagnosisReport;
  onOpen?: () => void;
}) {
  return (
    <Box sx={{
      position: 'relative',
      overflow: 'hidden',
      mt: 1.25,
      px: { xs: 1.6, sm: 2.25 },
      py: { xs: 1.6, sm: 2.1 },
      border: '1px solid #e1e8e4',
      borderRadius: '22px',
      bgcolor: '#fff',
      boxShadow: careShadows.card,
      '&::before': {
        content: '""',
        position: 'absolute',
        left: 0,
        top: 0,
        bottom: 0,
        width: 5,
        background: 'linear-gradient(180deg, #178f82 0%, #e58a68 100%)',
      },
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1.75 }}>
        <Box>
          <Typography sx={{ fontFamily: careFonts.serif, fontWeight: 800, fontSize: 16.5, letterSpacing: '-0.02em' }}>
            本次问诊总结
          </Typography>
          <Typography variant="caption" sx={{ color: carePalette.muted }}>可保存后带去就诊时参考</Typography>
        </Box>
        {onOpen && (
          <Button size="small" variant="outlined" startIcon={<DescriptionOutlinedIcon />} onClick={onOpen} sx={{ minHeight: 34, borderColor: '#d5e4df', color: carePalette.primaryDark }}>
            完整查看
          </Button>
        )}
      </Box>
      <PatientReportBody report={report} compact />
    </Box>
  );
}
