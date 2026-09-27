import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createChatSession, removeChatSession, saveChatHistory, loadChatHistory } from '../src/state/chatHistory.ts';
import { patientText } from '../src/state/patientText.ts';

test('删除当前聊天后创建新聊天，刷新仍不恢复已删除聊天，其他聊天保持完整', () => {
  const data = new Map();
  globalThis.localStorage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
  const a = { ...createChatSession(), id: 'a', reportCaseId: 'saved-case', backendSessionId: 'server-session' };
  const b = { ...createChatSession(), id: 'b' };
  const original = { version: 1, currentSessionId: 'a', sessions: [a, b] };
  const next = removeChatSession(original, 'a');
  saveChatHistory('user:review', next);
  const reloaded = loadChatHistory('user:review');
  assert.equal(reloaded.sessions.some(item => item.id === 'a'), false);
  assert.equal(reloaded.sessions.some(item => item.id === reloaded.currentSessionId), true);
  assert.equal(reloaded.sessions.find(item => item.id === 'b').id, 'b');
  assert.equal(original.sessions[0].reportCaseId, 'saved-case');
  assert.equal(original.sessions[0].backendSessionId, 'server-session');
});

test('删除非当前聊天不改变当前选择，重复删除无副作用', () => {
  const original = { version: 1, currentSessionId: 'a', sessions: [{ ...createChatSession(), id: 'a' }, { ...createChatSession(), id: 'b' }] };
  const next = removeChatSession(original, 'b');
  assert.equal(next.currentSessionId, 'a');
  assert.equal(next.sessions.length, 1);
  assert.equal(removeChatSession(next, 'b'), next);
});

test('旧报告隐藏标识及调试计数，保留缺少依据的说明和医学数值', () => {
  const text = '可能是 IBS-D（ICD-11: DD91.0）。患者ID：95bb18ce-6d49-4d2a-8059-52e958688fcd\n未检索到资料（retrieved_chunks=0，internal_sources=0，external_sources=0）。体温 38.5°C，血糖 5.6 mmol/L。';
  const output = patientText(text);
  assert.match(output, /腹泻型肠易激综合征/);
  assert.doesNotMatch(output, /ICD|DD91|95bb18ce|retrieved_chunks|internal_sources|external_sources/);
  assert.match(output, /未检索到资料/);
  assert.match(output, /38\.5°C/);
  assert.match(output, /5\.6 mmol\/L/);
  assert.equal(patientText(output), output);
  assert.equal(patientText('腹泻型肠易激综合征（IBS-D）'), '腹泻型肠易激综合征');
});
