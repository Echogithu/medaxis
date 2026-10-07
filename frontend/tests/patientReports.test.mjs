import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DuplicateReportError, editReport, extractReportText, getReportOriginal, getReportWorkspace, listReports, organizeReportText, previewReportText, uploadReport } from '../src/api/reports.ts';

globalThis.localStorage = { getItem: () => 'synthetic-token' };

test('上传和重试发送同一编号及有序文件，走独立归档接口', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return Response.json({ id: 'report-1' }); };
  const fields = { title: '合成报告', category: 'lab', institution: '', examination_date: null, report_date: null, notes: '' };
  const files = [new File(['page2'], 'page2.png'), new File(['page1'], 'page1.png')];
  try {
    await uploadReport(fields, files, 'fixed-request-id', true);
    await uploadReport(fields, files, 'fixed-request-id', true);
  } finally { globalThis.fetch = original; }
  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.equal(call.url, '/api/v1/patient/reports');
    assert.equal(call.options.headers.Authorization, 'Bearer synthetic-token');
    assert.equal(call.options.headers['Content-Type'], undefined);
    assert.deepEqual(call.options.body.getAll('files').map(file => file.name), ['page2.png', 'page1.png']);
    assert.deepEqual(JSON.parse(call.options.body.get('metadata')), { ...fields, request_id: 'fixed-request-id', ownership_declared: true });
  }
});

test('重复提示保留本人候选元数据，复用和另存重试发送冻结选择', async () => {
  const original = globalThis.fetch;
  const calls = [], candidate = { id: 'own-report', title: '原报告' };
  globalThis.fetch = async (_, options) => {
    calls.push(JSON.parse(options.body.get('metadata')));
    if (calls.length === 1) return Response.json({ detail: { code: 'duplicate_report', message: '相同原件', reports: [candidate], more: true } }, { status: 409 });
    return Response.json({ id: 'own-report', upload_outcome: 'reused' });
  };
  const fields = { title: '本页新名称', category: 'other', institution: '', examination_date: null, report_date: null, notes: '' };
  const files = [new File(['synthetic'], 'synthetic.png')];
  const choice = { duplicate_mode: 'reuse', duplicate_report_id: 'own-report' };
  try {
    await assert.rejects(uploadReport(fields, files, 'ask-id', true), error =>
      error instanceof DuplicateReportError && error.more && error.reports[0].id === candidate.id);
    await uploadReport(fields, files, 'reuse-id', true, choice);
    await uploadReport(fields, files, 'reuse-id', true, choice);
    await uploadReport(fields, files, 'separate-id', true, { duplicate_mode: 'separate' });
  } finally { globalThis.fetch = original; }
  assert.deepEqual(calls[1], calls[2]);
  assert.equal(calls[1].duplicate_report_id, 'own-report');
  assert.equal(calls[3].duplicate_mode, 'separate');
  assert.equal(calls[3].duplicate_report_id, undefined);
});

test('报告列表传递分页、日期搜索和待核对筛选', async () => {
  const original = globalThis.fetch;
  let url;
  globalThis.fetch = async value => { url = new URL(value, 'http://localhost'); return Response.json({ items: [] }); };
  try { await listReports({ page: 2, search: '2026-09-25', category: 'lab', pending_only: true }); }
  finally { globalThis.fetch = original; }
  assert.equal(url.pathname, '/api/v1/patient/reports');
  assert.deepEqual(Object.fromEntries(url.searchParams), { page: '2', limit: '12', search: '2026-09-25', category: 'lab', pending_only: 'true' });
});

test('信息保存发送版本号，冲突保留错误状态', async () => {
  const original = globalThis.fetch;
  let options;
  globalThis.fetch = async (_, value) => { options = value; return Response.json({ detail: '报告版本冲突' }, { status: 409 }); };
  try { await assert.rejects(editReport('report-1', { title: '本页填写' }, 2), error => error.status === 409 && error.message === '报告版本冲突'); }
  finally { globalThis.fetch = original; }
  assert.equal(options.method, 'PATCH');
  assert.deepEqual(JSON.parse(options.body), { title: '本页填写', expected_revision: 2 });
});

test('原件从本人认证接口读取 Blob，拒绝时不返回公开链接', async () => {
  const original = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => { request = { url, options }; return new Response(new Uint8Array([1, 2, 3]), { headers: { 'Content-Type': 'image/png' } }); };
  try {
    const blob = await getReportOriginal('report-1', 'file-1');
    assert.equal(blob.type, 'image/png');
    assert.deepEqual([...new Uint8Array(await blob.arrayBuffer())], [1, 2, 3]);
  } finally { globalThis.fetch = original; }
  assert.equal(request.url, '/api/v1/patient/reports/report-1/files/file-1');
  assert.equal(request.options.headers.Authorization, 'Bearer synthetic-token');
});

test('工作区任务只提交原件版本和编号，不提交原件或附件地址', async () => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return Response.json({}); };
  try {
    await getReportWorkspace('r-1');
    await extractReportText('r-1', { source_version: 2, revision: 4 }, 'stable-id');
  } finally { globalThis.fetch = original; }
  assert.equal(calls[0].url, '/api/v1/patient/reports/r-1/workspace');
  assert.deepEqual(JSON.parse(calls[1].options.body), { expected_source_version: 2, expected_workflow_revision: 4, request_id: 'stable-id' });
});

test('可编辑预览仅提交文字页，排除本地取字的文件编号和元数据', async () => {
  const original = globalThis.fetch;
  let payload;
  globalThis.fetch = async (_, options) => { payload = JSON.parse(options.body); return Response.json({}); };
  try { await previewReportText('r-1', { source_version: 1, revision: 2 }, [{ page: 1, text: 'WBC 6.2', file_id: 'private-file', filename: '姓名.png' }]); }
  finally { globalThis.fetch = original; }
  assert.deepEqual(payload, { expected_source_version: 1, expected_workflow_revision: 2, pages: [{ page: 1, text: 'WBC 6.2' }] });
});

test('AI提交显式传递逐次确认，重试保持预览绑定和同一编号', async () => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (_, options) => { calls.push(JSON.parse(options.body)); return Response.json({}); };
  const preview = { id: 'preview-1', hash: 'hash-1', source_version: 3, text: '不由浏览器重复提交正文' };
  try {
    await organizeReportText('r-1', preview, 'stable-ai-id', false, false);
    await organizeReportText('r-1', preview, 'stable-ai-id', true, true);
    await organizeReportText('r-1', preview, 'stable-ai-id', true, true);
  } finally { globalThis.fetch = original; }
  assert.equal(calls[0].consent, false); assert.equal(calls[0].ownership_confirmed, false);
  assert.deepEqual(calls[1], calls[2]);
  assert.deepEqual(calls[1], { request_id: 'stable-ai-id', preview_id: 'preview-1', preview_hash: 'hash-1', expected_source_version: 3, consent: true, ownership_confirmed: true });
});
