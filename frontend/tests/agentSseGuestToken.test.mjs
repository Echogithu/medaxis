import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { streamDiagnose, streamDiagnoseContinue } from '../src/api/agent.ts';

let storage;
let fetchCalls;

function sseResponse(events = ['event: complete\ndata: {}\n\n']) {
  return new Response(events.join(''), { status: 200 });
}

beforeEach(() => {
  storage = new Map();
  fetchCalls = [];
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
  globalThis.fetch = async (url, options) => {
    fetchCalls.push({ url: String(url), options });
    if (String(url).endsWith('/auth/guest')) {
      return new Response(JSON.stringify({
        session_token: 'bootstrapped-guest-token',
        message_count: 0,
        max_messages: 2,
      }), { status: 201, headers: { 'Content-Type': 'application/json' } });
    }
    return sseResponse();
  };
});

test('creates a guest session and keeps credentials and patient text out of the SSE URL', async () => {
  await streamDiagnose({
    message: '合成患者主诉',
    patient_history: '既往合成病史',
    submission_id: '08d7d595-1c9e-46a0-94df-819ea0461034',
  }, () => {});

  assert.equal(fetchCalls.length, 2);
  const guestCall = fetchCalls[0];
  const sseCall = fetchCalls[1];
  assert.match(guestCall.url, /\/auth\/guest$/);
  assert.equal(guestCall.options.method, 'POST');
  assert.equal(localStorage.getItem('guest_token'), 'bootstrapped-guest-token');
  assert.equal(sseCall.url, '/api/v1/agents/route/stream');
  assert.equal(sseCall.options.method, 'POST');
  assert.equal(sseCall.options.headers['X-Guest-Token'], 'bootstrapped-guest-token');
  assert.equal(
    sseCall.options.headers['Idempotency-Key'],
    '08d7d595-1c9e-46a0-94df-819ea0461034',
  );
  assert.deepEqual(JSON.parse(sseCall.options.body), {
    message: '合成患者主诉',
    patient_history: '既往合成病史',
  });
});

test('does not replace a stored guest token with an empty SSE value', async () => {
  localStorage.setItem('guest_token', 'existing-guest-token');
  globalThis.fetch = async (url, options) => {
    fetchCalls.push({ url: String(url), options });
    return sseResponse([
      'event: guest_token\ndata: {"guest_token":""}\n\n',
      'event: complete\ndata: {}\n\n',
    ]);
  };

  await streamDiagnose({ message: '合成患者主诉' }, () => {});

  assert.equal(localStorage.getItem('guest_token'), 'existing-guest-token');
});

test('stores a legacy guest_token event without changing the fetch SSE path', async () => {
  localStorage.setItem('guest_token', 'existing-guest-token');
  const events = [];
  globalThis.fetch = async (url, options) => {
    fetchCalls.push({ url: String(url), options });
    return sseResponse([
      'event: guest_token\ndata: {"guest_token":"refreshed-guest-token"}\n\n',
      'event: complete\ndata: {}\n\n',
    ]);
  };

  await streamDiagnose({ message: '合成患者主诉' }, event => events.push(event));

  assert.equal(localStorage.getItem('guest_token'), 'refreshed-guest-token');
  assert.deepEqual(events[0], {
    event: 'guest_token',
    data: { guest_token: 'refreshed-guest-token' },
  });
  assert.equal(fetchCalls[0].url, '/api/v1/agents/route/stream');
});

test('retries an initial stream transport failure with the same submission key and body', async () => {
  localStorage.setItem('guest_token', 'existing-guest-token');
  const submissionId = '06d06d9d-01f6-40df-a055-4b9d60284cab';
  globalThis.fetch = async (url, options) => {
    fetchCalls.push({ url: String(url), options });
    if (fetchCalls.length === 1) throw new TypeError('synthetic network failure');
    return sseResponse();
  };

  await streamDiagnose({ message: '合成患者主诉', submission_id: submissionId }, () => {});

  assert.equal(fetchCalls.length, 2);
  assert.equal(fetchCalls[0].url, fetchCalls[1].url);
  assert.equal(fetchCalls[0].options.headers['Idempotency-Key'], submissionId);
  assert.equal(fetchCalls[1].options.headers['Idempotency-Key'], submissionId);
  assert.equal(fetchCalls[0].options.body, fetchCalls[1].options.body);
});

test('retries a fetch transport failure with the same continuation idempotency key', async () => {
  localStorage.setItem('guest_token', 'existing-guest-token');
  const submissionId = 'cd47d5c1-5e2b-4f73-a38b-267942548ffb';
  globalThis.fetch = async (url, options) => {
    fetchCalls.push({ url: String(url), options });
    if (fetchCalls.length === 1) throw new TypeError('synthetic network failure');
    return sseResponse();
  };

  await streamDiagnoseContinue({
    session_id: 'synthetic-session',
    question_id: 'synthetic-question',
    answer: '合成回答',
    submission_id: submissionId,
  }, () => {});

  assert.equal(fetchCalls.length, 2);
  assert.equal(fetchCalls[0].options.headers['Idempotency-Key'], submissionId);
  assert.equal(fetchCalls[1].options.headers['Idempotency-Key'], submissionId);
  assert.equal(fetchCalls[0].url, '/api/v1/agents/route/stream/continue?session_id=synthetic-session&question_id=synthetic-question');
  assert.equal(fetchCalls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(fetchCalls[0].options.body), { answer: '合成回答' });
  assert.equal(fetchCalls[0].options.headers['X-Answer'], undefined);
  assert.equal(fetchCalls[0].options.body, fetchCalls[1].options.body);
});
