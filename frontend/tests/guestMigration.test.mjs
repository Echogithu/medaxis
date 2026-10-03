import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { completeGuestMigration } from '../src/auth/guestMigration.ts';
import { createChatSession, loadChatHistory, saveChatHistory } from '../src/state/chatHistory.ts';

let storage;
const guestToken = token('guest-1');
const userToken = token('user-1');

beforeEach(() => {
  storage = new Map();
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
  localStorage.setItem('access_token', userToken);
});

function token(sub) {
  return `header.${Buffer.from(JSON.stringify({ sub })).toString('base64url')}.signature`;
}

test('successful migration merges local guest history, preserves pending work, then clears guest state', async () => {
  const guestSession = createChatSession();
  guestSession.title = '访客问诊';
  guestSession.backendSessionId = 'backend-session-1';
  guestSession.chatMode = 'consulting';
  guestSession.pendingSession = { sessionId: 'backend-session-1', questionId: 'q2' };
  guestSession.answeredIds = ['q1'];
  saveChatHistory('guest:guest-1', { version: 1, currentSessionId: guestSession.id, sessions: [guestSession] });

  const duplicate = createChatSession();
  duplicate.title = '旧缓存副本';
  duplicate.backendSessionId = 'backend-session-1';
  const existing = createChatSession();
  existing.title = '已有账户记录';
  saveChatHistory('user:user-1', {
    version: 1, currentSessionId: existing.id, sessions: [duplicate, existing],
  });
  localStorage.setItem('guest_token', guestToken);
  localStorage.setItem('guest_status', '{"remaining":1}');

  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return Response.json({ migrated: 1 });
  };

  assert.equal(await completeGuestMigration(), 1);
  assert.equal(request.url, '/api/v1/auth/guest/migrate');
  assert.equal(request.init.method, 'POST');
  assert.equal(request.init.headers.Authorization, `Bearer ${userToken}`);
  assert.equal(request.init.headers['X-Guest-Token'], guestToken);

  const migrated = loadChatHistory('user:user-1');
  assert.equal(migrated.sessions.length, 2);
  assert.equal(migrated.currentSessionId, guestSession.id);
  assert.equal(migrated.sessions.find(item => item.id === guestSession.id).title, '访客问诊');
  assert.deepEqual(migrated.sessions.find(item => item.id === guestSession.id).pendingSession,
    guestSession.pendingSession);
  assert.equal(migrated.sessions.find(item => item.id === existing.id).title, '已有账户记录');
  assert.equal(localStorage.getItem('guest_token'), null);
  assert.equal(localStorage.getItem('guest_status'), null);
  assert.equal(localStorage.getItem('medaxis.chat-history.v1:guest:guest-1'), null);
});

test('server migration failure keeps guest credentials and local history for retry', async () => {
  const guestSession = createChatSession();
  saveChatHistory('guest:guest-1', { version: 1, currentSessionId: guestSession.id, sessions: [guestSession] });
  localStorage.setItem('guest_token', guestToken);
  localStorage.setItem('guest_status', '{"remaining":1}');
  globalThis.fetch = async () => Response.json({ detail: 'temporary failure' }, { status: 500 });

  await assert.rejects(completeGuestMigration(), /temporary failure/);
  assert.equal(localStorage.getItem('guest_token'), guestToken);
  assert.notEqual(localStorage.getItem('medaxis.chat-history.v1:guest:guest-1'), null);
  assert.equal(localStorage.getItem('medaxis.chat-history.v1:user:user-1'), null);
});

test('local copy failure can retry after the backend migration already succeeded', async () => {
  const guestSession = createChatSession();
  saveChatHistory('guest:guest-1', { version: 1, currentSessionId: guestSession.id, sessions: [guestSession] });
  localStorage.setItem('guest_token', guestToken);
  const userKey = 'medaxis.chat-history.v1:user:user-1';
  const setItem = localStorage.setItem;
  let failFirstUserWrite = true;
  localStorage.setItem = (key, value) => {
    if (key === userKey && failFirstUserWrite) {
      failFirstUserWrite = false;
      throw new Error('QuotaExceededError');
    }
    setItem(key, value);
  };
  let requestCount = 0;
  globalThis.fetch = async () => Response.json({ migrated: requestCount++ === 0 ? 1 : 0 });

  await assert.rejects(completeGuestMigration(), /QuotaExceededError/);
  assert.equal(localStorage.getItem('guest_token'), guestToken);
  assert.notEqual(localStorage.getItem('medaxis.chat-history.v1:guest:guest-1'), null);

  assert.equal(await completeGuestMigration(), 0);
  assert.equal(requestCount, 2);
  assert.equal(loadChatHistory('user:user-1').sessions[0].id, guestSession.id);
  assert.equal(localStorage.getItem('guest_token'), null);
  assert.equal(localStorage.getItem('medaxis.chat-history.v1:guest:guest-1'), null);
});
