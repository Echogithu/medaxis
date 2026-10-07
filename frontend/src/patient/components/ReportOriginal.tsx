import { useEffect, useState } from 'react';
import { Alert, Box, Button, CircularProgress, Stack, Typography } from '@mui/material';
import { DownloadOutlined, ZoomInOutlined, ZoomOutOutlined } from '@mui/icons-material';
import { getReportOriginal } from '../../api/reports';
import type { PatientReport } from '../../api/reports';

interface Preview { key: string; url?: string; error?: string }
export default function ReportOriginal({ report }: { report: PatientReport }) {
  const [position, setPosition] = useState(0);
  const [zoom, setZoom] = useState(100);
  const [retry, setRetry] = useState(0);
  const [preview, setPreview] = useState<Preview | null>(null);
  const file = report.files[Math.min(position, report.files.length - 1)];
  const key = `${report.id}/${file?.id}/${retry}`;
  useEffect(() => {
    if (!file) return;
    let active = true;
    let objectUrl: string | undefined;
    getReportOriginal(report.id, file.id).then(blob => {
      if (!active) return;
      objectUrl = URL.createObjectURL(blob);
      setPreview({ key, url: objectUrl });
    }).catch(error => { if (active) setPreview({ key, error: error.message }); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [report.id, file, key]);
  if (!file) return <Alert severity="warning">原件暂无可用文件</Alert>;
  const current = preview?.key === key ? preview : null;
  const next = (index: number) => { setPosition(index); setZoom(100); };
  return <Box>
    <Stack direction="row" spacing={1} sx={{ mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
      <Typography component="h2" variant="h6" sx={{ flex: 1 }}>报告原件</Typography>
      <Button disabled={!current?.url} startIcon={<DownloadOutlined />} component="a" href={current?.url} download={file.filename}>下载原件</Button>
    </Stack>
    <Typography variant="body2" sx={{ mb: 1, overflowWrap: 'anywhere' }}>{file.filename} · {file.page_count} 页</Typography>
    <Stack direction="row" spacing={1} sx={{ mb: 1, alignItems: 'center' }}>
      <Button disabled={position === 0} onClick={() => next(position - 1)}>上一个文件</Button>
      <Typography variant="body2">文件 {position + 1} / {report.file_count}</Typography>
      <Button disabled={position >= report.file_count - 1} onClick={() => next(position + 1)}>下一个文件</Button>
    </Stack>
    {!current ? <Box sx={{ height: 350, display: 'grid', placeItems: 'center' }}><CircularProgress aria-label="加载报告原件" /></Box> : current.error ?
      <Alert severity="error" action={<Button onClick={() => setRetry(value => value + 1)}>重试</Button>}>{current.error}</Alert> : <>
        {file.mime_type === 'application/pdf' ? <>
          <Typography variant="caption" sx={{ display: 'block', mb: 1 }}>可在原件阅读器中翻页、缩放；设备无法预览时请下载查看。</Typography>
          <Box component="iframe" title="PDF报告原件" src={current.url} sx={{ width: '100%', height: { xs: 480, md: 650 }, border: '1px solid #e2e8f0', borderRadius: 2, bgcolor: '#f1f5f9' }} />
        </> : <>
          <Stack direction="row" spacing={1} sx={{ mb: 1, alignItems: 'center' }}>
            <Button aria-label="缩小原件" disabled={zoom <= 50} onClick={() => setZoom(value => value - 25)}><ZoomOutOutlined /></Button>
            <Typography variant="body2">{zoom}%</Typography>
            <Button aria-label="放大原件" disabled={zoom >= 250} onClick={() => setZoom(value => value + 25)}><ZoomInOutlined /></Button>
          </Stack>
          <Box sx={{ overflow: 'auto', maxHeight: 650, borderRadius: 2, bgcolor: '#f1f5f9', border: '1px solid #e2e8f0' }}>
            <Box component="img" alt="报告原件" src={current.url} sx={{ display: 'block', width: `${zoom}%`, maxWidth: 'none' }} />
          </Box>
        </>}
      </>}
  </Box>;
}
