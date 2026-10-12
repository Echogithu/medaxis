/**
 * Agent 相关类型定义
 * 文档来源: 14 - API 与通信协议设计
 */

/** SSE 事件类型 */
export type SSEEventType =
  | 'intent'
  | 'agent_switch'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'structured'
  | 'text'
  | 'question'
  | 'interview_progress'
  | 'guest_token'
  | 'error'
  | 'complete';

/** SSE 流事件 */
export interface SSEEvent {
  event: SSEEventType;
  data: Record<string, unknown>;
}

/** Agent 工作流步骤 */
export interface WorkflowStep {
  id: string;
  type: 'intent' | 'agent_switch' | 'tool_call' | 'tool_result' | 'thinking' | 'complete';
  status: 'pending' | 'running' | 'done' | 'error';
  title: string;
  detail?: string;
  timestamp: Date;
  icon?: string;
  toolName?: string;
  toolParams?: Record<string, unknown>;
  toolResult?: unknown;
}

export interface KnowledgeCitation {
  citation_id: string;
  source_type: 'internal' | 'external';
  title: string;
  excerpt: string;
  used_in_report?: boolean | null;
  document_id?: string | null;
  chunk_id?: string | null;
  chunk_index?: number | null;
  document_type?: string | null;
  url?: string | null;
  source_engine?: string | null;
  trust_score?: number | null;
  is_trusted?: boolean | null;
  relevance?: number | null;
  relevance_method?: 'reranker' | 'keyword' | 'query_requirements' | 'unassessed';
  query_coverage?: {
    status: 'answers' | 'partial_answer' | 'does_not_answer' | 'unknown';
    requirements: string[];
    covered_requirements: string[];
    missing_requirements: string[];
    uncertain_requirements: string[];
    excerpt_sha256: string;
  } | null;
  relevance_level?: 'matched' | 'unassessed';
  relevance_reason?: string;
  relevance_query_fingerprint?: string;
  context_metadata?: {
    document_id: string;
    anchor_chunk_id: string;
    chunk_ids: string[];
    start: number;
    end: number;
    source_text_sha256: string;
    method: 'anchor_neighbors';
    max_chars: number;
  } | null;
}

export interface KnowledgeEvidence {
  claim_path: string;
  citation_id: string;
  claim: string;
  quote: string;
  status: 'excerpt_matched' | 'needs_review';
  reason: string;
  start: number | null;
  end: number | null;
}

/** 诊断报告 Schema */
export interface DiagnosisReport {
  primary_diagnosis: string;
  confidence: 'low' | 'medium' | 'high';
  icd11_code?: string;
  severity?: 'mild' | 'moderate' | 'severe' | 'emergency' | 'unknown';
  differential_diagnoses?: Array<{
    diagnosis: string;
    icd11_code?: string;
    reasoning: string;
  }>;
  key_findings?: string[];
  recommended_tests?: string[];
  recommended_actions?: string[];
  contraindications?: string[];
  follow_up_required?: boolean;
  follow_up_timeline?: string;
  knowledge_sources?: string[];
  knowledge_citations?: KnowledgeCitation[];
  knowledge_evidence?: KnowledgeEvidence[];
  knowledge_retrieval_status?: 'used' | 'retrieved_not_cited' | 'no_sources' | 'failed';
  knowledge_retrieval_count?: number;
  interview_stop_reason?: string;
  interview_information_gaps?: string[];
  interview_is_sufficient?: boolean | null;
  disclaimer?: string;
  /** Older clients may still provide these aliases. */
  recommended_exams?: string[];
  treatment_suggestions?: string[];
  follow_up_plan?: string;
  red_flags?: string[];
  referral_needed?: boolean;
  referral_reason?: string;
}

/** Return canonical report values while accepting older serialized field names. */
export function reportRecommendedTests(report: DiagnosisReport): string[] {
  return report.recommended_tests ?? report.recommended_exams ?? [];
}

export function reportRecommendedActions(report: DiagnosisReport): string[] {
  return report.recommended_actions ?? report.treatment_suggestions ?? [];
}

export function reportFollowUp(report: DiagnosisReport): string | undefined {
  return report.follow_up_timeline ?? report.follow_up_plan;
}

/** 问诊问题 */
export interface InterviewQuestion {
  question_id: string;
  question: string;
  type: 'choice' | 'multi_choice' | 'text';
  options?: string[];
  hint?: string;
  allow_skip?: boolean;
  phase?: string;           // 标准医学阶段 ID（如 hpi_onset, pmh_chronic）
  colloquial_phase?: string; // 口语化阶段名称（如 '症状情况', '用药情况'）
  reason?: string;
}

/** 用户消息 */
export interface ChatMessageItem {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  structured?: DiagnosisReport;
  toolCalls?: Array<{
    tool: string;
    params: Record<string, unknown>;
    result?: unknown;
  }>;
  workflowSteps?: WorkflowStep[];
  interviewQuestion?: InterviewQuestion;
  interviewQuestions?: InterviewQuestion[];
  timestamp: Date;
  isStreaming?: boolean;
  /** File upload status */
  uploadStatus?: 'processing' | 'completed' | 'failed';
  uploadFileName?: string;
  uploadFileId?: string;
  labReport?: LabReportResult;
  uploadError?: string;
}

/** 化验单指标 */
export interface LabIndicator {
  indicator_name: string;
  value: number | string;
  unit: string;
  reference_range: string;
  abnormal: boolean;
  abnormal_direction: 'high' | 'low' | null;
  loinc_code: string;
  confidence: number;
}

/** 化验单解析结果 */
export interface LabReportResult {
  file_id: string;
  indicators: LabIndicator[];
  overall_confidence: number;
  requires_manual_review: boolean;
  raw_response: string;
  error: string;
}

/** 文档上传响应 */
export interface DocumentUploadResponse {
  file_id: string;
  filename: string;
  parse_method: 'file-extract' | 'image';
  status: 'queued' | 'processing' | 'completed' | 'failed';
}

/** 文档解析结果 */
export interface DocumentParseResult {
  status: 'queued' | 'processing' | 'completed' | 'failed';
  file_id: string;
  result?: LabReportResult;
  error?: string;
}

/** 会话 */
export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

/** 路由响应 */
export interface RouteResponse {
  intent: string;
  confidence: number;
  target_agent: string;
  requires_clarification: boolean;
  suggested_followup_questions: string[];
}

/** 访客状态 */
export interface GuestStatus {
  interaction_count: number;
  max_interactions: number;
  remaining: number;
  can_interact: boolean;
}

/** 统一 API 响应 */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
  request_id?: string;
  timestamp?: string;
}
