import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { createChatSession, historyOwner, loadChatHistory, saveChatHistory } from '../src/state/chatHistory.ts';

let storage;
beforeEach(() => {
  storage = new Map();
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
});

test('reload restores selected conversation, messages, dates and diagnosis context', () => {
  const first = createChatSession();
  const second = createChatSession();
  second.chatMode = 'diagnosed';
  second.backendSessionId = 'backend-diagnosis';
  second.reportData = { primary_diagnosis: 'test report' };
  second.messages.push({ id: 'answer', role: 'agent', content: 'saved answer', timestamp: new Date(),
    workflowSteps: [{ id: 'step', timestamp: new Date(), title: 'done', type: 'thinking', status: 'done' }] });
  saveChatHistory('user:1', { version: 1, currentSessionId: second.id, sessions: [first, second] });
  const loaded = loadChatHistory('user:1');
  assert.equal(loaded.currentSessionId, second.id);
  assert.equal(loaded.sessions.length, 2);
  assert.equal(loaded.sessions[1].backendSessionId, 'backend-diagnosis');
  assert.equal(loaded.sessions[1].reportData.primary_diagnosis, 'test report');
  assert(loaded.sessions[1].messages[1].timestamp instanceof Date);
  assert(loaded.sessions[1].messages[1].workflowSteps[0].timestamp instanceof Date);
});

test('legacy MedicareAI history migrates into the MedAxis namespace', () => {
  const session = createChatSession();
  const legacyKey = 'medicareai.chat-history.v1:user:legacy';
  const currentKey = 'medaxis.chat-history.v1:user:legacy';
  storage.set(legacyKey, JSON.stringify({ version: 1, currentSessionId: session.id, sessions: [session] }));
  const loaded = loadChatHistory('user:legacy');
  assert.equal(loaded.sessions[0].id, session.id);
  assert.ok(storage.has(currentKey));
  assert.equal(storage.has(legacyKey), false);
});

test('pending interview retains its backend ID and answered questions across reload', () => {
  const session = createChatSession();
  session.chatMode = 'consulting';
  session.pendingSession = { sessionId: 'backend-1', questionId: 'q2' };
  session.answeredIds = ['q1'];
  session.messages.push({ id: 'question', role: 'agent', content: '', timestamp: new Date(), isStreaming: true,
    interviewQuestions: [{ question_id: 'q2', question: 'test question', type: 'text' }] });
  saveChatHistory('guest:1', { version: 1, currentSessionId: session.id, sessions: [session] });
  const restored = loadChatHistory('guest:1').sessions[0];
  assert.equal(restored.chatMode, 'consulting');
  assert.deepEqual(restored.pendingSession, session.pendingSession);
  assert.deepEqual(restored.answeredIds, ['q1']);
  assert.equal(restored.messages[1].isStreaming, false);
  assert.equal(restored.messages[1].interviewQuestions[0].question_id, 'q2');
});

test('interrupted initial response unlocks input without discarding partial messages', () => {
  const session = createChatSession();
  session.chatMode = 'consulting';
  session.interrupted = true;
  session.pendingSession = { sessionId: '', questionId: 'q1' };
  session.messages.push({ id: 'partial', role: 'agent', content: 'partial text', timestamp: new Date(), isStreaming: true });
  saveChatHistory('user:1', { version: 1, currentSessionId: session.id, sessions: [session] });
  const restored = loadChatHistory('user:1').sessions[0];
  assert.equal(restored.chatMode, 'idle');
  assert.equal(restored.pendingSession, null);
  assert.equal(restored.messages[1].content, 'partial text');
  assert.equal(restored.messages[1].isStreaming, false);
  assert.equal(restored.interrupted, true);
});

test('only uploads with a server file ID remain eligible for resumed polling', () => {
  const session = createChatSession();
  session.messages = ['pending', 'uploaded'].map(id => ({ id, role: 'agent', content: '', timestamp: new Date(),
    uploadStatus: 'processing', uploadFileId: id === 'uploaded' ? 'file-1' : undefined }));
  saveChatHistory('user:1', { version: 1, currentSessionId: session.id, sessions: [session] });
  const restored = loadChatHistory('user:1').sessions[0];
  assert.equal(restored.messages[0].uploadStatus, 'failed');
  assert.equal(restored.messages[1].uploadStatus, 'processing');
  assert.equal(restored.messages[1].uploadFileId, 'file-1');
});

test('users and guests never share local history', () => {
  const session = createChatSession();
  session.title = 'private';
  saveChatHistory('user:1', { version: 1, currentSessionId: session.id, sessions: [session] });
  for (const owner of ['user:2', 'guest:1']) assert.notEqual(loadChatHistory(owner).sessions[0].id, session.id);
  assert.equal(loadChatHistory('user:1').sessions[0].title, 'private');
  const token = expiry => `header.${Buffer.from(JSON.stringify({ sub: '1', exp: expiry })).toString('base64url')}.signature`;
  assert.equal(historyOwner(token(1), 'user'), historyOwner(token(2), 'user'));
  assert.notEqual(historyOwner(token(1), 'user'), historyOwner(token(1), 'guest'));
});

test('corrupted storage and quota failures are reported without overwriting old data', () => {
  const key = 'medaxis.chat-history.v1:user:1';
  storage.set(key, '{broken json');
  assert.throws(() => loadChatHistory('user:1'));
  assert.equal(storage.get(key), '{broken json');
  globalThis.localStorage.setItem = () => { throw new Error('QuotaExceededError'); };
  assert.throws(() => saveChatHistory('user:1', {}), /QuotaExceededError/);
});
