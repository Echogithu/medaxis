import { useEffect, useState } from 'react';
import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControlLabel, LinearProgress, Stack, TextField, Typography } from '@mui/material';
import { cancelReportJob, extractReportText, getReportWorkspace, organizeReportText, previewReportText, ReportError } from '../../api/reports';
import type { PatientReport, ReportJob, ReportPreview, ReportWorkspace } from '../../api/reports';
import { emptyReportApproval, mergeReportTextEditor, newerWorkspace, reportPreviewKey, updateReportApproval } from '../../state/reportWorkflow';
import type { ReportTextEditor } from '../../state/reportWorkflow';

const active = (job: ReportJob | null) => job && ['queued', 'processing'].includes(job.status);
const statusLabel: Record<string, string> = { queued: '等待处理', processing: '正在处理', completed: '已完成', failed: '处理失败', cancelled: '已取消' };
function sourceLocation(report: PatientReport, page: number) {
  let remaining = page;
  for (const file of report.files) {
    if (remaining <= file.page_count) return `原件文件 ${file.position + 1}，第 ${remaining} 页`;
    remaining -= file.page_count;
  }
  return `原件第 ${page} 页`;
}

export default function ReportProcessingPanel({ report }: { report: PatientReport }) {
  const [workspace, setWorkspace] = useState<ReportWorkspace | null>(null);
  const [editor, setEditor] = useState<ReportTextEditor>({ pages: [], modified: false, workspace: null });
  const { pages, modified } = editor;
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [approval, setApproval] = useState(emptyReportApproval);
  const previewKey = reportPreviewKey(workspace?.preview);
  const consent = !!previewKey && approval.previewKey === previewKey && approval.consent;
  const ownership = !!previewKey && approval.previewKey === previewKey && approval.ownership;
  function clearApproval() { setApproval(emptyReportApproval()); }
  function setConsent(checked: boolean) { setApproval(current => updateReportApproval(current, previewKey, 'consent', checked)); }
  function setOwnership(checked: boolean) { setApproval(current => updateReportApproval(current, previewKey, 'ownership', checked)); }
  const [uncertain, setUncertain] = useState<'extract' | 'ai' | null>(null);
  const [extractRequest, setExtractRequest] = useState<{ id: string; workspace: ReportWorkspace } | null>(null);
  const [aiRequest, setAIRequest] = useState<{ id: string; preview: ReportPreview } | null>(null);

  function accept(value: ReportWorkspace, replacePages = false) {
    setWorkspace(current => newerWorkspace(current, value));
    setEditor(current => mergeReportTextEditor(current, value, report.page_count, replacePages));
    if (extractRequest && value.extract_job?.request_id === extractRequest.id) {
      setExtractRequest(null); setUncertain(null);
    }
    if (aiRequest && value.ai_job?.request_id === aiRequest.id) {
      setAIRequest(null); setUncertain(null); clearApproval(); setOpen(false);
    }
  }

  useEffect(() => {
    let live = true;
    getReportWorkspace(report.id).then(value => {
      if (!live) return;
      setWorkspace(current => newerWorkspace(current, value));
      setEditor(current => mergeReportTextEditor(current, value, report.page_count));
      setApproval(emptyReportApproval()); setError('');
    }).catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [report.id, report.category, report.source_version, report.page_count]);

  const processing = !!workspace && !!(active(workspace.extract_job) || active(workspace.ai_job));
  useEffect(() => {
    if (!processing) return;
    let live = true, fetching = false;
    const timer = window.setInterval(async () => {
      if (fetching) return;
      fetching = true;
      try {
        const value = await getReportWorkspace(report.id);
        if (live) {
          setWorkspace(current => newerWorkspace(current, value));
          setEditor(current => mergeReportTextEditor(current, value, report.page_count));
          setError('');
        }
      } catch (failure) { if (live) setError(`获取进度失败：${(failure as Error).message}。任务状态未改变，可刷新进度。`); }
      finally { fetching = false; }
    }, 3000);
    return () => { live = false; window.clearInterval(timer); };
  }, [processing, report.id, report.page_count]);

  async function refresh() {
    try { accept(await getReportWorkspace(report.id)); setError(''); }
    catch (failure) { setError((failure as Error).message); }
  }
  function edit(index: number, text: string) {
    setEditor(current => ({ ...current, pages: current.pages.map((item, position) => position === index ? { ...item, text } : item), modified: true }));
    clearApproval();
  }
  async function extract() {
    if (!workspace) return;
    setBusy(true); setError(''); setNotice('');
    const request = extractRequest || { id: crypto.randomUUID(), workspace };
    setExtractRequest(request);
    try {
      const result = await extractReportText(report.id, request.workspace, request.id);
      setExtractRequest(null); setUncertain(null); accept(result.workspace);
      setNotice('本地识别任务已保存，刷新后可继续查看进度。');
    } catch (failure) {
      const known = failure instanceof ReportError && failure.status >= 400 && failure.status < 500;
      if (known) { setExtractRequest(null); setUncertain(null); } else setUncertain('extract');
      setError((failure as Error).message);
    } finally { setBusy(false); }
  }
  async function prepare() {
    if (!workspace) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await previewReportText(report.id, workspace, pages);
      accept(result.workspace, true); clearApproval(); setOpen(true);
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function organize() {
    if (!workspace?.preview || !consent || !ownership || modified) return;
    setBusy(true); setError(''); setNotice('');
    const request = aiRequest || { id: crypto.randomUUID(), preview: workspace.preview };
    setAIRequest(request);
    try {
      const result = await organizeReportText(report.id, request.preview, request.id, true, true);
      setAIRequest(null); setUncertain(null); accept(result.workspace);
      clearApproval(); setOpen(false); setNotice('本次整理已提交，结果保存为待核对候选。');
    } catch (failure) {
      const known = failure instanceof ReportError && failure.status >= 400 && failure.status < 500;
      if (known) { setAIRequest(null); setUncertain(null); } else setUncertain('ai');
      setError((failure as Error).message);
    } finally { setBusy(false); }
  }
  async function cancelById(jobId: string) {
    setBusy(true); setError('');
    try {
      const result = await cancelReportJob(report.id, jobId); accept(result.workspace);
      setNotice(result.message || '任务已取消'); clearApproval();
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  const candidate = workspace?.ai_job?.status === 'completed' ? workspace.ai_job.result : null;
  const preview = workspace?.preview;
  return <Box component="section" sx={{ mt: 3, minWidth: 0 }}>
    <Divider sx={{ mb: 3 }} />
    <Typography component="h2" variant="h6" sx={{ mb: 1 }}>整理报告</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>原件保存到平台，在平台内识别文字。AI 只接收本次确认的脱敏文字；识别失败可对照原件手动录入。</Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }} action={<Button onClick={refresh}>刷新进度</Button>}>{error} 本页文字仍保留。</Alert>}
    {notice && <Alert severity="info" sx={{ mb: 2 }}>{notice}</Alert>}
    {uncertain && <Alert severity="warning" sx={{ mb: 2 }}>提交结果尚未确认，请刷新进度或使用原编号重试。离开页面后可从已保存任务查看结果。</Alert>}
    <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', mb: 2 }}>
      <Button variant="outlined" disabled={busy || processing || modified || uncertain === 'ai'} onClick={extract}>{uncertain === 'extract' ? '使用原编号重试识别' : '本地识别文字'}</Button>
      <Button disabled={busy} onClick={refresh}>刷新进度</Button>
    </Stack>
    {modified && <Typography variant="caption" color="text.secondary">本页文字有未保存修改；先生成预览保存修改后再重新识别，刷新页面会丢失未保存填写。</Typography>}
    {workspace && [workspace.extract_job, workspace.ai_job].filter((job): job is ReportJob => !!job).map(job => <Box key={job.id} sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="body2">{job.kind === 'extract' ? '本地识别' : 'AI 整理'}：{statusLabel[job.status] || job.status}</Typography>
        {active(job) && <Button disabled={busy} onClick={() => cancelById(job.id)}>取消{job.kind === 'extract' ? '识别' : '整理'}</Button>}
      </Stack>
      {active(job) && <LinearProgress sx={{ mt: 1 }} />}
      {job.status === 'queued' && <Typography variant="caption">任务已保存，正在等待处理。刷新页面不会重新提交。</Typography>}
      {job.error_message && <Alert severity="warning" sx={{ mt: 1 }}>{job.error_message}</Alert>}
      {job.kind === 'extract' && job.result?.needs_manual_entry && <Alert severity="info" sx={{ mt: 1 }}>未识别到可用文字，请对照原件逐页填写。</Alert>}
    </Box>)}
    {workspace && <>
      <Typography component="h3" variant="subtitle1" sx={{ mb: 1 }}>逐页文字</Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>可修正识别错误、删除姓名和编号。生成预览时会再次遮蔽可识别身份；请仍自行检查是否有遗漏。</Typography>
      <Stack spacing={2}>{pages.map((page, index) => <TextField key={page.page} label={`第 ${page.page} 页文字`} multiline minRows={3} maxRows={12}
        value={page.text} disabled={busy || processing || !!uncertain} onChange={event => edit(index, event.target.value)}
        helperText={sourceLocation(report, page.page)} slotProps={{ htmlInput: { maxLength: 60000 } }} />)}</Stack>
      <Button variant="contained" onClick={prepare} disabled={busy || processing || !!uncertain} sx={{ mt: 2 }}>生成脱敏预览</Button>
      {preview && !modified && !preview.consumed_by && <Button sx={{ mt: 2 }} disabled={busy || processing} onClick={() => { clearApproval(); setOpen(true); }}>查看已保存预览</Button>}
      {uncertain === 'ai' && <Button sx={{ mt: 2 }} onClick={() => setOpen(true)}>继续确认原提交</Button>}
    </>}
    {candidate && <Box sx={{ mt: 3 }}>
      <Typography component="h3" variant="subtitle1">AI 整理结果 · 待本人核对</Typography>
      <Alert severity="info" sx={{ my: 2 }}>依据来自本次同意发送的文字，仍可能存在识别或配对错误，请逐项对照原件。患者核对不等于医生审核。</Alert>
      {preview && candidate.preview_hash !== preview.hash && <Alert severity="warning" sx={{ mb: 2 }}>这是此前预览的整理结果。当前文字已更新，需重新预览并同意后再整理。</Alert>}
      {candidate.needs_manual_entry && <Alert severity="warning">没有可核对的结构化结果，请对照原件人工录入。</Alert>}
      {candidate.indicators?.map((item, index) => <Box key={index} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2, mb: 1.5 }}>
        <Typography sx={{ fontWeight: 600 }}>{item.name}：{item.raw_value}</Typography>
        <Typography variant="body2">单位：{item.unit ?? '未知（原文未载）'} · 参考范围：{item.reference_range ?? '未知（原文未载）'}</Typography>
        <Typography variant="body2">原文异常标记：{item.abnormal_mark ?? '未知（原文未载）'}</Typography>
        <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>{sourceLocation(report, item.source_page)}</Typography>
        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', mt: .5 }}>原文依据：{item.evidence}</Typography>
      </Box>)}
      {candidate.sections?.map((item, index) => <Box key={index} sx={{ mb: 2 }}>
        <Typography sx={{ fontWeight: 600 }}>{({ findings: '所见', conclusion: '报告结论', other: '报告文字' })[item.kind]}</Typography>
        <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{item.text}</Typography>
        <Typography variant="caption">{sourceLocation(report, item.source_page)} · 原文依据：{item.evidence}</Typography>
      </Box>)}
    </Box>}
    <Dialog open={open} onClose={() => { if (!busy && !uncertain) { setOpen(false); clearApproval(); } }} fullWidth maxWidth="md">
      <DialogTitle>确认本次 AI 整理</DialogTitle>
      <DialogContent>
        {preview?.warning && <Alert severity="warning" sx={{ mb: 2 }}>{preview.warning}</Alert>}
        <Typography sx={{ mb: 2 }}>接收方：{preview?.recipient ? `${preview.recipient.provider} · ${preview.recipient.model} · ${preview.recipient.origin}` : '未配置可用模型'}</Typography>
        <Alert severity="info" sx={{ mb: 2 }}>仅发送下方完整脱敏文字及固定整理规则；原始附件、文件名和资料编号不发送。外部服务收到的文字无法通过本平台撤回。</Alert>
        <TextField label="本次将发送的完整文字" multiline minRows={6} maxRows={18} fullWidth value={preview?.text || ''} slotProps={{ input: { readOnly: true } }} />
        <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>如需修改，关闭窗口后编辑逐页文字，并重新生成预览。本次预览有效至 {preview ? new Date(preview.expires_at).toLocaleString('zh-CN') : '—'}。</Typography>
        <FormControlLabel control={<Checkbox checked={ownership} disabled={busy} onChange={event => setOwnership(event.target.checked)} />} label="我确认本次文字来自本人的报告" />
        <FormControlLabel control={<Checkbox checked={consent} disabled={busy} onChange={event => setConsent(event.target.checked)} />} label="我已检查上方脱敏文字，同意本次发送给显示的接收模型" />
        {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button disabled={busy} onClick={() => { setOpen(false); clearApproval(); }}>暂不发送</Button>
        <Button variant="contained" disabled={busy || !consent || !ownership || !preview?.recipient || modified || (!!preview.consumed_by && uncertain !== 'ai')} onClick={organize}>{uncertain === 'ai' ? '使用原编号重试提交' : '同意并整理'}</Button>
      </DialogActions>
    </Dialog>
  </Box>;
}
