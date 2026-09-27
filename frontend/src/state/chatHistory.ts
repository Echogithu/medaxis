import type { ChatMessageItem, ChatSession, DiagnosisReport } from '../types/agent';

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
      content: '您好！我是医枢 MedAxis 智能医疗助手🩺\n\n我可以帮您：\n• 分析症状并给出初步诊断\n• 解读检查报告\n• 提供健康建议\n\n请描述您的不适感受，或上传相关检查报告。',
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
  return { ...session, messages, pendingSession, chatMode };
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

/** 只移除浏览器聊天记录，服务端问诊报告和资料独立保留。 */
export function removeChatSession(history: ChatHistory, id: string): ChatHistory {
  if (!history.sessions.some(session => session.id === id)) return history;
  const sessions = history.sessions.filter(session => session.id !== id);
  if (history.currentSessionId !== id) return { ...history, sessions };
  const next = createChatSession();
  return { ...history, currentSessionId: next.id, sessions: [next, ...sessions] };
}
