import assert from 'node:assert/strict';
import { test } from 'node:test';
import { getReportLinks, listCaseReports, listReportCaseOptions, ReportError, saveReportLinks } from '../src/api/reports.ts';
import { acceptLinksWorkspace } from '../src/state/reportLinks.ts';

test('来源、核对与关联是独立修订，任何旧刷新不能撤回已显示的新状态', () => {
  const latest={links_revision:4,review_revision:7,source_epoch:3,items:[]};
  assert.equal(acceptLinksWorkspace(latest,{...latest,links_revision:3}),latest);
  assert.equal(acceptLinksWorkspace(latest,{...latest,review_revision:6}),latest);
  assert.equal(acceptLinksWorkspace(latest,{...latest,source_epoch:2}),latest);
  const newer={...latest,source_epoch:4};assert.equal(acceptLinksWorkspace(latest,newer),newer);
});

test('病例关联绑定独立修订/来源/核对版本，重试同编号同正文，更新来源仅指定病例', async () => {
  globalThis.localStorage = { getItem: () => 'synthetic-token' };
  const original = globalThis.fetch, calls=[];
  globalThis.fetch=async(url,init)=>{calls.push({url,body:init.body && JSON.parse(init.body)});return new Response('{}',{status:200});};
  try {
    const workspace={links_revision:2,review_revision:7,source_hash:'a'.repeat(64)};
    await saveReportLinks('report',workspace,['case-a','case-b'],['case-a'],'same-request');
    await saveReportLinks('report',workspace,['case-a','case-b'],['case-a'],'same-request');
    assert.deepEqual(calls[0],calls[1]);
    assert.deepEqual(calls[0].body,{request_id:'same-request',expected_links_revision:2,expected_review_revision:7,
      expected_source_hash:'a'.repeat(64),case_ids:['case-a','case-b'],refresh_case_ids:['case-a']});
    assert.equal('content' in calls[0].body,false);
    await getReportLinks('report'); await listReportCaseOptions('report','合成病例',2); await listCaseReports('case-a',3);
    assert.match(calls[3].url,/case-options\?search=/); assert.match(calls[3].url,/page=2/);
    assert.match(calls[4].url,/patient\/cases\/case-a\/reports\?page=3/);
  } finally {globalThis.fetch=original;}
});

test('关联409显式抛出，不能当成已保存或自动改基线再提交', async () => {
  globalThis.localStorage = { getItem: () => 'synthetic-token' };
  const original = globalThis.fetch;
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:'来源已变化'}),{status:409});
  try {
    await assert.rejects(()=>saveReportLinks('report',{links_revision:0,review_revision:0,source_hash:'a'.repeat(64)},[],[],'request'),
      error=>error instanceof ReportError && error.status===409 && error.message==='来源已变化');
  } finally {globalThis.fetch=original;}
});
