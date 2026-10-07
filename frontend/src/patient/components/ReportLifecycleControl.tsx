import { useState } from 'react';
import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, LinearProgress, Stack, Typography } from '@mui/material';
import { ReportError, changeReportLifecycle, getReportLifecycle } from '../../api/reports';
import type { PatientReport, ReportLifecycleAction, ReportLifecycleReply, ReportLifecycleWorkspace } from '../../api/reports';

const labels = { trash: '移入回收站', restore: '恢复报告', purge: '彻底删除' };
const acknowledgements = { trash: '我已了解影响，确认移入回收站', restore: '我确认恢复报告', purge: '我确认彻底删除此报告及其原件、文字和核对历史' };
interface Pending { action: ReportLifecycleAction; token: string; requestId: string }

export default function ReportLifecycleControl({ report, onChanged, onRefresh }: { report: PatientReport; onChanged: (result: ReportLifecycleReply) => void; onRefresh: () => void }) {
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState<ReportLifecycleAction>('trash');
  const [view, setView] = useState<ReportLifecycleWorkspace | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const available = view && (action === 'trash' ? view.report.archive_status !== 'trash' : view.report.archive_status === 'trash');
  async function load() {
    setBusy(true); setChecked(false); setError(''); setConflict(false); setView(null);
    try { setView(await getReportLifecycle(report.id)); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  function begin(next: ReportLifecycleAction) {
    setAction(next); setOpen(true); void load();
  }
  async function submit() {
    if ((!view || !available || !checked || conflict) && !pending) return;
    const frozen = pending || { action, token: view!.state_token, requestId: crypto.randomUUID() };
    setPending(frozen); setBusy(true); setError('');
    try {
      const result = await changeReportLifecycle(report.id, frozen.action, frozen.token, frozen.requestId, frozen.action === 'purge');
      setPending(null); setOpen(false); setChecked(false); setView(null); onChanged(result);
    } catch (failure) {
      const known = failure instanceof ReportError && failure.status >= 400 && failure.status < 500;
      if (known) { setPending(null); setChecked(false); setConflict(true); setError(failure.message); }
      else setError('操作结果暂未确认，请使用原编号重试；本次选择已锁定，重试不会重复执行。');
    } finally { setBusy(false); }
  }
  return <Box sx={{ mt: 1.5 }}>
    <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
      {report.archive_status === 'trash' ? <>
        <Button disabled={busy || !!pending} onClick={() => begin('restore')}>恢复报告</Button>
        <Button color="error" disabled={busy || !!pending} onClick={() => begin('purge')}>彻底删除</Button>
      </> : <Button color="error" disabled={busy || !!pending} onClick={() => begin('trash')}>移入回收站</Button>}
    </Stack>
    {pending && !open && <Alert severity="warning" action={<Button onClick={() => setOpen(true)}>继续确认操作结果</Button>}>本次操作结果待确认，请用原提交重试。刷新或离开后请到报告列表及回收站查看实际状态。</Alert>}
    <Dialog open={open} fullWidth maxWidth="sm" onClose={() => { if (!busy) setOpen(false); }} aria-labelledby={`report-lifecycle-${report.id}`}>
      <DialogTitle id={`report-lifecycle-${report.id}`}>{labels[action]}</DialogTitle>
      <DialogContent>
        {busy && <LinearProgress aria-label="加载或保存报告管理状态" sx={{ mb: 2 }} />}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {view && <>
          {!available && <Alert severity="warning" sx={{ mb: 2 }}>报告状态已改变，本次操作不适用。<Button onClick={() => { setOpen(false); onRefresh(); }}>关闭并刷新报告列表</Button></Alert>}
          <Typography sx={{ fontWeight: 600, overflowWrap: 'anywhere', mb: 2 }}>{view.report.title}</Typography>
          <Typography variant="body2" sx={{ mb: 2 }}>{view.report.file_count} 个原件 / {view.report.page_count} 页 · {view.report.archive_status === 'trash' ? '回收站' : '已归档'}</Typography>
          {action === 'trash' ? <Typography sx={{ mb: 2 }}>将解除 {view.links_count} 个病例关联并停止 {view.pending_jobs} 个待处理任务。原件及核对历史留在回收站，恢复后需重新选择关联；不会改变既有随访或用药安排。</Typography> : action === 'restore' ? <Typography sx={{ mb: 2 }}>将恢复原件及已有核对历史。不会恢复病例关联、整理任务或外发同意，也不会自动调用 AI。</Typography> : <Alert severity="warning" sx={{ mb: 2 }}>将从应用资料库删除此报告的原件、文字、整理结果和核对历史，无法从回收站恢复。只保留用于防止重复提交的必要编号记录；不会停止既有治疗安排。</Alert>}
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{view.has_dispatched_text ? '本报告已有或可能有文字发给模型。' : ''}已发送给模型的文字无法召回；备份及模型服务方的清理依各自留存策略，不保证即时删除。回收站不会自动到期清理。</Typography>
          <FormControlLabel control={<Checkbox checked={checked} disabled={busy || !!pending || conflict || !available} onChange={event => setChecked(event.target.checked)} />} label={acknowledgements[action]} />
        </>}
        {!pending && (conflict || (!view && !busy)) && <Button onClick={() => { void load(); }}>查看最新影响，重新确认</Button>}
      </DialogContent>
      <DialogActions>
        <Button disabled={busy} onClick={() => setOpen(false)}>{pending ? '暂收起（保留原提交）' : '暂不操作'}</Button>
        <Button variant="contained" color={action === 'purge' ? 'error' : 'primary'} disabled={busy || (!pending && (!view || !available || !checked || conflict))} onClick={() => { void submit(); }}>{pending ? '使用原编号重试操作' : `确认${labels[action]}`}</Button>
      </DialogActions>
    </Dialog>
  </Box>;
}
