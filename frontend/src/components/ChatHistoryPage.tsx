import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Box, CircularProgress } from '@mui/material';
import { agentApi } from '../api/agent';
import { API_BASE, getToken } from '../api/client';
import type { GuestStatus } from '../types/agent';
import { createChatSession, historyOwner, loadChatHistory, removeChatSession, saveChatHistory } from '../state/chatHistory';
import type { ChatHistory, SavedChatSession } from '../state/chatHistory';
import ChatPage from './ChatPage';

async function resolveIdentity(): Promise<{ owner: string; guestStatus: GuestStatus | null }> {
  const token = getToken();
  if (token) {
    const response = await fetch(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
    if (response.ok) {
      const user = await response.json();
      return { owner: `user:${user.id}`, guestStatus: null };
    }
    // Keep the identity and its history on transient server failures.
    if (response.status !== 401) throw new Error('暂时无法验证身份，请稍后刷新重试');
    localStorage.removeItem('access_token');
  }
  let guestToken = localStorage.getItem('guest_token');
  if (guestToken) {
    try {
      const guestStatus = await agentApi.fetchGuestStatus();
      return { owner: historyOwner(guestToken, 'guest'), guestStatus };
    } catch (error) {
      if (!(error instanceof Error) || !('status' in error) || ![401, 404, 410].includes(Number(error.status))) throw error;
      agentApi.clearGuestToken();
    }
  }
  guestToken = await agentApi.ensureGuestSession();
  return { owner: historyOwner(guestToken, 'guest'), guestStatus: agentApi.getGuestStatus() };
}

export default function ChatHistoryPage() {
  const [identity, setIdentity] = useState<Awaited<ReturnType<typeof resolveIdentity>> | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    let revision = 0;
    const loadIdentity = () => {
      const currentRevision = ++revision;
      resolveIdentity().then(value => {
        if (!cancelled && currentRevision === revision) setIdentity(value);
      }).catch(() => {
        if (!cancelled && currentRevision === revision) setError('无法加载会话，请检查网络后刷新重试。已保存的历史记录会保留。');
      });
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key !== null && event.key !== 'access_token' && event.key !== 'guest_token') return;
      setIdentity(null);
      setError('');
      loadIdentity();
    };
    loadIdentity();
    window.addEventListener('storage', onStorage);
    return () => { cancelled = true; window.removeEventListener('storage', onStorage); };
  }, []);

  if (error) return <Alert severity="error" sx={{ m: 3, borderRadius: '14px' }}>{error}</Alert>;
  if (!identity) return <Box sx={{ display: 'grid', placeItems: 'center', height: '100%', minHeight: 240 }}><CircularProgress aria-label="加载会话历史" /></Box>;
  return <HistoryWorkspace key={identity.owner} {...identity} />;
}

function HistoryWorkspace({ owner, guestStatus }: { owner: string; guestStatus: GuestStatus | null }) {
  const [initial] = useState(() => {
    try { return { history: loadChatHistory(owner), error: '' }; }
    catch { return { history: null, error: '无法读取已保存的会话。请检查浏览器存储设置后刷新重试，原记录未被覆盖。' }; }
  });
  const [history, setHistory] = useState(initial.history);
  const historyRef = useRef(history);
  const [storageError, setStorageError] = useState(initial.error);

  const updateHistory = useCallback((next: ChatHistory) => {
    historyRef.current = next;
    setHistory(next);
    try {
      saveChatHistory(owner, next);
      setStorageError('');
    } catch {
      setStorageError('会话无法保存到浏览器，刷新可能丢失本次更改。请检查存储空间或浏览器权限。');
    }
  }, [owner]);

  const saveSession = useCallback((session: SavedChatSession) => {
    const current = historyRef.current;
    if (!current) return;
    updateHistory({ ...current, sessions: current.sessions.map(item => item.id === session.id ? session : item) });
  }, [updateHistory]);

  const selectSession = useCallback((id: string) => {
    const current = historyRef.current;
    if (current?.sessions.some(session => session.id === id)) updateHistory({ ...current, currentSessionId: id });
  }, [updateHistory]);
  const newSession = useCallback(() => {
    const current = historyRef.current;
    if (!current) return;
    const session = createChatSession();
    updateHistory({ ...current, currentSessionId: session.id, sessions: [session, ...current.sessions] });
  }, [updateHistory]);

  const deleteSession = useCallback((id: string) => {
    const current = historyRef.current;
    if (!current) return;
    const next = removeChatSession(current, id);
    try {
      // 先保存再更新画面，存储失败时不显示虚假的删除成功。
      saveChatHistory(owner, next);
      historyRef.current = next;
      setHistory(next);
      setStorageError('');
    } catch {
      setStorageError('聊天未删除，请检查浏览器存储权限后重试。');
    }
  }, [owner]);
  const sessions = useMemo(() => [...(history?.sessions || [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at)), [history]);

  if (!history) return <Alert severity="error">{storageError}</Alert>;
  const selected = history.sessions.find(session => session.id === history.currentSessionId)!;
  return <>
    {storageError && <Alert severity="warning" sx={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 2000 }}>{storageError}</Alert>}
    <ChatPage
      key={selected.id}
      initialSession={selected}
      sessions={sessions}
      guestStatus={guestStatus}
      onSave={saveSession}
      onSelectSession={selectSession}
      onNewSession={newSession}
      onDeleteSession={deleteSession}
    />
  </>;
}
