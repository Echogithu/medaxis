import { useEffect, useState } from 'react';
import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControlLabel, MenuItem, Pagination, Stack, TextField, Typography } from '@mui/material';
import { confirmReportReview, getReportReview, getReportReviewHistory, getReportReviewVersion, ReportError, saveReportReviewDraft } from '../../api/reports';
import type { PatientReport, ReportReviewVersion, ReportReviewWorkspace, ReviewContent, ReviewOrigin } from '../../api/reports';
import { canConfirmReview, emptyReviewEditor, mergeReviewEditor, reviewLabels } from '../../state/reportReview';

const time = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
const sectionNames = { findings: '检查所见', conclusion: '报告结论', other: '报告文字' };
function ContentView({ content, sourceLabel = '患者录入/修改' }: { content: ReviewContent | undefined; sourceLabel?: string }) {
  return <Stack spacing={1} sx={{ mt: 1 }}>
    {content?.indicators.map((item, index) => <Box key={index} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
      <Typography sx={{ fontWeight: 600 }}>{item.name || '项目未填'}：{item.raw_value || '结果未填'}</Typography>
      <Typography variant="body2">单位：{item.unit ?? '未知'} · 参考范围：{item.reference_range ?? '未知'} · 原报告标记：{item.abnormal_mark ?? '未知'}</Typography>
      <Typography variant="caption">来源页：{item.source_page ?? '无法定位'} · {sourceLabel}</Typography>
      {item.evidence && <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>对照原文：{item.evidence}</Typography>}
    </Box>)}
    {content?.sections.map((item, index) => <Box key={index}>
      <Typography sx={{ fontWeight: 600 }}>{sectionNames[item.kind]}</Typography>
      <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{item.text || '文字未填'}</Typography>
      <Typography variant="caption">来源页：{item.source_page ?? '无法定位'} · {sourceLabel}</Typography>
      {item.evidence && <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>对照原文：{item.evidence}</Typography>}
    </Box>)}
    {!content?.indicators.length && !content?.sections.length && <Typography color="text.secondary">尚无核对内容</Typography>}
  </Stack>;
}
type Submission = { kind: 'draft' | 'confirm'; id: string; workspace: ReportReviewWorkspace;
  content: ReviewContent; origin: ReviewOrigin; draftId: string | null };

export default function ReportReviewPanel({ report, onSaved }: { report: PatientReport; onSaved: () => void }) {
  const [editor, setEditor] = useState(emptyReviewEditor);
  const [latest, setLatest] = useState<ReportReviewWorkspace | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Submission | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<ReportReviewWorkspace | null>(null);
  const [checked, setChecked] = useState(false);
  const [history, setHistory] = useState<{ items: ReportReviewVersion[]; total: number; page: number; limit: number } | null>(null);
  const [shown, setShown] = useState<ReportReviewVersion | null>(null);
  const current = latest || editor.base;
  const locked = busy || !!pending;

  useEffect(() => {
    let live = true;
    getReportReview(report.id).then(value => {
      if (!live) return;
      setLatest(value); setEditor(previous => mergeReviewEditor(previous, value)); setError('');
    }).catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [report.id, report.category, report.source_version]);

  function edit(content: ReviewContent) {
    setEditor(previous => ({ ...previous, content, modified: true })); setChecked(false);
  }
  async function refresh() {
    setBusy(true);
    try {
      const value = await getReportReview(report.id);
      setLatest(value); setEditor(previous => mergeReviewEditor(previous, value)); setError('');
      if (pending && [value.draft, value.confirmed].some(version => version?.request_id === pending.id)) {
        setPending(null); setConfirmTarget(null); setChecked(false); setNotice('已找回本次保存结果，可对照服务端版本。'); onSaved();
      }
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function submit(request: Submission) {
    setBusy(true); setError(''); setNotice(''); setPending(request);
    try {
      const reply = request.kind === 'draft'
        ? await saveReportReviewDraft(report.id, request.workspace, request.content, request.origin, request.id)
        : await confirmReportReview(report.id, request.workspace, request.draftId!, request.id, true);
      setLatest(reply.workspace); setPending(null); setConfirmTarget(null); setChecked(false);
      if (request.kind === 'draft' && reply.workspace.draft?.id !== reply.version.id) {
        setNotice('本次草稿已保存，服务端还有更新版本；本页填写保留，请对照后继续。');
      } else {
        setEditor(previous => mergeReviewEditor(previous, reply.workspace, true));
        setNotice(request.kind === 'draft' ? `草稿版本 ${reply.version.revision} 已保存，尚未确认核对。` : `版本 ${reply.version.revision} 已记录本人核对，不等于医生审核。`);
      }
      setHistory(null); onSaved();
    } catch (failure) {
      if (failure instanceof ReportError && failure.status >= 400 && failure.status < 500) setPending(null);
      setError((failure as Error).message);
    } finally { setBusy(false); }
  }
  function save() {
    if (!editor.base) return;
    void submit({ kind: 'draft', id: crypto.randomUUID(), workspace: editor.base,
      content: structuredClone(editor.content), origin: { ...editor.origin }, draftId: null });
  }
  async function importCandidate() {
    setBusy(true); setError('');
    try {
      const value = await getReportReview(report.id); setLatest(value);
      if (!value.candidate) { setNotice('当前没有可采用的AI候选，仍可人工填写。'); return; }
      setEditor({ base: value, content: structuredClone(value.candidate.content), modified: true,
        origin: { based_on_version_id: null, candidate_job_id: value.candidate.job_id } });
      setNotice('已载入当前AI候选，需逐项对照原件；尚未保存或确认。'); setChecked(false);
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function loadHistory(page = 1) {
    setBusy(true); setError('');
    try { setHistory(await getReportReviewHistory(report.id, page)); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function showVersion(id: string) {
    setBusy(true);
    try { setShown(await getReportReviewVersion(report.id, id)); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  const replaceWarning = editor.modified ? '放弃本页未保存填写，载入最新草稿' : '载入最新草稿';
  return <Box component="section" aria-label="人工核对报告" sx={{ mt: 4, minWidth: 0 }}>
    <Divider sx={{ mb: 3 }} />
    <Typography component="h2" variant="h6">对照原件核对</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>逐项填写或修正。保存草稿后，再单独确认已对照原件。内容只保存到平台，不调用模型。</Typography>
    <Typography sx={{ mb: 2 }}>{reviewLabels[current?.review_status || 'unverified']}</Typography>
    {current?.confirmed && <Box sx={{ mb: 2 }}>
      <Typography component="h3" variant="subtitle1">最近本人核对版本 {current.confirmed.revision} · {time(current.confirmed.created_at)}</Typography>
      {!current.confirmed.source_current && <Alert severity="warning">该确认的来源已变化，历史保留；需按当前原件重新保存并核对。</Alert>}
      <ContentView content={current.confirmed.content} />
    </Box>}
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error} 本页填写仍保留。</Alert>}
    {notice && <Alert severity="info" sx={{ mb: 2 }}>{notice}</Alert>}
    {pending && <Alert severity="warning" sx={{ mb: 2 }}>保存结果尚未确认，请刷新核对进度或使用原编号重试。离开页面后可查看服务端草稿和历史。</Alert>}
    <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', mb: 2 }}>
      <Button disabled={busy} onClick={refresh}>刷新核对进度</Button>
      {pending && <Button disabled={busy} onClick={() => submit(pending)}>使用原编号重试保存</Button>}
      <Button disabled={locked || editor.modified} onClick={importCandidate}>从当前AI候选填写</Button>
    </Stack>
    {latest && editor.modified && <Box sx={{ p: 2, mb: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
      <Typography variant="body2">服务端核对版本 {latest.revision} · 来源代次 {latest.source_epoch}；本页填写基于版本 {editor.base?.revision ?? '—'}。</Typography>
      <ContentView content={latest.draft?.content} />
      <Button disabled={locked} onClick={() => { setEditor(previous => mergeReviewEditor(previous, latest, true)); setError(''); }}>{replaceWarning}</Button>
      {editor.base && (latest.revision !== editor.base.revision || latest.source_hash !== editor.base.source_hash) && <Button disabled={locked} onClick={() => {
        setEditor(previous => ({ ...previous, base: latest, origin: { based_on_version_id: previous.base?.category === latest.category ? previous.origin.based_on_version_id : null, candidate_job_id: null }, modified: true }));
        setError(''); setNotice('已采用最新来源和版本号，本页填写仍保留；请重新对照原件后保存。');
      }}>采用最新来源，保留本页填写</Button>}
    </Box>}
    {editor.base && <>
      {editor.base.draft && !editor.base.draft.source_current && <Alert severity="warning" sx={{ mb: 2 }}>保存的草稿来自旧来源，请对照当前原件修正并重新保存。</Alert>}
      <Typography component="h3" variant="subtitle1">本页草稿</Typography>
      <Typography variant="caption" color="text.secondary">空白单位、范围和异常标记保存为未知；原报告明确写“正常”时可照录。未保存填写在离开或刷新页面后丢失。</Typography>
      <Stack spacing={2} sx={{ mt: 2 }}>{editor.content.indicators.map((item, index) => <Box component="fieldset" key={index} sx={{ m: 0, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2, minWidth: 0 }}>
        <Typography component="legend">指标 {index + 1}</Typography>
        <Stack spacing={1.5}>
          {(['name', 'raw_value', 'unit', 'reference_range', 'abnormal_mark', 'evidence'] as const).map(field => <TextField key={field}
            label={`${({ name: '项目名称', raw_value: '原始结果', unit: '单位', reference_range: '原报告参考范围', abnormal_mark: '原报告异常标记', evidence: '对照原文' })[field]} ${index + 1}`}
            value={item[field] ?? ''} disabled={locked} multiline={field === 'evidence'} minRows={field === 'evidence' ? 2 : undefined}
            slotProps={{ htmlInput: { maxLength: field === 'evidence' ? 4000 : field === 'reference_range' ? 300 : field === 'unit' || field === 'abnormal_mark' ? 100 : 200 } }}
            onChange={event => edit({ ...editor.content, indicators: editor.content.indicators.map((value, position) => position === index ? { ...value,
              [field]: field === 'name' || field === 'raw_value' ? event.target.value : event.target.value || null } : value) })} />)}
          <TextField label={`来源页 ${index + 1}`} type="number" value={item.source_page ?? ''} disabled={locked} helperText={`原件共 ${report.page_count} 页；无法定位时留空`}
            slotProps={{ htmlInput: { min: 1, max: report.page_count, step: 1 } }} onChange={event => edit({ ...editor.content,
              indicators: editor.content.indicators.map((value, position) => position === index ? { ...value, source_page: event.target.value ? Number(event.target.value) : null } : value) })} />
          <Button disabled={locked} color="error" onClick={() => edit({ ...editor.content, indicators: editor.content.indicators.filter((_, position) => position !== index) })}>移除指标 {index + 1}</Button>
        </Stack>
      </Box>)}</Stack>
      {editor.base.category === 'lab' && <Button disabled={locked || editor.content.indicators.length >= 100} sx={{ mt: 1 }} onClick={() => edit({ ...editor.content,
        indicators: [...editor.content.indicators, { name: '', raw_value: '', unit: null, reference_range: null, abnormal_mark: null, source_page: null, evidence: null }] })}>添加检验指标</Button>}
      <Stack spacing={2} sx={{ mt: 2 }}>{editor.content.sections.map((item, index) => <Box key={index} component="fieldset" sx={{ m: 0, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2, minWidth: 0 }}>
        <Typography component="legend">报告文字 {index + 1}</Typography>
        <Stack spacing={1.5}>
          <TextField select label={`文字类型 ${index + 1}`} value={item.kind} disabled={locked} onChange={event => edit({ ...editor.content,
            sections: editor.content.sections.map((value, position) => position === index ? { ...value, kind: event.target.value as typeof item.kind } : value) })}>
            {Object.entries(sectionNames).map(([kind, label]) => <MenuItem key={kind} value={kind}>{label}</MenuItem>)}
          </TextField>
          <TextField label={`报告文字内容 ${index + 1}`} multiline minRows={3} value={item.text} disabled={locked} slotProps={{ htmlInput: { maxLength: 4000 } }}
            onChange={event => edit({ ...editor.content, sections: editor.content.sections.map((value, position) => position === index ? { ...value, text: event.target.value } : value) })} />
          <TextField label={`文字来源页 ${index + 1}`} type="number" value={item.source_page ?? ''} disabled={locked} helperText="无法定位时留空"
            slotProps={{ htmlInput: { min: 1, max: report.page_count, step: 1 } }} onChange={event => edit({ ...editor.content,
              sections: editor.content.sections.map((value, position) => position === index ? { ...value, source_page: event.target.value ? Number(event.target.value) : null } : value) })} />
          <TextField label={`文字对照原文 ${index + 1}`} multiline minRows={2} value={item.evidence ?? ''} disabled={locked} slotProps={{ htmlInput: { maxLength: 4000 } }}
            onChange={event => edit({ ...editor.content, sections: editor.content.sections.map((value, position) => position === index ? { ...value, evidence: event.target.value || null } : value) })} />
          <Button disabled={locked} color="error" onClick={() => edit({ ...editor.content, sections: editor.content.sections.filter((_, position) => position !== index) })}>移除报告文字 {index + 1}</Button>
        </Stack>
      </Box>)}</Stack>
      <Button disabled={locked || editor.content.sections.length >= 20} sx={{ mt: 1 }} onClick={() => edit({ ...editor.content,
        sections: [...editor.content.sections, { kind: editor.base?.category === 'imaging' ? 'findings' : 'other', text: '', source_page: null, evidence: null }] })}>添加报告文字</Button>
      <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap' }}>
        <Button variant="contained" disabled={locked || (!editor.modified && editor.base.draft?.source_current !== false)} onClick={save}>保存核对草稿</Button>
        <Button variant="outlined" disabled={locked || !canConfirmReview(editor)} onClick={() => { setConfirmTarget(editor.base); setChecked(false); }}>确认已对照原件</Button>
        <Button disabled={busy} onClick={() => loadHistory()}>查看核对历史</Button>
      </Stack>
    </>}
    {history && <Box sx={{ mt: 3 }}>
      <Typography component="h3" variant="subtitle1">核对历史 · 共 {history.total} 个版本</Typography>
      {history.items.map(version => <Stack key={version.id} direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="body2">版本 {version.revision} · {version.kind === 'confirmed' ? '本人确认' : '人工草稿'} · {time(version.created_at)}{version.source_current ? '' : ' · 旧来源'}</Typography>
        <Button disabled={busy} onClick={() => showVersion(version.id)}>查看版本 {version.revision}</Button>
      </Stack>)}
      {history.total > history.limit && <Pagination count={Math.ceil(history.total / history.limit)} page={history.page} onChange={(_, page) => loadHistory(page)} />}
      {shown && <Box sx={{ mt: 2, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
        <Typography component="h4" variant="subtitle1">历史版本 {shown.revision} · {shown.kind === 'confirmed' ? '本人确认' : '人工草稿'} · 原件版本 {shown.source_version}</Typography>
        <Typography variant="caption">来源：{shown.based_on_version_id ? '患者修改已有版本' : shown.candidate_job_id ? '患者依据AI候选填写' : '患者人工填写'}；本人确认不等于医生审核。</Typography>
        <ContentView content={shown.content} />
        {shown.original_candidate && <Box sx={{ mt: 2 }}><Typography variant="subtitle2">当时的AI原始候选（未核对）</Typography>
          <ContentView sourceLabel="AI原始候选，未核对" content={{ indicators: shown.original_candidate.indicators || [], sections: shown.original_candidate.sections || [] }} />
        </Box>}
      </Box>}
    </Box>}
    <Dialog open={!!confirmTarget} onClose={() => { if (!busy) { setConfirmTarget(null); setChecked(false); } }} fullWidth maxWidth="md">
      <DialogTitle>确认这个已保存的草稿</DialogTitle>
      <DialogContent>
        <Typography>草稿版本 {confirmTarget?.draft?.revision} · {confirmTarget?.draft ? time(confirmTarget.draft.created_at) : ''}</Typography>
        <ContentView content={confirmTarget?.draft?.content} />
        <Alert severity="info" sx={{ my: 2 }}>只记录本人的核对确认，不等于医生审核，不生成诊断、随访或用药安排。</Alert>
        <FormControlLabel control={<Checkbox checked={checked} disabled={busy} onChange={event => setChecked(event.target.checked)} />} label="我已逐项对照原件，确认这个草稿的填写" />
        {error && <Alert severity="error">{error}</Alert>}
      </DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => { setConfirmTarget(null); setChecked(false); }}>暂不确认</Button>
        <Button variant="contained" disabled={busy || !checked || !!pending} onClick={() => {
          if (confirmTarget?.draft) void submit({ kind: 'confirm', id: crypto.randomUUID(), workspace: confirmTarget,
            content: confirmTarget.draft.content!, origin: { based_on_version_id: null, candidate_job_id: null }, draftId: confirmTarget.draft.id });
        }}>记录本人确认</Button></DialogActions>
    </Dialog>
  </Box>;
}
