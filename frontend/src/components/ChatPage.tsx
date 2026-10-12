import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Typography,
  Fab,
  Paper,
  Avatar,
  Button,
  Drawer,
  useMediaQuery,
} from '@mui/material';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpRoundedIcon from '@mui/icons-material/KeyboardArrowUpRounded';
import MonitorHeartRoundedIcon from '@mui/icons-material/MonitorHeartRounded';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import Tooltip from '@mui/material/Tooltip';
import type { ChatMessageItem, ChatSession, GuestStatus, SSEEvent, DiagnosisReport, WorkflowStep, InterviewQuestion } from '../types/agent';
import { agentApi } from '../api/agent';
import { uploadDocument, getParseResult } from '../api/documents';
import { getToken } from '../api/client';
import { generateId } from '../state/chatHistory';
import type { ChatMode, SavedChatSession } from '../state/chatHistory';
import ChatMessage from './ChatMessage';
import ChatInput from './ChatInput';
import GuestBanner from './GuestBanner';
import PendingCardsPanel from './PendingCardsPanel';
import FullScreenReport from './FullScreenReport';
import UploadStatusBanner from './UploadStatusBanner';
import ChatWelcome from './ChatWelcome';
import ConsultationSidebar from './ConsultationSidebar';
import DoctorHandoffDialog from './DoctorHandoffDialog';
import { useRegisterChatNavigation } from '../patient/layout/chatNavigation';

interface UploadItem {
  fileId: string;
  fileName: string;
  status: 'parsing' | 'completed' | 'failed';
}


const QUICK_REPLIES = [
  '头疼还发烧',
  '腹痛拉肚子',
  '咳嗽一周了',
  '近期体检报告解读',
];

interface Props {
  initialSession: SavedChatSession;
  sessions: ChatSession[];
  guestStatus: GuestStatus | null;
  onSave: (session: SavedChatSession) => void;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
}

export default function ChatPage({ initialSession, sessions, guestStatus, onSave, onSelectSession, onNewSession, onDeleteSession }: Props) {
  // The parent keys this component by session ID, so every switch restores an
  // independent state and none of the previous session's refs leak into it.
  const [session] = useState(initialSession);
  const currentSessionId = session.id;
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const requestedConsultationId = params.get('consultation_id');
  const closeHandoff = () => { setHelpOpen(false); const next = new URLSearchParams(params); next.delete('consultation_id'); setParams(next, { replace: true }); };
  const createdHandoff = (id: string) => { const next = new URLSearchParams(params); next.set('consultation_id', id); setParams(next, { replace: true }); };
  const registerNavigation = useRegisterChatNavigation();
  const [contextOpen, setContextOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const isDesktop = useMediaQuery('(min-width:1200px)');
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const [messages, setMessages] = useState<ChatMessageItem[]>(session.messages);
  const [isStreaming, setIsStreaming] = useState(false);
  useEffect(() => {
    registerNavigation({ sessions, currentSessionId, onSelectSession, onDeleteSession, busy: isStreaming });
    return () => registerNavigation(null);
  }, [registerNavigation, sessions, currentSessionId, onSelectSession, onDeleteSession, isStreaming]);
  const [showScrollDown, setShowScrollDown] = useState(false);
  const [showScrollTop, setShowScrollTop] = useState(false);
  const [answeredIds, setAnsweredIds] = useState<Set<string>>(() => new Set(session.answeredIds));
  const [reportData, setReportData] = useState<DiagnosisReport | null>(session.reportData);
  const [reportCaseId, setReportCaseId] = useState<string | null>(session.reportCaseId || null);
  const [showReport, setShowReport] = useState(false);
  const [chatMode, setChatMode] = useState<ChatMode>(session.chatMode);
  const [currentGuestStatus, setCurrentGuestStatus] = useState(guestStatus);
  const backendSessionIdRef = useRef<string | null>(session.backendSessionId);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingSessionRef = useRef(session.pendingSession);
  const answerQueueRef = useRef<Promise<void>>(Promise.resolve());
  const queuedAnswerIdsRef = useRef<Set<string>>(new Set());
  const [activeUploads, setActiveUploads] = useState<UploadItem[]>(() => session.messages
    .filter(message => message.uploadStatus)
    .map(message => ({ fileId: message.id, fileName: message.uploadFileName || '文件',
      status: message.uploadStatus === 'processing' ? 'parsing' : message.uploadStatus as 'completed' | 'failed' })));
  const uploadBannerDismissed = useRef(false);
  const failedFileAttempts = useRef<Map<string, number>>(new Map());

  useEffect(() => setCurrentGuestStatus(guestStatus), [guestStatus]);

  const refreshGuestStatus = useCallback(async () => {
    if (!localStorage.getItem('guest_token')) return;
    try {
      setCurrentGuestStatus(await agentApi.fetchGuestStatus());
    } catch {
      // Keep the last server-confirmed value if the status refresh is unavailable.
    }
  }, []);

  useEffect(() => {
    const firstMessage = messages.find(message => message.role === 'user');
    onSave({
      ...session, messages, chatMode, reportData, reportCaseId,
      title: firstMessage?.content.slice(0, 30) || messages.find(message => message.uploadFileName)?.uploadFileName || session.title,
      message_count: messages.filter(message => message.role === 'user').length,
      updated_at: messages.at(-1)?.timestamp.toISOString() || session.updated_at,
      backendSessionId: backendSessionIdRef.current,
      pendingSession: pendingSessionRef.current ? { ...pendingSessionRef.current } : null,
      answeredIds: [...answeredIds],
      interrupted: isStreaming,
    });
  }, [session, messages, chatMode, reportData, reportCaseId, answeredIds, isStreaming, onSave]);

  // 滚动到底部 — 仅在新消息增加且用户接近底部时滚动
  const prevMsgLen = useRef(messages.length);
  useEffect(() => {
    const hasActiveQuestions = messages.some(m => m.role === 'agent' && (m.interviewQuestions?.length));
    if (!hasActiveQuestions && messages.length > prevMsgLen.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevMsgLen.current = messages.length;
  }, [messages]);

  // 滚动监听
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    setShowScrollDown(!nearBottom);
    setShowScrollTop(el.scrollTop > 240);
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      if (isStreaming || !currentSessionId) return;

      if (chatMode === 'idle') {
        setChatMode('consulting');
      }

      const userMsg: ChatMessageItem = {
        id: generateId(),
        role: 'user',
        content: text,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);

      setIsStreaming(true);
      const submissionId = crypto.randomUUID();
      const agentMsgId = generateId();
      let content = '';
      let structured: DiagnosisReport | undefined;
      const workflowSteps: WorkflowStep[] = [];

      // 工作流步骤辅助函数
      const addStep = (step: Omit<WorkflowStep, 'id' | 'timestamp'>) => {
        const newStep: WorkflowStep = { ...step, id: generateId(), timestamp: new Date() };
        workflowSteps.push(newStep);
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === agentMsgId);
          if (idx === -1) {
            return [...prev, { id: agentMsgId, role: 'agent', content: '', timestamp: new Date(), isStreaming: true, workflowSteps: [...workflowSteps] }];
          }
          const next = prev.slice();
          next[idx] = { ...next[idx], workflowSteps: [...workflowSteps] };
          return next;
        });
      };

      // Plan C: diagnosed mode routes to dedicated chat endpoint
      if (chatMode === 'diagnosed' && backendSessionIdRef.current) {
        try {
          await agentApi.streamChat(
            backendSessionIdRef.current,
            text,
            (event: SSEEvent) => {
              switch (event.event) {
                case 'text':
                  content += event.data?.text || '';
                  setMessages((prev) => {
                    const idx = prev.findIndex((m) => m.id === agentMsgId);
                    if (idx === -1) {
                      return [...prev, { id: agentMsgId, role: 'agent', content, timestamp: new Date(), isStreaming: true }];
                    }
                    const next = prev.slice();
                    next[idx] = { ...next[idx], content, isStreaming: true };
                    return next;
                  });
                  break;
                case 'complete':
                  setMessages((prev) => {
                    const idx = prev.findIndex((m) => m.id === agentMsgId);
                    if (idx === -1) return prev;
                    const next = prev.slice();
                    next[idx] = { ...next[idx], isStreaming: false };
                    return next;
                  });
                  setIsStreaming(false);
                  break;
                case 'error':
                  setMessages((prev) => [...prev, { id: generateId(), role: 'agent', content: `请求失败，请重试`, timestamp: new Date() }]);
                  setIsStreaming(false);
                  break;
              }
            },
            submissionId,
          );
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : '连接失败，请检查网络后重试';
          setMessages((prev) => [...prev, { id: generateId(), role: 'agent', content: `❌ ${errorMessage}`, timestamp: new Date() }]);
          setIsStreaming(false);
        } finally {
          await refreshGuestStatus();
        }
        return;
      }

      // Lightweight patient history — only user Q&A, exclude verbose reports.
      // The diagnosis pipeline uses this for classify_intent context.
      // The chat endpoint (_build_chat_context) loads full context from DB.
      const patientHistory = messages
        .filter(m => m.role === 'user' && m.content.length < 500)
        .map(m => `患者: ${m.content.slice(0, 300)}`)
        .join('\n')
        .slice(0, 3000);

      try {
        await agentApi.streamDiagnose(
          {
            message: text,
            session_id: currentSessionId,
            patient_history: patientHistory,
            submission_id: submissionId,
          },
          (event: SSEEvent) => {
            switch (event.event) {
              case 'intent': {
                const intent = event.data?.intent as string || 'diagnosis';
                const confidence = event.data?.confidence as string || 'medium';
                addStep({
                  type: 'intent',
                  status: 'done',
                  title: `MasterAgent 识别到意图: ${intent}`,
                  detail: `置信度: ${confidence}`,
                });
                break;
              }
              case 'agent_switch': {
                const agentDisplay = event.data?.agent_display as string || event.data?.agent as string || '未知';
                addStep({
                  type: 'agent_switch',
                  status: 'done',
                  title: `已切换到 ${agentDisplay}`,
                  detail: event.data?.message as string || '',
                });
                break;
              }
              case 'thinking': {
                const messageText = event.data?.message as string || '正在分析...';
                addStep({
                  type: 'thinking',
                  status: 'done',
                  title: messageText,
                });
                break;
              }
              case 'tool_call': {
                const toolName = event.data?.tool as string || '未知工具';
                addStep({
                  type: 'tool_call',
                  status: 'done',
                  title: event.data?.message as string || `正在调用 ${toolName}...`,
                  toolName,
                  toolParams: (event.data?.params as Record<string, unknown>) || {},
                });
                break;
              }
              case 'tool_result': {
                const toolName = event.data?.tool as string || '未知工具';
                addStep({
                  type: 'tool_result',
                  status: 'done',
                  title: event.data?.message as string || `${toolName} 执行完成`,
                  toolName,
                  toolResult: event.data?.result,
                });
                break;
              }
              case 'text': {
                content += event.data?.text || '';
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, { id: agentMsgId, role: 'agent', content, timestamp: new Date(), isStreaming: true, workflowSteps: [...workflowSteps] }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], content, isStreaming: true, workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              }
              case 'structured':
                structured = event.data as unknown as DiagnosisReport;
                setReportData(structured);
                setShowReport(true);
                setChatMode('diagnosed');
                pendingSessionRef.current = null;
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) return prev;
                  const next = prev.slice();
                  next[idx] = { ...next[idx], structured, content: content || next[idx].content || '已生成问诊总结', workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              case 'question': {
                const q = event.data as unknown as { question_id: string; question: string; type: string; options?: string[]; hint?: string; allow_skip?: boolean; colloquial_phase?: string; phase?: string; questions?: InterviewQuestion[] };
                const qs: InterviewQuestion[] = 'questions' in event.data ? (event.data as { questions: InterviewQuestion[] }).questions : [q as InterviewQuestion];
                // sessionId will be set when 'complete' event with status='waiting_for_answer' arrives
                // For now, just set the questionId; sessionId is updated in the 'complete' handler
                if (!pendingSessionRef.current) {
                  pendingSessionRef.current = { sessionId: '', questionId: q.question_id };
                } else {
                  pendingSessionRef.current.questionId = q.question_id;
                }
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, {
                      id: agentMsgId,
                      role: 'agent',
                      content: '',
                      timestamp: new Date(),
                      isStreaming: true,
                      workflowSteps: [...workflowSteps],
                      interviewQuestions: qs,
                    }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], isStreaming: true, workflowSteps: [...workflowSteps], interviewQuestions: qs };
                  return next;
                });
                break;
              }
              case 'interview_progress': {
                addStep({
                  type: 'thinking',
                  status: 'done',
                  title: '📋 已收集问诊信息',
                  detail: Object.entries(event.data?.collected as Record<string, unknown> || {})
                    .filter(([k]) => !k.startsWith('__'))
                    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', '),
                });
                break;
              }
              case 'error': {
                const errorMsg = event.data?.message as string || event.data?.error as string || '服务异常';
                addStep({
                  type: 'thinking',
                  status: 'error',
                  title: `错误: ${errorMsg}`,
                });
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, { id: agentMsgId, role: 'agent', content: `❌ 错误: ${errorMsg}`, timestamp: new Date(), workflowSteps: [...workflowSteps] }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], content: `❌ 错误: ${errorMsg}`, isStreaming: false, workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              }
              case 'complete': {
                const sid = event.data?.session_id as string;
                if (sid) backendSessionIdRef.current = sid;
                const savedCaseId = event.data?.case_id as string | undefined;
                if (savedCaseId) setReportCaseId(savedCaseId);
                const status = event.data?.status as string;
                if (status === 'waiting_for_answer') {
                  setIsStreaming(false);
                  setMessages(prev => prev.map(message => ({ ...message, isStreaming: false })));
                  if (sid) {
                    if (!pendingSessionRef.current) {
                      pendingSessionRef.current = { sessionId: sid, questionId: '' };
                    } else {
                      pendingSessionRef.current.sessionId = sid;
                    }
                  }
                  break;
                }
                addStep({
                  type: 'complete',
                  status: 'done',
                  title: event.data?.message as string || '✅ 响应完成',
                });
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) return prev;
                  const next = prev.slice();
                  next[idx] = { ...next[idx], isStreaming: false, workflowSteps: [...workflowSteps] };
                  return next;
                });
                setIsStreaming(false);
                pendingSessionRef.current = null;
                break;
              }
            }
          }
        );
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : '连接失败，请检查网络后重试';
        setMessages((prev) => [...prev, { id: generateId(), role: 'agent', content: `❌ ${errorMessage}`, timestamp: new Date() }]);
        setIsStreaming(false);
        if (!pendingSessionRef.current?.sessionId) setChatMode('idle');
      } finally {
        setIsStreaming(false);
        // 普通回复或生成失败没有待回答会话，恢复输入；临床卡片和已生成报告保留各自状态。
        if (!pendingSessionRef.current?.sessionId && !structured) setChatMode('idle');
        await refreshGuestStatus();
      }
    },
    [isStreaming, currentSessionId, chatMode, messages, refreshGuestStatus]
  );

  const handleInterviewAnswer = useCallback(
    (questionId: string, answer: string) => {
      // P0-1: Block interview answers after diagnosis
      if (chatMode === 'diagnosed' || queuedAnswerIdsRef.current.has(questionId)) return;

      const pending = pendingSessionRef.current;
      if (!pending?.sessionId) return;

      queuedAnswerIdsRef.current.add(questionId);
      setAnsweredIds((prev) => new Set([...prev, questionId]));

      // Add user answer as a new message
      const userAnswerMsg: ChatMessageItem = {
        id: generateId(),
        role: 'user',
        content: answer,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userAnswerMsg]);

      const processAnswer = async () => {
      const activePending = pendingSessionRef.current;
      if (!activePending?.sessionId) {
          setAnsweredIds((prev) => {
            const next = new Set(prev);
            next.delete(questionId);
            return next;
          });
          return;
      }

      setIsStreaming(true);
      const submissionId = crypto.randomUUID();
      const agentMsgId = generateId();
        let content = '';
        let structured: DiagnosisReport | undefined;
        const workflowSteps: WorkflowStep[] = [];

        const addStep = (step: Omit<WorkflowStep, 'id' | 'timestamp'>) => {
          const newStep: WorkflowStep = { ...step, id: generateId(), timestamp: new Date() };
          workflowSteps.push(newStep);
          setMessages((prev) => {
            const idx = prev.findIndex((m) => m.id === agentMsgId);
            if (idx === -1) {
              return [...prev, { id: agentMsgId, role: 'agent', content: '', timestamp: new Date(), isStreaming: true, workflowSteps: [...workflowSteps] }];
            }
            const next = prev.slice();
            next[idx] = { ...next[idx], workflowSteps: [...workflowSteps] };
            return next;
          });
        };

        try {
          await agentApi.streamDiagnoseContinue(
          {
            session_id: activePending.sessionId,
            question_id: questionId,
            answer,
            submission_id: submissionId,
          },
          (event: SSEEvent) => {
            switch (event.event) {
              case 'thinking': {
                addStep({
                  type: 'thinking',
                  status: 'done',
                  title: (event.data?.message as string) || '正在分析...',
                });
                break;
              }
              case 'tool_call': {
                const toolName = (event.data?.tool as string) || '未知工具';
                addStep({
                  type: 'tool_call',
                  status: 'done',
                  title: (event.data?.message as string) || `正在调用 ${toolName}...`,
                  toolName,
                  toolParams: (event.data?.params as Record<string, unknown>) || {},
                });
                break;
              }
              case 'tool_result': {
                const toolName = (event.data?.tool as string) || '未知工具';
                addStep({
                  type: 'tool_result',
                  status: 'done',
                  title: (event.data?.message as string) || `${toolName} 执行完成`,
                  toolName,
                  toolResult: event.data?.result,
                });
                break;
              }
              case 'text': {
                content += (event.data?.text as string) || '';
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, { id: agentMsgId, role: 'agent', content, timestamp: new Date(), isStreaming: true, workflowSteps: [...workflowSteps] }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], content, isStreaming: true, workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              }
              case 'structured':
                structured = event.data as unknown as DiagnosisReport;
                setReportData(structured);
                setShowReport(true);
                setChatMode('diagnosed');
                pendingSessionRef.current = null;
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) return prev;
                  const next = prev.slice();
                  next[idx] = { ...next[idx], structured, content: content || next[idx].content || '已生成问诊总结', workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              case 'question': {
                const q = event.data as unknown as { question_id: string; question: string; type: string; options?: string[]; hint?: string; allow_skip?: boolean; colloquial_phase?: string; phase?: string; questions?: InterviewQuestion[] };
                const qs: InterviewQuestion[] = 'questions' in event.data ? (event.data as { questions: InterviewQuestion[] }).questions : [q as InterviewQuestion];
                // sessionId will be set when 'complete' event with status='waiting_for_answer' arrives
                // For now, just set the questionId; sessionId is updated in the 'complete' handler
                if (!pendingSessionRef.current) {
                  pendingSessionRef.current = { sessionId: '', questionId: q.question_id };
                } else {
                  pendingSessionRef.current.questionId = q.question_id;
                }
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, {
                      id: agentMsgId,
                      role: 'agent',
                      content: '',
                      timestamp: new Date(),
                      isStreaming: true,
                      workflowSteps: [...workflowSteps],
                      interviewQuestions: qs,
                    }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], isStreaming: true, workflowSteps: [...workflowSteps], interviewQuestions: qs };
                  return next;
                });
                break;
              }
              case 'interview_progress': {
                addStep({
                  type: 'thinking',
                  status: 'done',
                  title: '📋 已收集问诊信息',
                  detail: Object.entries(event.data?.collected as Record<string, unknown> || {})
                    .filter(([k]) => !k.startsWith('__'))
                    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', '),
                });
                break;
              }
              case 'error': {
                  const errorMsg = (event.data?.message as string) || (event.data?.error as string) || '服务异常';
                  // 请求未生成报告，保留会话并重新开放当前卡片，允许重试检索。
                  setAnsweredIds((prev) => {
                    const next = new Set(prev);
                    next.delete(questionId);
                    return next;
                  });
                addStep({
                  type: 'thinking',
                  status: 'error',
                  title: `错误: ${errorMsg}`,
                });
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) {
                    return [...prev, { id: agentMsgId, role: 'agent', content: `❌ 错误: ${errorMsg}`, timestamp: new Date(), workflowSteps: [...workflowSteps] }];
                  }
                  const next = prev.slice();
                  next[idx] = { ...next[idx], content: `❌ 错误: ${errorMsg}`, isStreaming: false, workflowSteps: [...workflowSteps] };
                  return next;
                });
                break;
              }
              case 'complete': {
                const completedSessionId = event.data?.session_id as string;
                if (completedSessionId) backendSessionIdRef.current = completedSessionId;
                const savedCaseId = event.data?.case_id as string | undefined;
                if (savedCaseId) setReportCaseId(savedCaseId);
                const status = event.data?.status as string;
                if (status === 'waiting_for_answer') {
                  setIsStreaming(false);
                  setMessages(prev => prev.map(message => ({ ...message, isStreaming: false })));
                  const sid = event.data?.session_id as string;
                  if (sid) {
                    if (!pendingSessionRef.current) {
                      pendingSessionRef.current = { sessionId: sid, questionId: '' };
                    } else {
                      pendingSessionRef.current.sessionId = sid;
                      // Keep the existing questionId, don't overwrite it
                    }
                  }
                  break;
                }
                if (status === 'already_diagnosed') {
                  setChatMode('diagnosed');
                  setMessages((prev) => {
                    const idx = prev.findIndex((m) => m.id === agentMsgId);
                    if (idx === -1) {
                      return [...prev, { id: agentMsgId, role: 'system', content: '✅ 问诊已完成，问诊总结已生成。', timestamp: new Date() }];
                    }
                    const next = prev.slice();
                    next[idx] = { ...next[idx], isStreaming: false, content: '✅ 问诊已完成，问诊总结已生成。', workflowSteps: [...workflowSteps] };
                    return next;
                  });
                  setIsStreaming(false);
                  pendingSessionRef.current = null;
                  break;
                }
                addStep({
                  type: 'complete',
                  status: 'done',
                  title: (event.data?.message as string) || '✅ 响应完成',
                });
                setMessages((prev) => {
                  const idx = prev.findIndex((m) => m.id === agentMsgId);
                  if (idx === -1) return prev;
                  const next = prev.slice();
                  next[idx] = { ...next[idx], isStreaming: false, workflowSteps: [...workflowSteps] };
                  return next;
                });
                setIsStreaming(false);
                pendingSessionRef.current = null;
                break;
              }
            }
          }
          );
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : '连接失败，请检查网络后重试';
          setMessages((prev) => [...prev, { id: generateId(), role: 'agent', content: `❌ ${errorMessage}`, timestamp: new Date() }]);
          setAnsweredIds((prev) => {
            const next = new Set(prev);
            next.delete(questionId);
            return next;
          });
          if (!pendingSessionRef.current?.sessionId) setChatMode('idle');
        } finally {
          setIsStreaming(false);
          await refreshGuestStatus();
        }
      };

      answerQueueRef.current = answerQueueRef.current
        .catch(() => undefined)
        .then(processAnswer)
        .finally(() => { queuedAnswerIdsRef.current.delete(questionId); });
    },
    [chatMode, refreshGuestStatus]
  );

  const handleQuickReply = useCallback(
    (text: string) => {
      if (isStreaming) return;
      handleSend(text);
    },
    [isStreaming, handleSend]
  );

  // The server file ID is persisted with the upload message. Polling starts
  // both for newly uploaded files and for pending uploads restored on refresh.
  const pendingUploads = messages.filter(message => message.uploadStatus === 'processing' && message.uploadFileId);
  const uploadKey = JSON.stringify(pendingUploads.map(message => ({ id: message.id, fileId: message.uploadFileId!, fileName: message.uploadFileName || '文件' })));
  useEffect(() => {
    const uploads: { id: string; fileId: string; fileName: string }[] = JSON.parse(uploadKey);
    let cancelled = false;
    const cleanups = uploads.map(upload => {
      let inFlight = false;
      let finished = false;
      const fail = (error: string) => {
        if (cancelled || finished) return;
        finished = true;
        failedFileAttempts.current.set(upload.fileName, (failedFileAttempts.current.get(upload.fileName) || 0) + 1);
        setActiveUploads(prev => prev.map(item => item.fileId === upload.id ? { ...item, status: 'failed' } : item));
        setMessages(prev => prev.map(message => message.id === upload.id
          ? { ...message, uploadStatus: 'failed', uploadError: error } : message));
      };
      const poll = async () => {
        if (inFlight || finished || cancelled) return;
        inFlight = true;
        try {
          const result = await getParseResult(upload.fileId);
          if (cancelled || finished) return;
          if (result.status === 'failed') fail(result.error || '解析失败');
          if (result.status === 'completed' && result.result) {
            const token = getToken();
            const uploadSessionId = backendSessionIdRef.current || currentSessionId;
            const response = await fetch(`/api/v1/agents/sessions/${uploadSessionId}/lab-reports`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json',
                ...(token ? { Authorization: `Bearer ${token}` } : { 'X-Guest-Token': localStorage.getItem('guest_token') || '' }) },
              body: JSON.stringify([result.result]),
            });
            if (!response.ok) throw new Error('保存解析结果失败');
            if (cancelled || finished) return;
            finished = true;
            setActiveUploads(prev => prev.map(item => item.fileId === upload.id ? { ...item, status: 'completed' } : item));
            setMessages(prev => prev.map(message => message.id === upload.id
              ? { ...message, uploadStatus: 'completed', labReport: result.result, content: `📄 ${upload.fileName} 解析完成` } : message));
          }
        } catch {
          // Retry transient failures until the bounded timeout.
        } finally { inFlight = false; }
      };
      const interval = setInterval(poll, 1500);
      const timeout = setTimeout(() => fail('解析超时，请重新上传文件'), 120000);
      void poll();
      return () => { clearInterval(interval); clearTimeout(timeout); };
    });
    return () => { cancelled = true; cleanups.forEach(cleanup => cleanup()); };
  }, [uploadKey, currentSessionId]);

  const handleFileUpload = useCallback(async (file: File) => {
    const uploadId = generateId();
    setActiveUploads(prev => [...prev, { fileId: uploadId, fileName: file.name, status: 'parsing' }]);
    setMessages(prev => [...prev, { id: uploadId, role: 'agent', content: '', timestamp: new Date(),
      uploadStatus: 'processing', uploadFileName: file.name }]);
    try {
      const result = await uploadDocument(file, currentSessionId);
      setMessages(prev => prev.map(message => message.id === uploadId ? { ...message, uploadFileId: result.file_id } : message));
    } catch (error) {
      setActiveUploads(prev => prev.map(item => item.fileId === uploadId ? { ...item, status: 'failed' } : item));
      setMessages(prev => prev.map(message => message.id === uploadId
        ? { ...message, uploadStatus: 'failed', uploadError: error instanceof Error ? error.message : '上传失败' } : message));
    }
  }, [currentSessionId]);

  return (
    <Box sx={{ display: 'flex', height: '100%', minHeight: 0, bgcolor: '#f8fafc' }}>
      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {currentGuestStatus && (
          <GuestBanner
            status={currentGuestStatus}
            onRegister={() => navigate('/register')}
            onLogin={() => navigate('/login')}
          />
        )}

        <Box sx={{ flex: 1, minHeight: 0, overflow: 'hidden', p: { xs: 1, sm: 1.75, lg: 2.5 }, bgcolor: '#f8fafc' }}>
          <Box sx={{ width: '100%', maxWidth: 1680, height: '100%', minHeight: 0, mx: 'auto', display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1fr) minmax(300px, 0.45fr)' }, gap: 1.75 }}>
          <Paper component="main" elevation={0} sx={{ position: 'relative', width: '100%', height: '100%', minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRadius: '24px', bgcolor: '#fff', boxShadow: '0 10px 40px -10px rgba(15,23,42,.08)' }}>
            <Box sx={{ minHeight: 64, px: { xs: 1.75, sm: 2.5 }, py: 1, display: 'flex', alignItems: 'center', gap: 1.25, borderBottom: '1px solid #f1f5f9', bgcolor: '#fff' }}>
              <Avatar variant="rounded" sx={{ display: { xs: 'none', sm: 'flex' }, width: 38, height: 38, borderRadius: '12px', bgcolor: '#0d9488', color: '#fff' }}>
                <MonitorHeartRoundedIcon sx={{ fontSize: 21 }} />
              </Avatar>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography sx={{ color: '#1e293b', fontSize: 14, fontWeight: 750, lineHeight: 1.25 }}>AI 问诊</Typography>
              </Box>
              <Button variant="contained" size="small" startIcon={<AddRoundedIcon />} onClick={onNewSession} disabled={isStreaming}
                sx={{ flexShrink: 0, px: 1.5, minWidth: 0, minHeight: 44, borderRadius: '14px', fontSize: { xs: 12, sm: 13 }, bgcolor: 'primary.dark', '&:hover': { bgcolor: '#115e59' }, '& .MuiButton-startIcon': { mr: 0.75, '& svg': { fontSize: 18 } } }}>新建会话</Button>
              {!isDesktop && <Button size="small" variant="outlined" onClick={() => setContextOpen(true)} aria-haspopup="dialog" sx={{ flexShrink: 0, px: 1, minWidth: 0, fontSize: 12, minHeight: 44 }}>问诊摘要</Button>}
            </Box>

            <Box
              ref={scrollRef}
              onScroll={handleScroll}
              aria-label="问诊消息"
              tabIndex={-1}
              sx={{ position: 'relative', flex: 1, minHeight: 0, overflowY: 'auto', px: { xs: 0.75, sm: 2, md: 3 }, py: { xs: 1.5, sm: 2.5 }, display: 'flex', flexDirection: 'column', gap: 0.5, bgcolor: '#f8fafc' }}
            >
              {session.interrupted && <Alert severity="info" sx={{ maxWidth: 1000, width: '100%', mx: 'auto', mb: 1, borderRadius: '12px' }}>上次回复被中断，已保留收到的内容；您可以继续回答问诊卡或重新发送问题。</Alert>}
              {messages.length === 0 && !session.interrupted && (
                <ChatWelcome onPick={handleQuickReply} />
              )}
              {messages.map((msg) => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  onInterviewAnswer={handleInterviewAnswer}
                  onOpenReport={() => setShowReport(true)}
                />
              ))}
              <div ref={messagesEndRef} />
            </Box>

            {chatMode === 'consulting' && (
              <PendingCardsPanel
                messages={messages}
                answeredIds={answeredIds}
                onAnswer={handleInterviewAnswer}
              />
            )}

            <Box sx={{ position: 'relative', px: { xs: 1.25, sm: 2.5 }, pt: { xs: 1.25, sm: 1.75 }, pb: { xs: 1.1, sm: 1.5 }, borderTop: '1px solid #f1f5f9', bgcolor: '#fff' }}>
              {(activeUploads.length > 0 || (chatMode === 'diagnosed' && !uploadBannerDismissed.current)) && (
                <UploadStatusBanner
                  uploads={activeUploads}
                  failedAttempts={failedFileAttempts.current}
                  mode={chatMode === 'diagnosed' ? 'diagnosed' : 'consulting'}
                  onDismiss={() => {
                    setActiveUploads([]);
                    uploadBannerDismissed.current = true;
                  }}
                />
              )}
              {chatMode === 'consulting' ? (
                <Typography variant="body2" color="text.secondary" align="center" sx={{ py: 1, color: '#6f8585', fontSize: 12 }}>
                  正在问诊中，请通过待回答卡片继续
                </Typography>
              ) : (
                <ChatInput
                  onSend={handleSend}
                  disabled={isStreaming}
                  quickReplies={chatMode === 'idle' && messages.length <= 2 ? QUICK_REPLIES : undefined}
                  onQuickReply={handleQuickReply}
                  onFileUpload={handleFileUpload}
                  placeholder={
                    activeUploads.some((u) => u.status === 'parsing')
                      ? '报告解析中，可继续描述症状…'
                      : undefined
                  }
                />
              )}
              <Typography sx={{ mt: 0.9, color: '#64748b', fontSize: 12, textAlign: 'center', lineHeight: 1.4 }}>
                AI 建议不能替代医生诊断；紧急情况请及时就医
              </Typography>
            </Box>
        {showScrollDown && (
          <Tooltip title="回到最新消息">
          <Fab
            size="small"
            aria-label="回到最新消息"
            onClick={() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: reduceMotion ? 'instant' : 'smooth' })}
            sx={{ position: 'absolute', bottom: { xs: 94, sm: 116 }, right: { xs: reportData ? 74 : 18, sm: reportData ? 88 : 32 }, bgcolor: '#fff', color: '#0d9488', border: '1px solid #e0e9e5', boxShadow: '0 6px 16px rgba(34,61,55,.12)' }}
          >
            <KeyboardArrowDownIcon />
          </Fab>
          </Tooltip>
        )}

        {showScrollTop && <Tooltip title="回到问诊顶部">
          <Fab size="small" aria-label="回到问诊顶部" onClick={() => {
            scrollRef.current?.scrollTo({ top: 0, behavior: reduceMotion ? 'instant' : 'smooth' });
            scrollRef.current?.focus({ preventScroll: true });
          }} sx={{ position: 'absolute', bottom: { xs: showScrollDown ? 142 : 94, sm: showScrollDown ? 164 : 116 }, right: { xs: reportData ? 74 : 18, sm: reportData ? 88 : 32 }, bgcolor: '#fff', color: '#0d9488', border: '1px solid #e0e9e5', boxShadow: '0 6px 16px rgba(34,61,55,.12)', '&:hover': { bgcolor: '#eef7f3' } }}>
            <KeyboardArrowUpRoundedIcon />
          </Fab>
        </Tooltip>}

        {reportData && (
          <Tooltip title="查看问诊总结">
            <Fab
              size="small"
              aria-label="查看问诊总结"
              onClick={() => setShowReport(true)}
              sx={{ position: 'absolute', bottom: { xs: 94, sm: 116 }, right: { xs: 18, sm: 32 }, bgcolor: '#0d9488', color: '#fff', boxShadow: '0 8px 20px rgba(23,143,130,.24)', zIndex: 1200, '&:hover': { bgcolor: '#0f766e' } }}
            >
              <DescriptionOutlinedIcon />
            </Fab>
          </Tooltip>
        )}

          </Paper>
          {isDesktop && <Box sx={{ minHeight: 0, overflowY: 'auto', pb: 1 }}>
            <ConsultationSidebar messages={messages} report={reportData} onOpenReport={() => setShowReport(true)} onRequestHelp={() => setHelpOpen(true)} />
          </Box>}
          </Box>
        </Box>

      </Box>

      <Drawer anchor="right" open={!isDesktop && contextOpen} onClose={() => setContextOpen(false)} slotProps={{ paper: { sx: { width: { xs: '100%', sm: 400 }, p: 2, bgcolor: '#f8fafc' }, role: 'dialog', 'aria-label': '问诊辅助信息' } }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
          <Typography sx={{ fontWeight: 750, color: '#1e293b' }}>本次问诊</Typography>
          <Button onClick={() => setContextOpen(false)} aria-label="关闭问诊摘要">关闭</Button>
        </Box>
        <ConsultationSidebar messages={messages} report={reportData} onOpenReport={() => { setContextOpen(false); setShowReport(true); }} onRequestHelp={() => { setContextOpen(false); setHelpOpen(true); }} />
      </Drawer>

      {(helpOpen || requestedConsultationId) && <DoctorHandoffDialog key={`${currentSessionId}-${requestedConsultationId || ''}`} caseId={reportCaseId} requestedId={requestedConsultationId} onClose={closeHandoff} onCreated={createdHandoff} />}

      <FullScreenReport
        report={reportData!}
        visible={!!reportData && showReport}
        onClose={() => setShowReport(false)}
        onSupplement={() => {
          setShowReport(false);
          // 等待全屏总结关闭并释放焦点，再进入现有追问输入框。
          setTimeout(() => scrollRef.current?.closest('main')?.querySelector<HTMLTextAreaElement>('textarea')?.focus(), 350);
        }}
        caseId={reportCaseId}
        canOpenCase={Boolean(reportCaseId && getToken())}
        onOpenCase={() => {
          if (!reportCaseId || !getToken()) return;
          navigate(`/cases?case_id=${encodeURIComponent(reportCaseId)}`);
        }}
      />
    </Box>
  );
}
