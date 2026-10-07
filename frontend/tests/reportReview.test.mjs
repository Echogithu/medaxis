import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canConfirmReview, emptyReviewEditor, mergeReviewEditor } from '../src/state/reportReview.ts';
import { confirmReportReview, saveReportReviewDraft } from '../src/api/reports.ts';

const content = value => ({ indicators: [{ name: '项目', raw_value: value, unit: null, reference_range: null,
  abnormal_mark: null, source_page: null, evidence: null }], sections: [] });
const workspace = (revision=1, epoch=0) => ({ revision, source_epoch: epoch, source_version: 1, source_hash: 'a'.repeat(64),
  category: 'lab', draft: { id: 'draft-id', category: 'lab', revision, source_current: true, content: content('服务端值') }, confirmed: null });

test('刷新不能覆盖未保存人工填写或悄悄更新其并发版本号，明确放弃才替换', () => {
  const initial = mergeReviewEditor(emptyReviewEditor(), workspace());
  const changed = { ...initial, content: content('本页值'), modified: true };
  const newer = workspace(2,1);
  const kept = mergeReviewEditor(changed, newer);
  assert.equal(kept, changed);
  assert.equal(kept.base.revision, 1);
  const replaced = mergeReviewEditor(kept, newer, true);
  assert.equal(replaced.base.revision, 2); assert.equal(replaced.content.indicators[0].raw_value, '服务端值');
  assert.equal(mergeReviewEditor(replaced, workspace()), replaced);
});

test('类别变更保留旧填写供对照，但新草稿不会引用另一类别的版本', () => {
  const latest = workspace(2,1); latest.category = 'imaging'; latest.draft.source_current = false;
  const editor = mergeReviewEditor(emptyReviewEditor(), latest);
  assert.equal(editor.content.indicators.length, 1);
  assert.equal(editor.origin.based_on_version_id, null);
  assert.equal(canConfirmReview(editor), false);
});

test('仅当前来源的完整已保存草稿可打开确认，编辑/旧来源/空或未填完都禁用', () => {
  const initial = mergeReviewEditor(emptyReviewEditor(), workspace());
  assert.equal(canConfirmReview(initial), true);
  assert.equal(canConfirmReview({ ...initial, modified: true }), false);
  assert.equal(canConfirmReview({ ...initial, content: content('') }), false);
  assert.equal(canConfirmReview({ ...initial, content: { indicators: [], sections: [] } }), false);
  assert.equal(canConfirmReview({ ...initial, base: { ...initial.base, draft: { ...initial.base.draft, source_current: false } } }), false);
  assert.equal(canConfirmReview({ ...initial, base: { ...initial.base, revision: 2 } }), false);
});

test('保存和确认绑定源/版本及原编号，确认请求不能偷换为未保存正文', async () => {
  const captured = [];
  globalThis.localStorage = { getItem: () => 'synthetic-token' };
  const original = globalThis.fetch;
  globalThis.fetch = async (_url, init) => { captured.push(JSON.parse(init.body)); return new Response('{}', { status: 201 }); };
  try {
    const view = workspace();
    await saveReportReviewDraft('report', view, content('人工值'), { based_on_version_id: null, candidate_job_id: null }, 'same-request');
    await saveReportReviewDraft('report', view, content('人工值'), { based_on_version_id: null, candidate_job_id: null }, 'same-request');
    assert.deepEqual(captured[0], captured[1]);
    await confirmReportReview('report', view, 'draft-id', 'confirm-request', true);
    assert.equal(captured[2].expected_source_hash, 'a'.repeat(64));
    assert.equal(captured[2].draft_id, 'draft-id'); assert.equal(captured[2].checked_against_original, true);
    assert.equal('content' in captured[2], false);
  } finally { globalThis.fetch = original; }
});
