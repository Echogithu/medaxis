import { useRef, useState } from 'react';
import { Alert, Box, Button, Card, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, LinearProgress, Stack, Typography } from '@mui/material';
import { ArrowDownwardRounded, ArrowUpwardRounded, UploadFileOutlined } from '@mui/icons-material';
import { DuplicateReportError, ReportError, uploadReport } from '../../api/reports';
import type { DuplicateReport, ReportDuplicateChoice, ReportFields } from '../../api/reports';
import { reportCategories } from '../../state/reportFields';
import ReportFieldsForm from './ReportFieldsForm';

interface Group {
  id: string; requestId: string; fields: ReportFields; files: File[]; ownership: boolean;
  status: 'waiting' | 'saving' | 'saved' | 'error' | 'duplicate'; error: string; uncertain: boolean;
  duplicates?: DuplicateReport[]; more?: boolean; choice?: ReportDuplicateChoice; outcome?: 'archived' | 'reused';
}
const accept = '.jpg,.jpeg,.png,.webp,.pdf';
function fileProblem(file: File): string | null {
  if (!/\.(jpe?g|png|webp|pdf)$/i.test(file.name)) return '仅支持 JPEG、PNG、WEBP 和 PDF';
  if (!file.size || file.size > 10 * 1024 * 1024) return '每个文件需非空且不超过10MiB';
  return null;
}
export default function ReportUploadDialog({ open, onClose, onResume, onSaved }: { open: boolean; onClose: () => void; onResume: () => void; onSaved: () => void }) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const addTarget = useRef<string | null>(null);
  const mutate = (id: string, changes: Partial<Group>) => setGroups(current => current.map(group => group.id === id ? {
    ...group, ...changes, ...(changes.fields || changes.files || changes.ownership !== undefined ? {
      requestId: crypto.randomUUID(), status: 'waiting' as const, error: '', uncertain: false, duplicates: undefined, choice: undefined,
    } : {}),
  } : group));
  function selectFiles(files: File[]) {
    const problem = files.map(fileProblem).find(Boolean);
    if (problem) { setError(problem); return; }
    const target = groups.find(group => group.id === addTarget.current);
    if (target) {
      if (target.files.length + files.length > 5) { setError('每份报告最多5个文件'); return; }
      mutate(target.id, { files: [...target.files, ...files] });
    } else {
      if (groups.length + files.length > 5) { setError('每批最多5份报告；同一份的其他页面可在该份内添加'); return; }
      setGroups(current => [...current, ...files.map(file => ({ id: crypto.randomUUID(), requestId: crypto.randomUUID(), files: [file], ownership: false,
        fields: { title: file.name.replace(/\.[^.]+$/, ''), category: 'other' as const, institution: '', examination_date: null, report_date: null, notes: '' },
        status: 'waiting' as const, error: '', uncertain: false }))]);
    }
    setError('');
  }
  async function save(selected?: Group[]) {
    const pending = selected || groups.filter(group => group.status !== 'saved' && group.status !== 'duplicate');
    if (!pending.length || pending.some(group => !group.fields.title.trim() || !group.ownership)) {
      setError('请填写每份报告名称，并确认归档的是本人报告'); return;
    }
    setBusy(true); setError('');
    for (const group of pending) {
      mutate(group.id, { status: 'saving', error: '' });
      try {
        const result = await uploadReport(group.fields, group.files, group.requestId, group.ownership, group.choice);
        mutate(group.id, { status: 'saved', uncertain: false, outcome: result.upload_outcome || 'archived', duplicates: undefined });
        onSaved();
      } catch (failure) {
        if (failure instanceof DuplicateReportError) {
          mutate(group.id, { status: 'duplicate', uncertain: false, duplicates: failure.reports, more: failure.more, error: '' });
          continue;
        }
        const uncertain = !(failure instanceof ReportError && failure.status >= 400 && failure.status < 500);
        mutate(group.id, { status: 'error', uncertain, error: uncertain ? '归档结果暂未确认。原填写仍保留，请用原提交重试；成功项不会重复保存。' : (failure as Error).message });
      }
    }
    setBusy(false);
  }
  function choose(group: Group, choice?: ReportDuplicateChoice) {
    const selected = { ...group, choice, requestId: crypto.randomUUID(), status: 'waiting' as const, duplicates: undefined, error: '', uncertain: false };
    mutate(group.id, { choice, requestId: selected.requestId, status: 'waiting', duplicates: undefined, error: '', uncertain: false });
    void save([selected]);
  }
  const saved = groups.filter(group => group.status === 'saved').length;
  const pendingCount = groups.length - saved;
  const close = () => {
    if (busy) return;
    if (!pendingCount) setGroups([]);
    onClose();
  };
  return <>
  {!open && pendingCount > 0 && <Alert severity="warning" sx={{ mt: 2 }} action={<Button onClick={onResume}>继续处理</Button>}>
    当前页面保留了 {pendingCount} 份待处理提交。请先继续处理；刷新或离开页面会清除未保存填写和所选文件，已归档报告仍在列表中。
  </Alert>}
  <Dialog open={open} fullWidth maxWidth="md" onClose={close} aria-labelledby="upload-report-title">
    <DialogTitle id="upload-report-title">上传检查报告</DialogTitle>
    <DialogContent>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>原件将保存到医枢平台。此步骤只校验和归档；AI 整理需要另行查看脱敏文字并逐次同意。</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>每批最多5份；每份最多5个文件、合计20页；每文件不超过10MiB。首次选取默认一文件一份，同一报告的其他页请在该份内添加。PDF 包含多份时请先拆分。</Typography>
      <input hidden ref={input} type="file" multiple accept={accept} aria-label="选择报告文件" onChange={event => { selectFiles(Array.from(event.target.files || [])); event.target.value = ''; }} />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {busy && <LinearProgress aria-label="校验并归档原件" sx={{ mb: 2 }} />}
      {groups.length > 0 && <Typography role="status" sx={{ mb: 2 }}>本批已处理 {saved} / {groups.length} 份（新增 {groups.filter(group => group.status === 'saved' && group.outcome !== 'reused').length}，复用 {groups.filter(group => group.status === 'saved' && group.outcome === 'reused').length}）</Typography>}
      <Stack spacing={2}>{groups.map((group, index) => {
        const locked = busy || group.status === 'saved' || group.uncertain;
        return <Card key={group.id} variant="outlined" component="section" aria-label={`第${index + 1}份报告`} sx={{ p: { xs: 2, sm: 3 }, boxShadow: 'none' }}>
          <Stack direction="row" sx={{ mb: 2, justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography component="h3" variant="subtitle1">第 {index + 1} 份报告 · {group.files.length} 个文件</Typography>
            <Chip size="small" label={{ waiting: '待提交', saving: '处理中', saved: group.outcome === 'reused' ? '已复用' : '已归档', error: group.uncertain ? '结果待确认' : '未归档', duplicate: '重复原件待选择' }[group.status]} color={group.status === 'saved' ? 'success' : 'default'} />
          </Stack>
          <ReportFieldsForm value={group.fields} disabled={locked} onChange={fields => mutate(group.id, { fields })} />
          <Box sx={{ mt: 2 }}>{group.files.map((file, position) => <Stack key={`${position}-${file.name}`} direction="row" spacing={1} sx={{ py: 0.5, alignItems: 'center' }}>
            <Typography variant="body2" sx={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{position + 1}. {file.name}</Typography>
            <Button size="small" aria-label={`文件${position + 1}上移`} disabled={locked || !position} onClick={() => { const files = [...group.files]; [files[position - 1], files[position]] = [files[position], files[position - 1]]; mutate(group.id, { files }); }}><ArrowUpwardRounded fontSize="small" /></Button>
            <Button size="small" aria-label={`文件${position + 1}下移`} disabled={locked || position === group.files.length - 1} onClick={() => { const files = [...group.files]; [files[position + 1], files[position]] = [files[position], files[position + 1]]; mutate(group.id, { files }); }}><ArrowDownwardRounded fontSize="small" /></Button>
            <Button size="small" disabled={locked || group.files.length === 1} onClick={() => mutate(group.id, { files: group.files.filter((_, i) => i !== position) })}>移除</Button>
          </Stack>)}</Box>
          <Button disabled={locked || group.files.length === 5} onClick={() => { addTarget.current = group.id; input.current?.click(); }}>添加到这份报告</Button>
          <FormControlLabel control={<Checkbox checked={group.ownership} disabled={locked} onChange={e => mutate(group.id, { ownership: e.target.checked })} />} label="我确认归档的是本人报告" />
          {group.error && <Alert severity="error" sx={{ mt: 1 }}>{group.error}</Alert>}
          {group.status === 'duplicate' && <Box component="section" aria-label="重复报告选择" sx={{ mt: 2 }}>
            <Alert severity="info">相同原件已归档。复用会保留已有报告的信息、核对结果和病例关联，本页填写不会覆盖它；另存会创建独立报告。</Alert>
            <Stack spacing={1} sx={{ mt: 1 }}>{group.duplicates?.map(report => <Box key={report.id} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
              <Typography sx={{ overflowWrap: 'anywhere' }}>{report.title}</Typography>
              <Typography variant="body2" color="text.secondary">{reportCategories[report.category]} · {report.institution || '机构未填写'} · 检查日期 {report.examination_date || '未填写'} · 归档 {new Date(report.created_at).toLocaleString('zh-CN')}</Typography>
              <Button disabled={busy} onClick={() => choose(group, { duplicate_mode: 'reuse', duplicate_report_id: report.id })}>复用这份报告</Button>
            </Box>)}</Stack>
            {group.more && <Typography variant="body2">这里显示最近5份相同原件；更多报告可在报告列表查看。</Typography>}
            <Button disabled={busy} onClick={() => choose(group, { duplicate_mode: 'separate' })}>仍然另存一份</Button>
            <Button disabled={busy} onClick={() => choose(group)}>重新检查重复报告</Button>
          </Box>}
          {group.status === 'error' && group.choice && !group.uncertain && <Button onClick={() => choose(group)}>重新检查重复报告</Button>}
          {!locked && <Button color="error" onClick={() => setGroups(current => current.filter(item => item.id !== group.id))}>取消此份</Button>}
        </Card>;
      })}</Stack>
      <Button sx={{ mt: 2 }} startIcon={<UploadFileOutlined />} disabled={busy || groups.length >= 5} onClick={() => { addTarget.current = null; input.current?.click(); }}>选择其他报告</Button>
    </DialogContent>
    <DialogActions>
      <Button disabled={busy} onClick={close}>{pendingCount > 0 ? '暂收起（保留待处理项）' : saved > 0 ? '完成' : '关闭'}</Button>
      <Button variant="contained" disabled={busy || !groups.some(group => group.status !== 'saved' && group.status !== 'duplicate')} onClick={() => { void save(); }}>{groups.some(group => group.status === 'error') ? '重试未完成项' : '保存原件'}</Button>
    </DialogActions>
  </Dialog></>;
}
