import assert from 'node:assert/strict';
import { test } from 'node:test';
import { getCaseRecovery, listCases } from '../src/api/patient.ts';
import { initialCaseSelection, mergeCasePage, shouldPollCaseMaterials } from '../src/state/patientCases.ts';

globalThis.localStorage = { getItem: () => null };

test('case list requests one bounded page at a time', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl;
  globalThis.fetch = async url => {
    requestedUrl = String(url);
    return Response.json([]);
  };

  try {
    await listCases({ page: 2, limit: 10 });
  } finally {
    globalThis.fetch = originalFetch;
  }

  const url = new URL(requestedUrl, 'http://localhost');
  assert.equal(url.pathname, '/api/v1/patient/cases');
  assert.equal(url.searchParams.get('page'), '2');
  assert.equal(url.searchParams.get('limit'), '10');
});

test('case URL controls selection and removing it returns to the first loaded case', () => {
  assert.equal(initialCaseSelection('older-case', [{ id: 'newest-case' }]), 'older-case');
  // 浏览器后退移除 case_id 后，选择回到当前已加载列表的首条。
  assert.equal(initialCaseSelection(null, [{ id: 'newest-case' }]), 'newest-case');
});

test('recovery API requests a case ID directly without requiring list membership', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl;
  globalThis.fetch = async url => {
    requestedUrl = String(url);
    return Response.json({ case: { id: 'older-case' }, report: null, lab_reports: [], materials: [] });
  };

  try {
    const result = await getCaseRecovery('older-case');
    assert.equal(result.case.id, 'older-case');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestedUrl, '/api/v1/patient/cases/older-case/recovery');
});

test('loading another case page appends without duplicating an overlapping ID', () => {
  const firstPage = [{ id: 'case-10', title: 'ten' }, { id: 'case-9', title: 'nine' }];
  const nextPage = [
    { id: 'case-9', title: 'duplicate' },
    { id: 'case-8', title: 'eight' },
    { id: 'case-8', title: 'duplicate in response' },
  ];
  assert.deepEqual(mergeCasePage(firstPage, nextPage), [
    { id: 'case-10', title: 'ten' },
    { id: 'case-9', title: 'nine' },
    { id: 'case-8', title: 'eight' },
  ]);
});

test('case recovery polls only while materials are queued or processing and stops at its limit', () => {
  assert.equal(shouldPollCaseMaterials([{ status: 'queued' }], 1), true);
  assert.equal(shouldPollCaseMaterials([{ status: 'processing' }], 79), true);
  assert.equal(shouldPollCaseMaterials([{ status: 'completed' }, { status: 'failed' }], 1), false);
  assert.equal(shouldPollCaseMaterials([{ status: 'processing' }], 80), false);
});
