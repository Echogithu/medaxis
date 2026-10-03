import type { ChatMessageItem, ChatSession, DiagnosisReport } from '../types/agent';
import { recoverReportSources } from './reportCitations.ts';

export type ChatMode = 'idle' | 'consulting' | 'diagnosed';

export interface SavedChatSession extends ChatSession {
  messages: ChatMessageItem[];
  chatMode: ChatMode;
  reportData: DiagnosisReport | null;
  reportCaseId?: string | null;
  backendSessionId: string | null;
  pendingSession: { sessionId: string; questionId: string } | null;
  answeredIds: string[];
  interrupted?: boolean;
}

export interface ChatHistory {
  version: 1;
  currentSessionId: string;
  sessions: SavedChatSession[];
}

export function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export function createChatSession(): SavedChatSession {
  const now = new Date();
  return {
    id: generateId(), title: '新对话',
    created_at: now.toISOString(), updated_at: now.toISOString(), message_count: 0,
    messages: [{
      id: generateId(), role: 'agent', timestamp: now,
      content: '你好，今天哪里不舒服？你也可以上传检查报告。',
    }],
    chatMode: 'idle', reportData: null, reportCaseId: null, backendSessionId: null,
    pendingSession: null, answeredIds: [],
  };
}

// Only used to scope local UI history. Authentication still happens on the server.
export function historyOwner(token: string, kind: 'user' | 'guest'): string {
  const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
  const { sub } = JSON.parse(atob(part.padEnd(Math.ceil(part.length / 4) * 4, '=')));
  if (typeof sub !== 'string' || !sub) throw new Error('无法识别会话所属身份');
  return `${kind}:${sub}`;
}

function storageKey(owner: string): string {
  return `medaxis.chat-history.v1:${owner}`;
}

function legacyStorageKey(owner: string): string {
  return `medicareai.chat-history.v1:${owner}`;
}

function restoreSession(session: SavedChatSession): SavedChatSession {
  if (!session.id || !Array.isArray(session.messages) || !Array.isArray(session.answeredIds)
      || !['idle', 'consulting', 'diagnosed'].includes(session.chatMode)) {
    throw new Error('无效的会话历史');
  }
  const messages = session.messages.map(message => ({
    ...message,
    timestamp: new Date(message.timestamp),
    isStreaming: false,
    workflowSteps: message.workflowSteps?.map(step => ({ ...step, timestamp: new Date(step.timestamp) })),
    // Uploads with a server file ID can resume polling after a reload.
    ...(message.uploadStatus === 'processing' && !message.uploadFileId ? {
      uploadStatus: 'failed' as const,
      uploadError: '上传已中断，请重新上传文件',
    } : {}),
  }));
  if (messages.some(message => Number.isNaN(message.timestamp.getTime()))) {
    throw new Error('无效的消息时间');
  }
  const pendingSession = session.pendingSession?.sessionId ? session.pendingSession : null;
  const hasPendingQuestions = messages.some(message =>
    [...(message.interviewQuestions || []), ...(message.interviewQuestion ? [message.interviewQuestion] : [])]
      .some(question => !session.answeredIds.includes(question.question_id)));
  // An interrupted first response must not leave the input permanently hidden.
  const chatMode = session.chatMode === 'consulting' && (!pendingSession || !hasPendingQuestions) ? 'idle' : session.chatMode;
  return { ...session, messages, pendingSession, chatMode, reportData: recoverReportSources(session.reportData, messages) };
}

export function loadChatHistory(owner: string): ChatHistory {
  const key = storageKey(owner);
  const legacyKey = legacyStorageKey(owner);
  const raw = localStorage.getItem(key) ?? localStorage.getItem(legacyKey);
  if (raw) {
    const history: ChatHistory = JSON.parse(raw);
    if (history.version !== 1 || !Array.isArray(history.sessions)) throw new Error('无法读取会话历史');
    const sessions = history.sessions.map(restoreSession);
    if (sessions.length) {
      const migratedHistory = {
        version: 1 as const, sessions,
        currentSessionId: sessions.some(session => session.id === history.currentSessionId)
          ? history.currentSessionId : sessions[0].id,
      };
      if (!localStorage.getItem(key)) {
        localStorage.setItem(key, JSON.stringify(migratedHistory));
        localStorage.removeItem(legacyKey);
      }
      return migratedHistory;
    }
  }
  const session = createChatSession();
  return { version: 1, currentSessionId: session.id, sessions: [session] };
}

export function saveChatHistory(owner: string, history: ChatHistory): void {
  localStorage.setItem(storageKey(owner), JSON.stringify(history));
}

/**
 * 将访客浏览器历史并入账户历史。只有目标副本写入成功后才删除访客副本。
 */
export function migrateGuestChatHistory(guestToken: string, userToken: string): void {
  const guestOwner = historyOwner(guestToken, 'guest');
  const userOwner = historyOwner(userToken, 'user');
  const guestKey = storageKey(guestOwner);
  const guestLegacyKey = legacyStorageKey(guestOwner);
  if (!localStorage.getItem(guestKey) && !localStorage.getItem(guestLegacyKey)) return;

  const guestHistory = loadChatHistory(guestOwner);
  const userKey = storageKey(userOwner);
  const userLegacyKey = legacyStorageKey(userOwner);
  const hasUserHistory = Boolean(localStorage.getItem(userKey) || localStorage.getItem(userLegacyKey));
  const userHistory = hasUserHistory ? loadChatHistory(userOwner) : null;

  const sessions: SavedChatSession[] = [];
  const seenIds = new Set<string>();
  const seenBackendIds = new Set<string>();
  for (const session of [...guestHistory.sessions, ...(userHistory?.sessions || [])]) {
    if (seenIds.has(session.id)
        || (session.backendSessionId && seenBackendIds.has(session.backendSessionId))) continue;
    seenIds.add(session.id);
    if (session.backendSessionId) seenBackendIds.add(session.backendSessionId);
    sessions.push(session);
  }

  const currentSessionId = sessions.some(session => session.id === guestHistory.currentSessionId)
    ? guestHistory.currentSessionId
    : userHistory?.currentSessionId && sessions.some(session => session.id === userHistory.currentSessionId)
      ? userHistory.currentSessionId
      : sessions[0].id;
  saveChatHistory(userOwner, { version: 1, currentSessionId, sessions });
  localStorage.removeItem(guestKey);
  localStorage.removeItem(guestLegacyKey);
}

/** 只移除浏览器聊天记录，服务端问诊报告和资料独立保留。 */
export function removeChatSession(history: ChatHistory, id: string): ChatHistory {
  if (!history.sessions.some(session => session.id === id)) return history;
  const sessions = history.sessions.filter(session => session.id !== id);
  if (history.currentSessionId !== id) return { ...history, sessions };
  if (sessions.length > 0) {
    return { ...history, currentSessionId: sessions[0].id, sessions };
  }
  const next = createChatSession();
  return { ...history, currentSessionId: next.id, sessions: [next, ...sessions] };
}
