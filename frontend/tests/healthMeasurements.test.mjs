import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createMeasurement, listMeasurements } from '../src/api/measurements.ts';

globalThis.localStorage = { getItem: key => key === 'access_token' ? 'synthetic-token' : null };

test('健康指标请求保留记录时间、零缺失值和重复提交ID，不修改档案', async () => {
  const original = globalThis.fetch;
  const calls = [];
  const fields = { systolic: 128, diastolic: 82, heart_rate: null, weight: 62.5, recorded_at: '2026-10-02T23:30:00Z' };
  globalThis.fetch = async (url, options) => { calls.push({ url: String(url), ...options }); return Response.json({ id: 'stable-id', ...fields }); };
  try {
    await createMeasurement(fields, 'stable-id');
    await createMeasurement(fields, 'stable-id');
    assert.equal(calls.length, 2);
    for (const call of calls) {
      assert.match(call.url, /\/patient\/measurements$/);
      assert.equal(call.method, 'POST');
      assert.equal(call.headers.Authorization, 'Bearer synthetic-token');
      assert.deepEqual(JSON.parse(call.body), { ...fields, request_id: 'stable-id' });
    }
  } finally { globalThis.fetch = original; }
});

test('历史记录按页请求，拒绝缺少分页字段的响应', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async url => { assert.equal(new URL(String(url), 'http://test').searchParams.get('page'), '2'); return Response.json({ items: [], has_more: false }); };
    assert.deepEqual(await listMeasurements(2), { items: [], has_more: false });
    for (const invalid of [{}, { items: null, has_more: false }, { items: [], has_more: 'false' }]) {
      globalThis.fetch = async () => Response.json(invalid);
      await assert.rejects(listMeasurements(), /健康指标暂时无法读取/);
    }
  } finally { globalThis.fetch = original; }
});

test('保存冲突和非JSON故障显式失败，不返回成功记录', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ detail: '记录请求已使用，请重新核对并提交' }, { status: 409 });
    await assert.rejects(createMeasurement({}, 'id'), /记录请求已使用/);
    globalThis.fetch = async () => new Response('unavailable', { status: 503 });
    await assert.rejects(listMeasurements(), /健康指标操作失败/);
  } finally { globalThis.fetch = original; }
});
