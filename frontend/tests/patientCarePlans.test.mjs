import assert from 'node:assert/strict';
import { test } from 'node:test';
import { listCarePlanPage, createCarePlan, editCarePlan, changeCarePlan, checkInCareTask } from '../src/api/patient.ts';

globalThis.localStorage = { getItem: key => key === 'access_token' ? 'synthetic-token' : null };
const fields = { title: '患者随访', description: '', source_case_id: null, start_date: '2026-10-02', end_date: '2026-10-03',
  tasks: [{ type: 'self_check', description: '自测', due_date: '2026-10-03', unit: '单位' }] };

test('创建、编辑、确认和自测请求保留契约与幂等ID', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({url:String(url), ...options}); return Response.json({ id: 'plan', revision: 2 }); };
  try {
    await createCarePlan(fields, 'stable-request');
    await editCarePlan('plan /中文', fields, 1);
    await changeCarePlan({id:'plan',revision:2}, 'pause');
    await checkInCareTask('plan','task','自报备注',0);
    assert.deepEqual(JSON.parse(calls[0].body), { ...fields, request_id: 'stable-request' });
    assert.equal(calls[0].method,'POST');
    assert.match(calls[1].url,/plan%20%2F%E4%B8%AD%E6%96%87/);
    assert.deepEqual(JSON.parse(calls[1].body), { ...fields, expected_revision: 1 });
    assert.deepEqual(JSON.parse(calls[2].body), { action:'pause', expected_revision:2 });
    assert.deepEqual(JSON.parse(calls[3].body), { plan_id:'plan',task_id:'task',notes:'自报备注',value:0 });
    assert.equal(calls[0].headers.Authorization,'Bearer synthetic-token');
  } finally { globalThis.fetch=original; }
});

test('分页请求传递状态及完整游标', async () => {
  const original=globalThis.fetch;
  globalThis.fetch=async url => {
    const params=new URL(String(url),'http://test').searchParams;
    assert.equal(params.get('status'),'expired'); assert.equal(params.get('include_page'),'true');
    assert.equal(params.get('cursor_at'),'2026-10-02T01:00:00+08:00'); assert.equal(params.get('cursor_id'),'id');
    return Response.json({items:[],next_cursor:null});
  };
  try { assert.deepEqual(await listCarePlanPage({status:'expired',cursor:{created_at:'2026-10-02T01:00:00+08:00',id:'id'}}),{items:[],next_cursor:null}); }
  finally { globalThis.fetch=original; }
});

test('冲突和验证失败保留可理解的错误，不伪成功', async () => {
  const original=globalThis.fetch;
  try {
    globalThis.fetch=async ()=>Response.json({detail:'计划已被更新，请重新加载后操作'},{status:409});
    await assert.rejects(changeCarePlan({id:'plan',revision:1},'confirm'),/计划已被更新/);
    globalThis.fetch=async ()=>Response.json({detail:[{msg:'invalid'}]},{status:422});
    await assert.rejects(createCarePlan(fields,'id'),/HTTP 422/);
  } finally { globalThis.fetch=original; }
});
