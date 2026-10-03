import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ProfileSaveError, updateProfile } from '../src/api/patient.ts';

globalThis.localStorage = { getItem: key => key === 'access_token' ? 'test-access-token' : null };

test('profile update sends only fields supported by the patient profile API', async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url: String(url), options };
    return Response.json({ id: 'patient-1', name: '合成患者' });
  };

  try {
    await updateProfile({
      id: 'patient-1', name: '合成患者', email: 'synthetic@example.invalid',
      date_of_birth: '2000-01-01', phone: '13800000000', gender: 'female',
      height: 165, weight: 60, allergies: ['花粉'],
      chronic_diseases: [{ code: 'E11', name: '2型糖尿病' }],
      medications: [{ name: '示例药物', dosage: '1片', frequency: '每日一次' }],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(request.url, '/api/v1/patient/profile');
  assert.equal(request.options.method, 'PATCH');
  assert.deepEqual(JSON.parse(request.options.body), {
    name: '合成患者', phone: '13800000000', gender: 'female', height: 165, weight: 60,
    allergies: ['花粉'], chronic_diseases: [{ code: 'E11', name: '2型糖尿病' }],
    medications: [{ name: '示例药物', dosage: '1片', frequency: '每日一次' }],
  });
});

test('profile update propagates server errors for the page to keep the draft and show an error', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 500 });
  try {
    await assert.rejects(updateProfile({ name: '合成患者' }), /Failed to update profile/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('档案版本、记录状态、疾病详情和停用标记按原值发送', async () => {
  const originalFetch = globalThis.fetch;
  const payload = {
    expected_revision: 7,
    section_states: { allergies: 'unknown', conditions: 'present', medications: 'present' },
    chronic_diseases: [{ name: '合成特殊疾病', category: 'special', severity: 'severe', diagnosed_date: '2020-01-02', notes: '患者自报说明' }],
    medications: [{ name: '合成药物', dosage: '', frequency: '', status: 'stopped' }],
  };
  globalThis.fetch = async (_url, options) => {
    assert.deepEqual(JSON.parse(options.body), payload);
    return Response.json({ revision: 8 });
  };
  try { assert.equal((await updateProfile(payload)).revision, 8); }
  finally { globalThis.fetch = originalFetch; }
});

test('版本冲突保留可识别的状态码和服务器说明', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ detail: '档案已被更新' }, { status: 409 });
  try {
    await assert.rejects(updateProfile({ expected_revision: 1 }), error => error instanceof ProfileSaveError && error.status === 409 && error.message === '档案已被更新');
  } finally { globalThis.fetch = originalFetch; }
});
