import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControlLabel, Pagination, Stack, TextField, Typography } from '@mui/material';
import { getReportLinks, listReportCaseOptions, ReportError, saveReportLinks } from '../../api/reports';
import type { PatientReport, ReportCaseOptions, ReportLinksWorkspace } from '../../api/reports';
import { acceptLinksWorkspace, reportLinkLabels } from '../../state/reportLinks';

type Submission = { id: string; base: ReportLinksWorkspace; caseIds: string[]; refreshIds: string[] };
export default function ReportCaseLinksPanel({ report }: { report: PatientReport }) {
  const [view, setView] = useState<ReportLinksWorkspace | null>(null);
  const [base, setBase] = useState<ReportLinksWorkspace | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ReportCaseOptions | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [optionsError, setOptionsError] = useState('');
  const [optionsReload, setOptionsReload] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Submission | null>(null);
  const locked = busy || !!pending;
  useEffect(() => {
    let live = true;
    getReportLinks(report.id).then(value => { if (live) { setView(previous => acceptLinksWorkspace(previous,value)); setError(''); } })
      .catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [report.id, report.category, report.source_version, report.review_revision]);
  useEffect(() => {
    if (!open) return;
    let live = true;
    listReportCaseOptions(report.id, search, page).then(value => { if (live) { setOptions(value); setOptionsError(''); } })
      .catch(failure => { if (live) setOptionsError(failure.message); });
    return () => { live = false; };
  }, [open, report.id, search, page, optionsReload]);

  async function refresh(discard = false) {
    setBusy(true);
    try {
      const value = await getReportLinks(report.id); setView(previous => acceptLinksWorkspace(previous,value)); setError('');
      if (discard) { setBase(value); setSelected(value.items.map(item => item.case_id)); }
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function submit(request: Submission) {
    setBusy(true); setPending(request); setError(''); setNotice('');
    try {
      const reply = await saveReportLinks(report.id, request.base, request.caseIds, request.refreshIds, request.id);
      setView(previous => acceptLinksWorkspace(previous,reply.workspace)); setBase(reply.workspace); setSelected(reply.workspace.items.map(item => item.case_id));
      setPending(null); setOpen(false); setNotice('病例关联已保存；仅本人可见，不会发送给医生或模型。');
    } catch (failure) {
      if (failure instanceof ReportError && failure.status >= 400 && failure.status < 500) setPending(null);
      setError((failure as Error).message);
    } finally { setBusy(false); }
  }
  async function choose() {
    setBusy(true); setError('');
    try {
      const value = await getReportLinks(report.id); setView(previous => acceptLinksWorkspace(previous,value)); setBase(value);
      setSelected(value.items.map(item => item.case_id)); setSearchInput(''); setSearch(''); setPage(1); setOptions(null); setOpen(true);
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  function changeOne(caseId: string, update: boolean) {
    if (!view) return;
    void submit({ id: crypto.randomUUID(), base: view,
      caseIds: view.items.filter(item => update || item.case_id !== caseId).map(item => item.case_id), refreshIds: update ? [caseId] : [] });
  }
  return <Box component="section" aria-label="报告病例关联" sx={{ mt: 3 }}>
    <Divider sx={{ mb: 2 }} />
    <Typography component="h2" variant="h6">关联到我的病例</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>仅在本人病例中建立资料引用。不会授权医生查看，也不会自动用于诊断、随访或用药。</Typography>
    {error && <Alert severity="error" sx={{ my: 1 }}>{error} 本页选择仍保留。</Alert>}
    {notice && <Alert severity="success" sx={{ my: 1 }}>{notice}</Alert>}
    {pending && <Alert severity="warning">提交结果尚未确认，请使用原编号重试。<Button disabled={busy} onClick={() => submit(pending)}>使用原编号重试关联</Button></Alert>}
    {view?.items.map(item => <Box key={item.case_id} sx={{ my: 1.5, p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
      <Typography sx={{ overflowWrap: 'anywhere', fontWeight: 600 }}>{item.title}</Typography>
      <Typography variant="body2">关联原件版本 {item.source_version} · {item.review_revision ? `本人核对版本 ${item.review_revision}` : '未关联核对内容'}</Typography>
      <Typography variant="body2" color={['source_changed','review_changed'].includes(item.status) ? 'warning.main' : 'text.secondary'}>{reportLinkLabels[item.status]}</Typography>
      <Stack direction="row" sx={{ flexWrap: 'wrap' }}>
        <Button component={RouterLink} to={`/cases?case_id=${encodeURIComponent(item.case_id)}`}>查看病例</Button>
        {['source_changed','review_changed'].includes(item.status) && <Button disabled={locked} onClick={() => changeOne(item.case_id,true)}>更新为当前来源</Button>}
        <Button disabled={locked} onClick={() => changeOne(item.case_id,false)}>解除关联</Button>
      </Stack>
    </Box>)}
    {view && !view.items.length && <Typography color="text.secondary" sx={{ my: 1 }}>还没有关联病例；报告已独立归档。</Typography>}
    <Button disabled={locked} onClick={choose}>选择关联病例</Button><Button disabled={busy} onClick={() => refresh()}>刷新关联进度</Button>
    <Dialog open={open} onClose={() => { if (!locked) setOpen(false); }} fullWidth maxWidth="sm">
      <DialogTitle>选择本人的病例</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 2 }}>最多关联50个病例。已有引用保持原版本；更新来源需在关联卡片单独操作。</Typography>
        <Box component="form" onSubmit={event => { event.preventDefault(); setSearch(searchInput.trim()); setPage(1); setOptions(null); }} sx={{ display: 'flex', gap: 1, my: 2 }}>
          <TextField label="搜索病例名称" value={searchInput} disabled={locked} size="small" sx={{ flex: 1 }} slotProps={{ htmlInput: { maxLength: 200 } }} onChange={event => setSearchInput(event.target.value)} />
          <Button type="submit" disabled={locked}>搜索</Button>
        </Box>
        {optionsError ? <Alert severity="error" action={<Button disabled={locked} onClick={() => setOptionsReload(value => value+1)}>重试</Button>}>{optionsError}</Alert> : !options ? <Typography>加载病例中…</Typography> : <>
          {!options.items.length && <Typography color="text.secondary">{search ? '没有匹配的本人病例' : '还没有病例，可先保留独立报告。'}</Typography>}
          <Stack>{options.items.map(item => <FormControlLabel key={item.id} sx={{ overflowWrap: 'anywhere' }} control={<Checkbox
            checked={selected.includes(item.id)} disabled={locked || (selected.length >= 50 && !selected.includes(item.id))}
            onChange={event => setSelected(values => event.target.checked ? [...values, item.id] : values.filter(value => value !== item.id))} />} label={item.title} />)}</Stack>
          {options.total > options.limit && <Pagination disabled={locked} count={Math.ceil(options.total/options.limit)} page={page} onChange={(_,value) => { setPage(value); setOptions(null); }} />}
        </>}
        <Typography sx={{ mt: 2 }}>共选择 {selected.length} 个病例（保留其他页的选择）</Typography>
        {error && <Alert severity="error" sx={{ mt: 1 }}>{error} 选择仍保留；请对照最新关联。</Alert>}
        {pending && <Alert severity="warning" sx={{ mt: 1 }}>提交结果尚未确认。
          <Button disabled={busy} onClick={() => submit(pending)}>使用原编号重试关联</Button></Alert>}
        {view && base && (view.links_revision !== base.links_revision || view.source_hash !== base.source_hash || view.review_revision !== base.review_revision) && <Alert severity="warning" sx={{ mt: 1 }}>服务端版本已变化，保存前需重新对照。</Alert>}
        {error && <Button disabled={locked} onClick={() => refresh(true)}>放弃本页选择，载入最新关联</Button>}
      </DialogContent>
      <DialogActions><Button disabled={locked} onClick={() => setOpen(false)}>暂不保存</Button>
        <Button disabled={locked || !base || !options || !!optionsError} variant="contained" onClick={() => {
          if (base) void submit({ id: crypto.randomUUID(), base, caseIds: [...selected], refreshIds: [] });
        }}>保存病例关联</Button></DialogActions>
    </Dialog>
  </Box>;
}
