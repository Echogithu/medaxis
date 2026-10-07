import assert from 'node:assert/strict';
import { test } from 'node:test';
import { approvedReportPreview, emptyReportApproval, mergeReportTextEditor, newerWorkspace, reportPreviewKey, updateReportApproval } from '../src/state/reportWorkflow.ts';

const view = (revision, time, text) => ({ revision, source_version: 1, category: 'lab', extract_job: null,
  ai_job: { id: 'job-1', updated_at: time }, preview: { pages: [{ page: 1, text }] } });

test('旧预览响应不能覆盖新预览及已保存文字', () => {
  const old = view(1, '2026-10-03T10:00:00Z', '旧文字'), latest = view(2, '2026-10-03T10:00:01Z', '新文字');
  const editor = { pages: latest.preview.pages, modified: false, workspace: latest };
  assert.equal(newerWorkspace(latest, old), latest);
  assert.equal(mergeReportTextEditor(editor, old, 1), editor);
});

test('跨窗口更新文字或接收方后旧勾选立即失效，重新确认不继承另一项', () => {
  const key = reportPreviewKey({ id: 'preview-1', hash: 'text-source-recipient-1' });
  let approval = updateReportApproval(emptyReportApproval(), key, 'ownership', true);
  approval = updateReportApproval(approval, key, 'consent', true);
  assert.equal(approvedReportPreview(approval, key), true);
  for (const changed of [
    { id: 'preview-2', hash: 'text-source-recipient-1' },
    { id: 'preview-1', hash: 'text-source-recipient-2' },
  ]) {
    const nextKey = reportPreviewKey(changed);
    assert.equal(approvedReportPreview(approval, nextKey), false);
    const reconfirmed = updateReportApproval(approval, nextKey, 'consent', true);
    assert.equal(reconfirmed.ownership, false);
    assert.equal(approvedReportPreview(reconfirmed, nextKey), false);
  }
  assert.equal(approvedReportPreview(approval, null), false);
  assert.equal(approvedReportPreview(emptyReportApproval(), key), false);
});

test('延迟轮询不能把已结束任务显示回处理中', () => {
  const processing = view(1, '2026-10-03T10:00:00Z', '文字'); processing.ai_job.status = 'processing';
  const completed = view(1, '2026-10-03T10:00:01Z', '文字'); completed.ai_job.status = 'completed';
  assert.equal(newerWorkspace(completed, processing).ai_job.status, 'completed');
});

test('任务进度刷新保留未保存填写，生成新预览后才能明确替换', () => {
  const next = view(2, '2026-10-03T10:00:02Z', '服务端脱敏文字');
  const editor = { pages: [{ page: 1, text: '本页未保存填写' }], modified: true, workspace: view(1, '2026-10-03T10:00:00Z', '') };
  const preserved = mergeReportTextEditor(editor, next, 1);
  assert.equal(preserved.pages[0].text, '本页未保存填写');
  assert.equal(preserved.modified, true);
  const saved = mergeReportTextEditor(preserved, next, 1, true);
  assert.equal(saved.pages[0].text, '服务端脱敏文字');
  assert.equal(saved.modified, false);
});
