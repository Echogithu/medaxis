import { useEffect, useState } from 'react';
import { Alert, Box, Button, Checkbox, CircularProgress, FormControlLabel, Paper, Stack, TextField, Typography } from '@mui/material';
import {
  createPostVisitFeedback,
  getCaseRecovery,
  getPostVisitFeedback,
  updatePostVisitFeedback,
} from '../../api/patient';
import type { CaseRecovery, PostVisitFeedback, PostVisitFeedbackFields } from '../../api/patient';
import PostVisitActionsPanel from './PostVisitActionsPanel';

function toLocalDateTime(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toLocalFields(item: PostVisitFeedback | null): PostVisitFeedbackFields {
  return {
    self_reported_visit_at: item?.self_reported_visit_at || null,
    actual_department: item?.actual_department || null,
    patient_summary: item?.patient_summary || null,
    follow_up_items: item?.follow_up_items || [],
    material_file_ids: item?.material_file_ids || [],
  };
}

export default function PostVisitFeedbackPanel({ caseId }: { caseId: string }) {
  const [aiBusy, setAiBusy] = useState(false);
  const [feedback, setFeedback] = useState<PostVisitFeedback | null>(null);
  const [materials, setMaterials] = useState<CaseRecovery['materials']>([]);
  const [visitAt, setVisitAt] = useState('');
  const [department, setDepartment] = useState('');
  const [summary, setSummary] = useState('');
  const [followUpText, setFollowUpText] = useState('');
  const [materialIds, setMaterialIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const hydrate = (item: PostVisitFeedback | null) => {
    setFeedback(item);
    const fields = toLocalFields(item);
    setVisitAt(toLocalDateTime(fields.self_reported_visit_at));
    setDepartment(fields.actual_department || '');
    setSummary(fields.patient_summary || '');
    setFollowUpText(fields.follow_up_items.join('\n'));
    setMaterialIds(fields.material_file_ids);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.allSettled([getCaseRecovery(caseId), getPostVisitFeedback(caseId)])
      .then(([recoveryResult, feedbackResult]) => {
        if (cancelled) return;
        if (recoveryResult.status === 'fulfilled') setMaterials(recoveryResult.value.materials);
        if (feedbackResult.status === 'fulfilled') hydrate(feedbackResult.value.feedback);
        if (recoveryResult.status === 'rejected' || feedbackResult.status === 'rejected') {
          setError('就诊结果或病例材料暂时无法读取；已读取的内容仍可查看。');
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [caseId]);

  const fields = (): PostVisitFeedbackFields => ({
    self_reported_visit_at: visitAt ? new Date(visitAt).toISOString() : null,
    actual_department: department.trim() || null,
    patient_summary: summary.trim() || null,
    follow_up_items: followUpText.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
    material_file_ids: materialIds,
  });

  const save = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      if (feedback) {
        hydrate(await updatePostVisitFeedback(caseId, feedback.feedback_id, feedback.revision, fields()));
      } else {
        const result = await createPostVisitFeedback(caseId, fields());
        hydrate(result.feedback);
      }
      setNotice('就诊结果已保存为患者自述。');
    } catch (cause) {
      setError(cause instanceof Error ? `未保存：${cause.message}` : '未保存；填写内容仍保留在当前页面。');
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Box sx={{ display: 'grid', placeItems: 'center', py: 3 }}><CircularProgress size={24} /></Box>;

  return (
    <Paper variant="outlined" sx={{ mt: 3, p: { xs: 2, md: 3 }, borderRadius: 3 }}>
      <Typography variant="h6" sx={{ fontWeight: 750 }}>就诊结果</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        记录你实际就诊后的情况，仅作为本人记录保存。
      </Typography>
      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mt: 2 }}>{notice}</Alert>}
      <Stack spacing={2} sx={{ mt: 2 }}>
        <TextField
          label="就诊时间"
          type="datetime-local"
          value={visitAt}
          onChange={(event) => setVisitAt(event.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
        />
        <TextField label="就诊科室" value={department} onChange={(event) => setDepartment(event.target.value)} />
        <TextField label="就诊情况" multiline minRows={3} value={summary} onChange={(event) => setSummary(event.target.value)} />
        <TextField
          label="需要复查的事项（每行一条）"
          multiline minRows={2} value={followUpText}
          onChange={(event) => setFollowUpText(event.target.value)}
        />
        <Box>
          <Typography variant="subtitle2">相关检查资料</Typography>
          {materials.length
            ? materials.map((material) => (
              <FormControlLabel
                key={material.file_id}
                control={<Checkbox
                  checked={materialIds.includes(material.file_id)}
                  onChange={(event) => setMaterialIds((current) => event.target.checked
                    ? [...new Set([...current, material.file_id])]
                    : current.filter((id) => id !== material.file_id))}
                />}
                label={`${material.filename} · ${({ queued: '等待处理', processing: '处理中', completed: '已整理', failed: '处理失败' } as Record<string, string>)[material.status] || material.status}`}
              />
            ))
            : <Typography variant="body2" color="text.secondary">暂无检查资料。</Typography>}
        </Box>
        {feedback && <>
          <Typography variant="caption" color="text.secondary">已保存 · 本人记录</Typography>
          {feedback.revision_history.length > 0 && (
            <Box component="details">
              <Typography component="summary" sx={{ cursor: 'pointer' }}>修改历史</Typography>
              {feedback.revision_history.map((entry) => (
                <Typography key={entry.revision} variant="body2" color="text.secondary">
                  修订 {entry.revision} · {entry.submitted_at || '时间未知'} · 患者自述
                </Typography>
              ))}
            </Box>
          )}
        </>}
        <Button variant="contained" onClick={() => void save()} disabled={busy || aiBusy}>
          {busy ? '保存中…' : feedback ? '保存修改' : '保存就诊结果'}
        </Button>
      </Stack>
      {feedback && <PostVisitActionsPanel caseId={caseId} revision={feedback.revision} onBusyChange={setAiBusy} dirty={busy ||
        summary.trim() !== (feedback.patient_summary || '') || department.trim() !== (feedback.actual_department || '') ||
        visitAt !== toLocalDateTime(feedback.self_reported_visit_at) ||
        JSON.stringify(fields().follow_up_items) !== JSON.stringify(feedback.follow_up_items) ||
        JSON.stringify(materialIds) !== JSON.stringify(feedback.material_file_ids)} />}
    </Paper>
  );
}
