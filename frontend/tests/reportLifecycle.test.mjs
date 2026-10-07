import assert from 'node:assert/strict';
import { test } from 'node:test';
import { changeReportLifecycle, getReportLifecycle, listReports } from '../src/api/reports.ts';

globalThis.localStorage = { getItem: () => 'synthetic-token' };

test('回收站列表与影响查询走本人接口，不触发整理', async () => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return Response.json({}); };
  try { await listReports({ archive: 'trash', search: '合成报告' }); await getReportLifecycle('r/1'); }
  finally { globalThis.fetch = original; }
  const query = new URL(calls[0].url, 'http://localhost');
  assert.equal(query.searchParams.get('archive'), 'trash');
  assert.equal(calls[1].url, '/api/v1/patient/reports/r%2F1/lifecycle');
  assert.equal(calls[1].options.headers.Authorization, 'Bearer synthetic-token');
});

test('恢复不携带外发同意；彻底删除单独确认，原编号和状态token重试不变', async () => {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, body: JSON.parse(options.body) }); return Response.json({}); };
  try {
    await changeReportLifecycle('r1', 'restore', 'state', 'restore-id');
    await changeReportLifecycle('r1', 'purge', 'state', 'purge-id', false);
    await changeReportLifecycle('r1', 'purge', 'state', 'purge-id', true);
    await changeReportLifecycle('r1', 'purge', 'state', 'purge-id', true);
  } finally { globalThis.fetch = original; }
  assert.deepEqual(calls[0].body, { request_id: 'restore-id', expected_state_token: 'state' });
  assert.equal(calls[1].body.confirmed_permanent_delete, false);
  assert.deepEqual(calls[2], calls[3]);
  assert.deepEqual(calls[2].body, { request_id: 'purge-id', expected_state_token: 'state', confirmed_permanent_delete: true });
});

test('管理冲突与已删除响应显式抛出，不伪成功', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ detail: '状态已变化，未执行' }, { status: 409 });
  try { await assert.rejects(changeReportLifecycle('r1', 'trash', 'old', 'id'), error => error.status === 409); }
  finally { globalThis.fetch = original; }
});
