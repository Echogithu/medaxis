/**
 * Agent API 服务层
 * 文档来源: 14 - API 与通信协议设计
 * 支持 REST + SSE 流式输出
 */

import type { ApiResponse, ChatSession, GuestStatus, RouteResponse, SSEEvent } from '../types/agent';

import { API_BASE, getToken } from './client.ts';

function getGuestToken(): string | null {
  return localStorage.getItem('guest_token');
}

let guestSessionRequest: Promise<string> | null = null;

export function ensureGuestSession(): Promise<string> {
  const token = getGuestToken();
  if (token) return Promise.resolve(token);
  if (!guestSessionRequest) {
    guestSessionRequest = createGuestSession().finally(() => { guestSessionRequest = null; });
  }
  return guestSessionRequest;
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  const guest = getGuestToken();
  if (token) return { Authorization: `Bearer ${token}` };
  if (guest) return { 'X-Guest-Token': guest };
  return {};
}

async function fetchWithSubmissionRetry(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    // The key and body stay unchanged so a lost response replays the same submission.
    return fetch(input, init);
  }
}

/** 获取本地存储的访客状态 */
export function getStoredGuestStatus(): GuestStatus | null {
  const raw = localStorage.getItem('guest_status');
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

/**
 * 创建访客 Session
 * POST /api/v1/auth/guest
 */
export async function createGuestSession(
  fingerprint?: string
): Promise<string> {
  const res = await fetch(`${API_BASE}/auth/guest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fingerprint: fingerprint || 'web' }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  const data = await res.json();
  // 后端返回: { id, session_token, message_count, max_messages, expires_at, created_at }
  localStorage.setItem('guest_token', data.session_token);
  const status: GuestStatus = {
    interaction_count: data.message_count || 0,
    max_interactions: data.max_messages || 10,
    remaining: (data.max_messages || 10) - (data.message_count || 0),
    can_interact: true,
  };
  localStorage.setItem('guest_status', JSON.stringify(status));
  return data.session_token;
}

/**
 * 查询访客状态
 * GET /api/v1/auth/guest/status
 */
export async function fetchGuestStatus(): Promise<GuestStatus> {
  const guestToken = getGuestToken();
  const res = await fetch(`${API_BASE}/auth/guest/status`, {
    headers: guestToken ? { 'X-Guest-Token': guestToken } : {},
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw Object.assign(new Error(err.detail || `HTTP ${res.status}`), { status: res.status });
  }
  const data = await res.json();
  // 后端返回: { interaction_count, max_interactions, remaining, can_interact, expires_at }
  const status: GuestStatus = {
    interaction_count: data.interaction_count || 0,
    max_interactions: data.max_interactions || 10,
    remaining: data.remaining ?? 0,
    can_interact: data.can_interact ?? false,
  };
  localStorage.setItem('guest_status', JSON.stringify(status));
  return status;
}

/**
 * 路由用户意图
 * POST /api/v1/agents/route
 */
export async function routeIntent(
  message: string,
  sessionId?: string
): Promise<RouteResponse> {
  const idempotencyKey = crypto.randomUUID();
  const res = await fetchWithSubmissionRetry(`${API_BASE}/agents/route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey, ...authHeaders() },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
  return json as RouteResponse;
}

/**
 * 非流式对话
 * POST /api/v1/agents/diagnose
 */
export async function chat(
  message: string
): Promise<{ session_id: string; response_text: string; structured_report?: unknown }> {
  const idempotencyKey = crypto.randomUUID();
  const res = await fetchWithSubmissionRetry(`${API_BASE}/agents/diagnose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey, ...authHeaders() },
    body: JSON.stringify({ symptoms: message }),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
  return {
    session_id: json.session_id || '',
    response_text: json.content || '',
    structured_report: json.structured,
  };
}

/**
 * 通用 SSE ReadableStream 解析器。
 * 将 fetch response.body ReadableStream 解析为 SSE 事件流。
 * 支持 event: / data: 格式，每个完整事件通过 onEvent 回调抛出。
 *
 * @param reader   - fetch response.body.getReader() 的返回值
 * @param onEvent  - 事件回调，每个完整 SSE 事件调用一次
 * @param resolve  - Promise resolve，流正常结束时调用
 * @param reject   - Promise reject，流异常或收到 error 事件时调用
 * @param errorKey - error 事件 JSON 中的错误消息字段名（默认 "message"）
 */
async function parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: SSEEvent) => void,
  resolve: () => void,
  reject: (reason: Error) => void,
  errorKey: string = 'message',
): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      while (buffer.includes('\n\n')) {
        const idx = buffer.indexOf('\n\n');
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);

        const lines = raw.split('\n');
        let eventName = '';
        let dataStr = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) eventName = line.slice(7).trim();
          else if (line.startsWith('data: ')) dataStr = line.slice(6);
        }
        if (!eventName || !dataStr) continue;

        try {
          const parsed = JSON.parse(dataStr);
          onEvent({ event: eventName as SSEEvent['event'], data: parsed });
          if (eventName === 'complete') { resolve(); return; }
          if (eventName === 'error') {
            const errMsg = parsed[errorKey] || parsed.error || parsed.message || parsed.detail || 'SSE error';
            reject(new Error(errMsg));
            return;
          }
        } catch {
          onEvent({ event: eventName as SSEEvent['event'], data: { raw: dataStr } });
        }
      }
    }
    resolve();
  } catch (e) {
    reject(e instanceof Error ? e : new Error(String(e)));
  }
}

/**
 * 流式对话 (SSE)
 * POST /api/v1/agents/route/stream
 * 事件类型: intent / agent_switch / thinking / tool_call / tool_result / text / error / complete
 */
export async function streamDiagnose(
  payload: { message: string; session_id?: string; patient_history?: string; submission_id?: string },
  onEvent: (event: SSEEvent) => void
): Promise<void> {
  if (!getToken() && !getGuestToken()) await ensureGuestSession();
  const submissionId = payload.submission_id || crypto.randomUUID();
  const url = `${API_BASE}/agents/route/stream`;
  const body = JSON.stringify({
    message: payload.message,
    session_id: payload.session_id,
    patient_history: payload.patient_history,
  });
  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
    'Idempotency-Key': submissionId,
    ...authHeaders(),
  };

  for (let attempt = 0; attempt < 2; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(url, { method: 'POST', headers, body });
    } catch (error) {
      if (attempt === 0 && error instanceof TypeError) continue;
      throw error;
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error('No response body');
    try {
      await new Promise<void>((resolve, reject) => {
        void parseSSEStream(reader, event => {
          if (event.event === 'guest_token' && typeof event.data.guest_token === 'string' && event.data.guest_token.trim()) {
            localStorage.setItem('guest_token', event.data.guest_token);
          }
          onEvent(event);
        }, resolve, reject);
      });
      return;
    } catch (error) {
      if (attempt === 0 && error instanceof TypeError) continue;
      throw error;
    } finally {
      await reader.cancel().catch(() => {});
    }
  }
}

/**
 * 续传流式对话 (POST + fetch + ReadableStream SSE)
 * 答案放入请求体，凭证放入请求头，不写入 URL。
 */
export async function streamDiagnoseContinue(
  payload: { session_id: string; question_id: string; answer: string; submission_id?: string },
  onEvent: (event: SSEEvent) => void
): Promise<void> {
  const params = new URLSearchParams();
  params.set('session_id', payload.session_id);
  params.set('question_id', payload.question_id);

  const url = `${API_BASE}/agents/route/stream/continue?${params.toString()}`;

  const headers: Record<string, string> = {
    'Idempotency-Key': payload.submission_id || crypto.randomUUID(),
  };
  const token = getToken();
  const guestToken = getGuestToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  else if (guestToken) headers['X-Guest-Token'] = guestToken;

  const response = await fetchWithSubmissionRetry(url, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer: payload.answer }),
  });

  if (!response.ok) throw new Error(`HTTP ${response.status}`);

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  try {
    await new Promise<void>((resolve, reject) => { void parseSSEStream(reader, onEvent, resolve, reject, 'message'); });
  } finally {
    await reader.cancel().catch(() => {});
  }
}

/**
 * 获取会话列表
 * GET /api/v1/agents/sessions
 */
export async function listSessions(): Promise<ChatSession[]> {
  const res = await fetch(`${API_BASE}/agents/sessions`, {
    headers: authHeaders(),
  });
  const json: ApiResponse<ChatSession[]> = await res.json();
  if (json.code !== 200) throw new Error(json.message);
  return json.data || [];
}

/**
 * 清除访客 Token
 */
export function clearGuestToken(): void {
  localStorage.removeItem('guest_token');
  localStorage.removeItem('guest_status');
}

export async function migrateGuestData(guestToken = getGuestToken()): Promise<number> {
  if (!guestToken) return 0;
  const res = await fetch(`${API_BASE}/auth/guest/migrate`, {
    method: 'POST',
    headers: { ...authHeaders(), 'X-Guest-Token': guestToken, 'Content-Type': 'application/json' },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || '访客记录迁移失败');
  return data.migrated || 0;
}

/**
 * 诊断后对话 (Plan C)
 * POST /api/v1/agents/sessions/{sessionId}/chat (SSE)
 */
export function streamChat(
  sessionId: string,
  message: string,
  onEvent: (event: SSEEvent) => void,
  submissionId = crypto.randomUUID(),
): Promise<void> {
  return new Promise((resolve, reject) => {
    const url = `${API_BASE}/agents/sessions/${encodeURIComponent(sessionId)}/chat`;
    const body = JSON.stringify({ message });

    const token = getToken();
    const guestToken = getGuestToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
      'Idempotency-Key': submissionId,
    };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    else if (guestToken) headers['X-Guest-Token'] = guestToken;

    fetchWithSubmissionRetry(url, { method: 'POST', headers, body })
      .then(async (response) => {
        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          reject(new Error(err.detail || `HTTP ${response.status}`));
          return;
        }
        const reader = response.body?.getReader();
        if (!reader) { reject(new Error('No response body')); return; }

        parseSSEStream(reader, onEvent, resolve, reject, 'error');
      })
      .catch(reject);
  });
}

/**
 * Agent API 对象 (兼容性导出)
 */
export const agentApi = {
  getGuestStatus: getStoredGuestStatus,
  createGuestSession,
  ensureGuestSession,
  fetchGuestStatus,
  routeIntent,
  chat,
  streamDiagnose,
  streamDiagnoseContinue,
  streamChat,
  listSessions,
  clearGuestToken,
  migrateGuestData,
};
