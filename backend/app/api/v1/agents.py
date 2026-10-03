"""Multi-Agent Medical Collaboration endpoints.

New design per docs/archive/PROPOSAL.md:
- /route      → MasterAgent intent classification + auto-routing
- /diagnose   → DiagnosisAgent with Tool Use + structured output
- /plan       → PlanningAgent with structured treatment plan
- /monitor    → MonitoringAgent with structured assessment
- /consult    → Full multi-agent consultation
- /sessions   → Agent session management
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    CurrentUserContext,
    CurrentUserContextLenient,
    CurrentUserContextLenientNoQuery,
    CurrentUserOrActiveGuest,
    UserContext,
    require_role,
)
from app.db.session import async_session_maker, get_db
from app.models.agent import AgentSession, AgentSessionStatus, AgentSessionType
from app.models.document_parse import DocumentParseTask
from app.models.medical_case import MedicalCase
from app.models.user import GuestSession, User, UserRole
from app.services.agents import AgentOrchestrator, DiagnosisAgent, MonitoringAgent, PlanningAgent
from app.services.llm import LLMService
from app.services.knowledge_citations import evidence_matches_excerpt
from app.services.llm_errors import patient_llm_error, safe_llm_failure_fields, MedicalEvidenceUnavailableError
from app.services.patient_case_persistence import (
    DiagnosisCasePersistenceError,
    persist_diagnosis_case,
)
from app.services.guest_model_quota import run_guest_submission, stream_guest_submission
from app.services.rag import RAGService
from app.tools.registry import GLOBAL_REGISTRY

router = APIRouter()


def _patient_llm_error_event(
    exc: BaseException,
    stage: str,
    *,
    code: str | None = None,
    message: str | None = None,
) -> str:
    """为患者 SSE 返回稳定错误码，只记录脱敏分类信息。"""
    payload = patient_llm_error(exc)
    if code:
        payload["code"] = code
    if message:
        payload["error"] = message
    fields = safe_llm_failure_fields(exc)
    logging.getLogger("agents.llm").warning(
        "患者模型请求失败 stage=%s code=%s exception_type=%s",
        stage,
        payload["code"],
        fields["exception_type"],
    )
    return f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _patient_error_event(code: str, message: str, stage: str) -> str:
    logging.getLogger("agents.patient").warning(
        "患者端请求失败 stage=%s code=%s",
        stage,
        code,
    )
    return f"event: error\ndata: {json.dumps({'code': code, 'error': message}, ensure_ascii=False)}\n\n"


def _log_patient_llm_interruption(stage: str) -> None:
    logging.getLogger("agents.llm").info(
        "患者模型请求中断 stage=%s code=LLM_REQUEST_INTERRUPTED exception_type=CancelledError",
        stage,
    )

def _inject_lab_context(messages: list[dict[str, str]], lab_reports: list[dict[str, Any]]) -> None:
    """Format lab reports and insert into the message list as a system prompt."""
    lab_text = "**已上传的检查报告解析结果：**\n"
    for r in lab_reports:
        indicators = r.get("indicators", [])
        if indicators:
            lab_text += f"\n报告 (置信度: {int(r.get('overall_confidence', 0) * 100)}%):\n"
            for ind in indicators[:30]:
                abn = " [异常]" if ind.get("abnormal") else ""
                lab_text += f"  - {ind.get('indicator_name', '?')}: {ind.get('value', '?')} {ind.get('unit', '')}{abn}\n"
    messages.insert(0, {"role": "system", "content": lab_text})


def _session_belongs_to_context(session: AgentSession, ctx: UserContext) -> bool:
    if ctx.user is not None:
        return session.user_id == ctx.user.id and session.guest_session_id is None
    if ctx.is_guest and ctx.guest_id:
        try:
            return session.guest_session_id == uuid.UUID(ctx.guest_id) and session.user_id is None
        except ValueError:
            return False
    return False


async def _require_session_access(
    db: AsyncSession, session: AgentSession, ctx: UserContext
) -> None:
    """继续或查看会话前验证账号归属及访客有效期。"""
    if not _session_belongs_to_context(session, ctx):
        raise HTTPException(status_code=404, detail="Session not found")
    if ctx.is_guest and ctx.guest_id:
        try:
            guest = await db.get(GuestSession, uuid.UUID(ctx.guest_id))
        except ValueError:
            guest = None
        if guest is None or guest.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Session not found")


def _parse_task_owner_filter(ctx: UserContext):
    if ctx.user is not None:
        return DocumentParseTask.owner_user_id == ctx.user.id
    if ctx.is_guest and ctx.guest_id:
        try:
            return DocumentParseTask.owner_guest_id == uuid.UUID(ctx.guest_id)
        except ValueError:
            pass
    return DocumentParseTask.file_id == ""


async def _load_session_lab_reports(
    db: AsyncSession, ctx: UserContext, session_id: str
) -> list[dict[str, Any]]:
    """只从当前身份拥有的持久化上传任务中读取报告。"""
    ids: list[str] = [session_id]
    source_session_id = None
    try:
        session = await db.get(AgentSession, uuid.UUID(session_id))
        if session is not None:
            if not _session_belongs_to_context(session, ctx):
                raise HTTPException(status_code=404, detail="Session not found")
            source_session_id = session.id
            frontend_id = (session.context or {}).get("_frontend_sid")
            if frontend_id:
                ids.append(frontend_id)
    except ValueError:
        pass

    criteria = [DocumentParseTask.client_session_id.in_(ids)]
    if source_session_id is not None:
        criteria.append(DocumentParseTask.source_session_id == source_session_id)
    rows = await db.execute(
        select(DocumentParseTask)
        .where(
            _parse_task_owner_filter(ctx),
            DocumentParseTask.status == "completed",
            or_(*criteria),
        )
        .order_by(DocumentParseTask.created_at)
    )
    return [row.result for row in rows.scalars().all() if row.result]


async def _load_health_profile_context(
    db: AsyncSession,
    user_id: str | None,
) -> str:
    """按当前授权患者读取人工档案，不混入后置的 AI 画像。"""
    if not user_id:
        return ""

    from app.models.agent import PatientHealthProfile
    from app.services.patient_profile import format_profile_context
    profile = await db.scalar(select(PatientHealthProfile).where(
        PatientHealthProfile.patient_id == uuid.UUID(user_id)
    ))
    context = format_profile_context(profile)
    user = await db.get(User, uuid.UUID(user_id))
    age_parts = []
    if user is not None:
        age_years = getattr(user, "age_years", None)
        age_months = getattr(user, "age_months", None)
        if type(age_years) is int and 0 <= age_years <= 150:
            age_parts.append(f"年龄填写值：{age_years}岁")
        if type(age_months) is int and 0 <= age_months <= 1800:
            age_parts.append(f"月龄填写值：{age_months}个月")
    if age_parts:
        context += "患者填写的一般资料（未获医护核验）：" + "；".join(age_parts) + "\n"
    return context


async def _patient_history_with_profile(db, patient_id, history=None):
    profile_context = await _load_health_profile_context(db, patient_id)
    if not profile_context:
        return history
    return profile_context + ("\n本次对话病史：\n" + history if history else "")


async def _build_conversation_context(
    db: AsyncSession,
    query_sid: str,
    messages: list[dict[str, str]],
    intent: str,
    user_id: str | None = None,
) -> None:
    """Inject full session context for post-diagnosis conversation (P0-2).

    When session phase is 'completed' and intent is not 'diagnosis',
    loads the diagnosis report, interview history, lab reports, and
    historical cases (for registered users) into the system prompt.
    """
    import uuid as _uuid

    try:
        session = await db.get(AgentSession, _uuid.UUID(query_sid))
    except (ValueError, Exception):
        return

    if not session or not session.context:
        return

    interview_data = session.context.get("interview")
    if not interview_data:
        return

    phase = interview_data.get("phase", "")
    if phase != "completed":
        return

    context_parts = [
        "## Patient Session Context\n"
        "The following is the complete consultation history and diagnosis for this patient. "
        "Base your response on this context.\n"
    ]

    # 1. Diagnosis Report
    if session.structured_output:
        report = session.structured_output
        context_parts.append("### Previous Diagnosis Report")
        context_parts.append(f"**Primary Diagnosis**: {report.get('primary_diagnosis', 'Unknown')}")
        context_parts.append(f"**Severity**: {report.get('severity', 'Unknown')}")
        context_parts.append(f"**Confidence**: {report.get('confidence', 'Unknown')}")
        if report.get('differential_diagnoses'):
            context_parts.append("**Differential Diagnoses**:")
            for d in report['differential_diagnoses'][:5]:
                if isinstance(d, dict):
                    context_parts.append(f"  - {d.get('diagnosis', '')}")
        if report.get('key_findings'):
            context_parts.append(f"**Key Findings**: {'; '.join(str(f) for f in report['key_findings'][:5])}")
        if report.get('recommended_actions'):
            context_parts.append(f"**Recommended Actions**: {'; '.join(str(a) for a in report['recommended_actions'][:5])}")
        if report.get('red_flags'):
            context_parts.append(f"**Red Flags**: {'; '.join(str(r) for r in report['red_flags'])}")
        context_parts.append("")

    # 2. Interview Q&A Summary
    collected = interview_data.get("collected_info", {})
    if collected:
        context_parts.append("### Collected Clinical Information")
        for k, v in collected.items():
            if not k.startswith("__") and v:
                v_str = str(v)[:200]
                context_parts.append(f"- **{k}**: {v_str}")
        context_parts.append("")

    # 3. Lab Reports
    lab_reports = session.context.get("lab_reports", [])
    if lab_reports:
        context_parts.append("### Lab / Examination Reports")
        for i, r in enumerate(lab_reports):
            indicators = r.get("indicators", [])
            if indicators:
                context_parts.append(f"**Report {i + 1}** (confidence: {int(r.get('overall_confidence', 0) * 100)}%):")
                for ind in indicators[:10]:
                    abn = " [ABNORMAL]" if ind.get("abnormal") else ""
                    context_parts.append(
                        f"  - {ind.get('indicator_name', '?')}: "
                        f"{ind.get('value', '?')} {ind.get('unit', '')}{abn}"
                    )
        context_parts.append("")

    # 4. Historical Cases (registered users only)
    if user_id:
        try:
            from app.tools.medical import QueryPatientHistoryTool
            history_tool = QueryPatientHistoryTool()
            history_result = await history_tool.execute(
                patient_id=user_id, limit=5, include_documents=False
            )
            cases = history_result.get("cases", [])
            if cases:
                context_parts.append("### Patient Historical Cases")
                for case in cases[:5]:
                    cc = case.get("chief_complaint") or case.get("title", "Unknown")
                    context_parts.append(f"- [{case.get('status', '?')}] {cc}")
                    dd = case.get("diagnosis_doctor") or case.get("ai_diagnosis_summary", "")
                    if dd:
                        context_parts.append(f"  Diagnosis: {dd[:150]}")
                context_parts.append("")

            # Load Health Profile (Context Pipeline)
            health_ctx = await _load_health_profile_context(db, user_id)
            if health_ctx:
                context_parts.append(health_ctx)
        except Exception:
            pass

    context_text = "\n".join(context_parts)
    context_text += (
        "\n---\nBased on the above context and the user's new message, provide a professional, coherent response."
        "\nLANGUAGE REQUIREMENT: Respond entirely in Simplified Chinese."
        " Keep diagnosis explanations, recommendations, warnings, and follow-up answers in Simplified Chinese."
        " Keep ICD codes, units, drug names, and standard medical abbreviations unchanged when appropriate."
    )

    messages.insert(0, {"role": "system", "content": context_text})


async def _build_chat_context(
    db: AsyncSession,
    parent: AgentSession,
    user_id: str | None = None,
) -> str:
    """Build system prompt for post-diagnosis chat (Plan C).

    Loads: parent diagnosis + interview + lab + sibling conversations + history.
    """
    parts = [
        "You are MedAxis, a medical AI assistant in a post-diagnosis conversation.\n"
        "LANGUAGE REQUIREMENT: Respond entirely in Simplified Chinese. "
        "All explanations, medical terms, recommendations, warnings, and follow-up answers "
        "must be in Simplified Chinese. Keep ICD codes, units, drug names, and standard "
        "medical abbreviations unchanged when appropriate.\n"
    ]

    if parent.structured_output:
        r = parent.structured_output
        parts.append("## Current Diagnosis")
        parts.append(f"Primary: {r.get('primary_diagnosis', 'Unknown')}")
        parts.append(f"Severity: {r.get('severity', 'Unknown')}")
        if r.get('key_findings'):
            parts.append(f"Findings: {'; '.join(str(f) for f in r['key_findings'][:5])}")
        if r.get('recommended_actions'):
            parts.append(f"Actions: {'; '.join(str(a) for a in r['recommended_actions'][:5])}")
        parts.append("")

    interview = (parent.context or {}).get("interview", {})
    collected = interview.get("collected_info", {})
    if collected:
        parts.append("## Patient History")
        for k, v in collected.items():
            if not k.startswith("__") and v:
                parts.append(f"- {k}: {str(v)[:200]}")
        parts.append("")

    lab_reports = (parent.context or {}).get("lab_reports", [])
    if lab_reports:
        parts.append("## Lab Reports")
        for r in lab_reports:
            for ind in r.get("indicators", [])[:10]:
                abn = " [ABNORMAL]" if ind.get("abnormal") else ""
                parts.append(f"  - {ind.get('indicator_name', '?')}: {ind.get('value', '?')}{abn}")
        parts.append("")

    # Sibling conversations
    from sqlalchemy import select as _sel
    sib_stmt = (
        _sel(AgentSession)
        .where(AgentSession.parent_session_id == parent.id)
        .where(AgentSession.session_type == AgentSessionType.CONVERSATION)
        .order_by(AgentSession.created_at.asc())
    )
    sib_result = await db.execute(sib_stmt)
    siblings = sib_result.scalars().all()
    if siblings:
        parts.append("## Previous Conversation")
        for sib in siblings:
            ctx = sib.context or {}
            um = ctx.get("user_message", "")
            ar = ctx.get("assistant_response", "")
            if um:
                parts.append(f"User: {um[:200]}")
            if ar:
                parts.append(f"Assistant: {ar[:300]}")
            parts.append("")

    # Historical cases (registered users)
    if user_id:
        try:
            from app.tools.medical import QueryPatientHistoryTool
            ht = QueryPatientHistoryTool()
            hr = await ht.execute(patient_id=user_id, limit=3, include_documents=False)
            cases = hr.get("cases", [])
            if cases:
                parts.append("## Historical Cases")
                for c in cases[:3]:
                    cc = c.get("chief_complaint") or c.get("title", "?")
                    parts.append(f"- {cc}")
                    dd = c.get("diagnosis_doctor") or c.get("ai_diagnosis_summary", "")
                    if dd:
                        parts.append(f"  Dx: {dd[:150]}")
                parts.append("")
        except Exception:
            pass

    parts.append("---\nRespond based on all above context.")
    if user_id:
        health_context = await _load_health_profile_context(db, user_id)
        if health_context:
            parts.append(health_context)
    context_text = "\n".join(parts)

    import logging as _diag_log
    _diag = _diag_log.getLogger("chat.context")
    _diag.info(
        "[CHAT-CTX] session=%s total_chars=%d diagnosis=%d collected_keys=%d "
        "lab_reports=%d lab_indicators=%d siblings=%d",
        str(parent.id),
        len(context_text),
        len(str(parent.structured_output or {})),
        len(collected),
        len(lab_reports),
        sum(len(r.get("indicators", [])) for r in lab_reports),
        len(siblings) if siblings else 0,
    )

    return context_text


# ---------------------------------------------------------------------------
# Helper: DiagnosisReport → Markdown
# ---------------------------------------------------------------------------

def _diagnosis_report_to_markdown(report: dict[str, Any]) -> str:
    """Convert DiagnosisReport dict to Markdown for frontend rendering."""
    lines: list[str] = []
    _unknown = "\u672a\u77e5"
    _pending = "\u5f85\u5b9a"
    severity_labels = {
        "mild": "轻度",
        "moderate": "中度",
        "severe": "重度",
        "emergency": "紧急",
        "unknown": _unknown,
    }
    confidence_labels = {
        "high": "高",
        "medium": "中",
        "low": "低",
    }

    if report.get("interview_is_sufficient") is False:
        lines.append("### 阶段摘要：仍有信息待核对")
        lines.append("已整理目前提供的信息；停止补问不表示信息已充分。")
        lines.extend(f"- {gap}" for gap in report.get("interview_information_gaps", []))
    lines.append("### \ud83c\udfe5 \u521d\u6b65\u8bca\u65ad")
    lines.append("**" + report.get("primary_diagnosis", _unknown) + "**")
    lines.append("")

    if report.get("differential_diagnoses"):
        lines.append("### \ud83d\udd0d \u9274\u522b\u8bca\u65ad")
        for d in report["differential_diagnoses"]:
            if isinstance(d, dict):
                diag_name = d.get("diagnosis", "")
                reasoning = d.get("reasoning", "")
                lines.append(f"- **{diag_name}**: {reasoning}")
            else:
                lines.append("- " + str(d))
        lines.append("")

    severity = str(report.get("severity", "unknown"))
    severity_emoji = {"mild": "\ud83d\udfe2", "moderate": "\ud83d\udfe1", "severe": "\ud83d\udd34", "emergency": "\u26d4"}.get(severity, "")
    lines.append("**\u4e25\u91cd\u7a0b\u5ea6**: " + severity_emoji + " " + severity_labels.get(severity, severity))
    confidence = str(report.get("confidence", "unknown"))
    lines.append("**\u7f6e\u4fe1\u5ea6**: " + confidence_labels.get(confidence, confidence if confidence != "unknown" else _unknown))
    lines.append("")

    if report.get("key_findings"):
        lines.append("### \ud83d\udccb \u5173\u952e\u53d1\u73b0")
        for f in report["key_findings"]:
            lines.append("- " + str(f))
        lines.append("")

    if report.get("recommended_tests"):
        lines.append("### \ud83e\uddea \u63a8\u8350\u68c0\u67e5")
        for t in report["recommended_tests"]:
            lines.append("- " + str(t))
        lines.append("")

    if report.get("recommended_actions"):
        lines.append("### \ud83d\udc8a \u5efa\u8bae\u63aa\u65bd")
        for a in report["recommended_actions"]:
            lines.append("- " + str(a))
        lines.append("")

    if report.get("contraindications"):
        lines.append("### \u26a0\ufe0f \u7981\u5fcc\u4e8b\u9879")
        for c in report["contraindications"]:
            lines.append("- " + str(c))
        lines.append("")

    if report.get("red_flags"):
        lines.append("### \ud83d\udea8 \u5371\u9669\u4fe1\u53f7\uff08\u9700\u7acb\u5373\u5c31\u533b\uff09")
        for r in report["red_flags"]:
            lines.append("- " + str(r))
        lines.append("")

    if report.get("follow_up_required"):
        lines.append("### \ud83d\udcc5 \u968f\u8bbf")
        lines.append("\u9700\u8981\u968f\u8bbf\uff0c\u65f6\u95f4: " + report.get("follow_up_timeline", _pending))
        lines.append("")

    citations = report.get("knowledge_citations")
    valid_citations = [
        citation for citation in citations
        if isinstance(citation, dict)
        and isinstance(citation.get("citation_id"), str)
        and re.fullmatch(r"S\d+", citation["citation_id"])
        and isinstance(citation.get("title"), str)
        and isinstance(citation.get("excerpt"), str)
        and citation.get("source_type") in {"internal", "external"}
    ] if isinstance(citations, list) else []
    if valid_citations:
        lines.append("### \ud83d\udcda \u77e5\u8bc6\u6765\u6e90")
        lines.append("引用可追溯不等于陈述已获原文支持；原文一致也不代表医学适用性已审核。")
        for citation in valid_citations:
            citation_id = citation["citation_id"]
            title = citation["title"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            excerpt = citation["excerpt"].replace("\r", " ").replace("\n", " ").replace("\t", " ")
            if citation["source_type"] == "internal":
                lines.append(f"- [{citation_id}] **内部知识库｜{title}**")
                document_id = citation.get("document_id")
                chunk_id = citation.get("chunk_id")
                chunk_index = citation.get("chunk_index")
                locator = []
                if isinstance(document_id, str) and document_id:
                    locator.append(f"文档ID：{document_id}")
                if isinstance(chunk_index, int):
                    locator.append(f"片段序号：{chunk_index + 1}")
                if isinstance(chunk_id, str) and chunk_id:
                    locator.append(f"片段ID：{chunk_id}")
                if locator:
                    lines.append("  - " + "；".join(locator))
            else:
                lines.append(f"- [{citation_id}] **外部来源｜{title}**")
                url = citation.get("url")
                if isinstance(url, str):
                    parsed_url = urlsplit(url.strip())
                    if (
                        parsed_url.scheme in {"http", "https"}
                        and parsed_url.hostname
                        and not any(char.isspace() or char in "<>" for char in url)
                    ):
                        lines.append(f"  - 链接：<{url.strip()}>")
            if excerpt:
                lines.append(f"  - 摘录：{excerpt}")
            evidence = report.get("knowledge_evidence")
            rows = [row for row in evidence if isinstance(row, dict) and row.get("citation_id") == citation_id] if isinstance(evidence, list) else []
            for row in rows:
                status = "原文一致（适用性待专业核对）" if evidence_matches_excerpt(row, citation) else "待核对"
                lines.append(f"  - {status}：{row.get('claim', '')}")
            if not rows:
                lines.append("  - 尚无逐条原文核对记录。")
        lines.append("")
    elif report.get("knowledge_sources"):
        lines.append("### \ud83d\udcda \u77e5\u8bc6\u6765\u6e90")
        lines.append("以下为旧版来源名称，缺少逐条检索记录，暂无法核验。")
        for source in report["knowledge_sources"]:
            lines.append("- " + str(source))
        lines.append("")
    elif report.get("knowledge_retrieval_status") == "retrieved_not_cited":
        lines.append("### \ud83d\udcda \u77e5\u8bc6\u6765\u6e90")
        lines.append("本次检索到了资料，但报告未建立逐条引用，因此不将其列为已引用依据。")
        lines.append("")
    elif report.get("knowledge_retrieval_status") == "failed":
        lines.append("### \ud83d\udcda \u77e5\u8bc6\u6765\u6e90")
        lines.append("本次知识检索失败，报告未附可核验的知识来源。")
        lines.append("")
    elif report.get("knowledge_retrieval_status") == "no_sources":
        lines.append("### \ud83d\udcda \u77e5\u8bc6\u6765\u6e90")
        lines.append("本次没有检索到可核验的知识来源。")
        lines.append("")

    disclaimer = report.get("disclaimer")
    if disclaimer:
        lines.append("> " + str(disclaimer))

    return "\n".join(lines)


def _chunk_text(text: str, chunk_size: int = 80) -> list[str]:
    """Split text into chunks for SSE streaming simulation."""
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RouteRequest(BaseModel):
    """Natural language input for MasterAgent routing."""

    message: str = Field(..., min_length=1, max_length=2000, description="Patient message")
    patient_id: str | None = Field(None, description="Patient UUID if authenticated")
    patient_history: str | None = Field(None, max_length=5000)
    provider: str | None = None


class RouteStreamRequest(BaseModel):
    """流式问诊提交；病史与主诉放在请求体，避免进入访问日志 URL。"""

    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(None, max_length=36)
    patient_history: str | None = Field(None, max_length=3000)
    provider: str | None = None


def _reject_query_auth_token(request: Request) -> None:
    """患者模型 SSE 只接受 Header/Cookie 凭证，避免令牌进入 URL 日志。"""
    if any(name in request.query_params for name in ("token", "guest_token", "access_token")):
        raise HTTPException(
            status_code=400,
            detail="请通过请求头传递认证凭据。",
        )


def _reject_patient_text_in_query(request: Request, *field_names: str) -> None:
    if any(name in request.query_params for name in field_names):
        raise HTTPException(
            status_code=400,
            detail="患者内容必须放在请求体中。",
        )


class DiagnosisRequest(BaseModel):
    """Symptom analysis request with Tool Use."""

    symptoms: str = Field(..., min_length=5, max_length=2000)
    patient_id: str | None = Field(None, description="Patient UUID for history lookup")
    patient_history: str | None = Field(None, max_length=5000)
    test_results: str | None = Field(None, max_length=5000)
    provider: str | None = None


class PlanningRequest(BaseModel):
    """Treatment planning request."""

    diagnosis: str = Field(..., min_length=5, max_length=2000)
    patient_profile: dict[str, Any] | None = None
    constraints: list[str] | None = None
    provider: str | None = None


class MonitoringRequest(BaseModel):
    """Monitoring check request."""

    patient_updates: str = Field(..., min_length=5, max_length=3000)
    baseline_status: str | None = None
    current_plan: str | None = None
    provider: str | None = None


class ConsultationRequest(BaseModel):
    """Full multi-agent consultation request."""

    symptoms: str = Field(..., min_length=5, max_length=2000)
    patient_id: str | None = Field(None)
    patient_history: str | None = Field(None, max_length=5000)
    patient_profile: dict[str, Any] | None = None
    provider: str | None = None


class SessionListResponse(BaseModel):
    """Agent session list item."""

    id: str
    session_type: str
    status: str
    intent: str | None
    created_at: str
    updated_at: str


def _resolve_patient_scope(ctx: UserContext, requested_patient_id: str | None) -> str | None:
    """拒绝请求体指定他人身份；未指定时沿用当前会话身份。"""
    if requested_patient_id is not None:
        try:
            requested_id = uuid.UUID(requested_patient_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Patient identity must come from the authenticated session",
            ) from exc

        if (
            ctx.user is None
            or ctx.user.role != UserRole.PATIENT
            or requested_id != ctx.user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Patient identity must come from the authenticated session",
            )

    if ctx.user is not None:
        return str(ctx.user.id)
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/route", status_code=status.HTTP_200_OK)
async def route_request(
    req: RouteRequest,
    ctx: CurrentUserOrActiveGuest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """MasterAgent: classify intent and route to the appropriate Agent."""
    patient_id = _resolve_patient_scope(ctx, req.patient_id)
    async def _run() -> dict[str, Any]:
        orchestrator = AgentOrchestrator(provider=req.provider, platform=ctx.platform)
        return await orchestrator.route(
            user_input=req.message,
            patient_id=patient_id,
            patient_history=await _patient_history_with_profile(db, patient_id, req.patient_history),
        )

    return await run_guest_submission(
        db,
        ctx,
        submission_id=idempotency_key,
        endpoint="agents.route",
        request_payload=req.model_dump(mode="json"),
        operation=_run,
    )


@router.post("/diagnose", status_code=status.HTTP_200_OK)
async def diagnose(
    req: DiagnosisRequest,
    ctx: CurrentUserOrActiveGuest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """DiagnosisAgent: structured diagnosis with Tool Use."""
    patient_id = _resolve_patient_scope(ctx, req.patient_id)
    async def _run() -> dict[str, Any]:
        agent = DiagnosisAgent(provider=req.provider)
        try:
            result = await agent.analyze(
                symptoms=req.symptoms,
                patient_id=patient_id,
                patient_history=await _patient_history_with_profile(db, patient_id, req.patient_history),
                test_results=req.test_results,
            )
        except MedicalEvidenceUnavailableError as exc:
            raise HTTPException(status_code=503, detail=patient_llm_error(exc)) from exc
        return {
            "agent": "diagnosis",
            "structured": result.structured_output.model_dump() if result.structured_output else None,
            "content": result.content,
            "tool_calls_used": result.tool_calls_used,
            "session_id": result.session_id,
        }

    return await run_guest_submission(
        db,
        ctx,
        submission_id=idempotency_key,
        endpoint="agents.diagnose",
        request_payload=req.model_dump(mode="json"),
        operation=_run,
    )


@router.post("/plan", status_code=status.HTTP_200_OK)
async def plan_treatment(
    req: PlanningRequest,
    ctx: CurrentUserOrActiveGuest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """PlanningAgent: structured treatment plan."""
    async def _run() -> dict[str, Any]:
        agent = PlanningAgent(provider=req.provider)
        result = await agent.plan(
            diagnosis=req.diagnosis,
            patient_profile=req.patient_profile,
            constraints=req.constraints,
        )
        return {
            "agent": "planning",
            "structured": result.structured_output.model_dump() if result.structured_output else None,
            "content": result.content,
        }

    return await run_guest_submission(
        db,
        ctx,
        submission_id=idempotency_key,
        endpoint="agents.plan",
        request_payload=req.model_dump(mode="json"),
        operation=_run,
    )


@router.post("/monitor", status_code=status.HTTP_200_OK)
async def monitor(
    req: MonitoringRequest,
    ctx: CurrentUserOrActiveGuest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """MonitoringAgent: structured monitoring assessment."""
    async def _run() -> dict[str, Any]:
        agent = MonitoringAgent(provider=req.provider)
        result = await agent.check(
            patient_updates=req.patient_updates,
            baseline_status=req.baseline_status,
            current_plan=req.current_plan,
        )
        return {
            "agent": "monitoring",
            "structured": result.structured_output.model_dump() if result.structured_output else None,
            "content": result.content,
        }

    return await run_guest_submission(
        db,
        ctx,
        submission_id=idempotency_key,
        endpoint="agents.monitor",
        request_payload=req.model_dump(mode="json"),
        operation=_run,
    )


@router.post("/consult", status_code=status.HTTP_200_OK)
async def full_consultation(
    req: ConsultationRequest,
    ctx: CurrentUserOrActiveGuest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """Full multi-agent consultation (diagnosis + plan + monitoring)."""
    patient_id = _resolve_patient_scope(ctx, req.patient_id)
    async def _run() -> dict[str, Any]:
        orchestrator = AgentOrchestrator(provider=req.provider, platform=ctx.platform)
        return await orchestrator.route(
            user_input=req.symptoms,
            patient_id=patient_id,
            patient_history=req.patient_history,
        )

    return await run_guest_submission(
        db,
        ctx,
        submission_id=idempotency_key,
        endpoint="agents.consult",
        request_payload=req.model_dump(mode="json"),
        operation=_run,
    )


@router.get("/sessions", response_model=list[SessionListResponse])
async def list_sessions(
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(UserRole.ADMIN, UserRole.DOCTOR)),
) -> list[SessionListResponse]:
    """List Agent sessions (admin/doctor only).

    Query params:
    - status: active, completed, escalated, failed
    - type: diagnosis, planning, monitoring, consultation
    """
    stmt = select(AgentSession).order_by(AgentSession.created_at.desc())

    if status_filter:
        stmt = stmt.where(AgentSession.status == AgentSessionStatus(status_filter))
    if type_filter:
        from app.models.agent import AgentSessionType
        stmt = stmt.where(AgentSession.session_type == AgentSessionType(type_filter.upper()))

    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return [
        SessionListResponse(
            id=str(s.id),
            session_type=s.session_type.value,
            status=s.status.value,
            intent=s.intent,
            created_at=s.created_at.isoformat() if s.created_at else "",
            updated_at=s.updated_at.isoformat() if s.updated_at else "",
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(UserRole.ADMIN, UserRole.DOCTOR)),
) -> dict[str, Any]:
    """Get full Agent session details."""
    import uuid as uuid_module

    stmt = select(AgentSession).where(AgentSession.id == uuid_module.UUID(session_id))
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "id": str(session.id),
        "session_type": session.session_type.value,
        "status": session.status.value,
        "intent": session.intent,
        "context": session.context,
        "tool_calls": session.tool_calls,
        "structured_output": session.structured_output,
        "escalation_reason": session.escalation_reason,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


# ---------------------------------------------------------------------------
# Streaming SSE endpoints (backend-ready, frontend to integrate later)
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/lab-reports")
async def store_lab_reports(
    session_id: str,
    ctx: CurrentUserContext,
    reports: list[dict[str, Any]] = Body(default_factory=list),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """把已完成的自有上传关联到会话；报告内容以数据库解析结果为准。"""
    if ctx.user is None:
        try:
            guest_id = uuid.UUID(ctx.guest_id or "")
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Valid guest session required") from exc
        guest = await db.get(GuestSession, guest_id)
        if guest is None or guest.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Guest session has expired")

    file_ids = list(dict.fromkeys(str(report.get("file_id", "")) for report in reports))
    file_ids = [file_id for file_id in file_ids if file_id]
    if not file_ids:
        raise HTTPException(status_code=400, detail="At least one uploaded file_id is required")

    result = await db.execute(
        select(DocumentParseTask).where(
            DocumentParseTask.file_id.in_(file_ids),
            _parse_task_owner_filter(ctx),
            DocumentParseTask.status == "completed",
        )
    )
    tasks = result.scalars().all()
    if len(tasks) != len(file_ids):
        raise HTTPException(status_code=404, detail="One or more parsed documents were not found")

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        session_uuid = None
    session = None
    if session_uuid is not None:
        session = await db.get(AgentSession, session_uuid)
        if session is None or not _session_belongs_to_context(session, ctx):
            raise HTTPException(status_code=404, detail="Session not found")
    elif any(task.client_session_id != session_id for task in tasks):
        raise HTTPException(status_code=404, detail="Session not found")

    lab_reports = [task.result for task in tasks if task.result]
    for task in tasks:
        if session is not None:
            task.source_session_id = session.id
            task.client_session_id = task.client_session_id or (session.context or {}).get("_frontend_sid")
            case_result = await db.execute(
                select(MedicalCase).where(MedicalCase.source_session_id == session.id)
            )
            case = case_result.scalar_one_or_none()
            if case is not None:
                task.case_id = case.id

    if session is not None:
        session_context = dict(session.context or {})
        existing = session_context.get("lab_reports", [])
        by_file_id = {str(report.get("file_id")): report for report in existing if report.get("file_id")}
        by_file_id.update({str(report.get("file_id")): report for report in lab_reports if report.get("file_id")})
        session_context["lab_reports"] = list(by_file_id.values())
        session.context = session_context

    await db.commit()
    return {"status": "stored", "session_id": session_id, "count": len(lab_reports)}

@router.post("/route/stream")
async def route_stream(
    req: RouteStreamRequest,
    request: Request,
    ctx: CurrentUserContextLenientNoQuery,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> StreamingResponse:
    """MasterAgent intent classification + streaming multi-agent response via SSE.

    Frontend connects with fetch + ReadableStream SSE so credentials and patient
    text stay out of the URL.

    SSE Events:
        intent          →  MasterAgent 意图分类结果
        agent_switch    →  切换到专科 Agent
        thinking        →  Agent 分析思考过程
        tool_call       →  调用工具
        tool_result     →  工具返回结果
        text            →  流式文本片段
        structured      →  结构化诊断报告
        complete        →  流结束
        error           →  错误
    """
    _reject_query_auth_token(request)
    _reject_patient_text_in_query(request, "message", "patient_history")
    has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
    # Registered user with expired Bearer token: return 401 so frontend refreshes
    if has_bearer and ctx.user is None and not ctx.is_guest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please refresh.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if ctx.user is None and not ctx.is_guest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先创建访客会话再发起问诊。",
        )

    if ctx.is_guest and ctx.guest_id:
        try:
            guest = await db.get(GuestSession, uuid.UUID(ctx.guest_id))
        except ValueError:
            guest = None
        if guest is None or guest.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Guest session has expired")

    message = req.message
    submission_id = idempotency_key
    query_sid = req.session_id
    patient_history = await _patient_history_with_profile(
        db, str(ctx.user.id) if ctx.user else None, req.patient_history,
    )
    provider = req.provider
    if query_sid:
        try:
            queried_session = await db.get(AgentSession, uuid.UUID(query_sid))
        except ValueError:
            queried_session = None
        if queried_session is not None and not _session_belongs_to_context(queried_session, ctx):
            raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        completed_case_id: str | None = None
        try:
                master = AgentOrchestrator(provider=provider, platform=ctx.platform)
                actual_patient_id = str(ctx.user.id) if ctx.user else None

                yield f"event: thinking\ndata: {json.dumps({'step': 'master', 'message': '🧠 MasterAgent 正在分析您的需求...'})}\n\n"

                # Load session context for context-aware intent classification
                session_context = None
                if query_sid:
                    try:
                        existing_session = await db.get(AgentSession, uuid.UUID(query_sid))
                        if existing_session and not _session_belongs_to_context(existing_session, ctx):
                            raise HTTPException(status_code=404, detail="Session not found")
                        if existing_session and existing_session.context:
                            interview = existing_session.context.get("interview", {})
                            phase = interview.get("phase", "")
                            structured = existing_session.structured_output

                            if phase == "completed" and structured:
                                session_ctx: dict[str, Any] = {"has_completed_diagnosis": True}

                                primary = structured.get("primary_diagnosis", "")
                                severity = structured.get("severity", "")
                                if primary:
                                    session_ctx["diagnosis_summary"] = (
                                        f"Primary: {primary}"
                                        + (f" Severity: {severity}" if severity else "")
                                    )

                                collected = interview.get("collected_info", {})
                                if collected:
                                    session_ctx["interview_collected"] = collected

                                session_context = session_ctx
                    except HTTPException:
                        raise
                    except Exception:
                        pass

                intent_result = await master.master.classify_intent(message, session_context=session_context)
                intent = intent_result.get("intent", "diagnosis")
                confidence = intent_result.get("confidence", "medium")
                reasoning = intent_result.get("reasoning", "")

                yield f"event: intent\ndata: {json.dumps(intent_result)}\n\n"
                yield f"event: thinking\ndata: {json.dumps({'step': 'master_done', 'message': f'✅ 意图识别完成: {intent} (置信度: {confidence})', 'detail': reasoning})}\n\n"

                # ─── Step 2: Agent 切换 ───
                agent_name_map = {
                    "diagnosis": "DiagnosisAgent 诊断专家",
                    "planning": "PlanningAgent 治疗规划",
                    "monitoring": "MonitoringAgent 随访监测",
                    "research": "ResearchAgent 医学研究",
                    "consultation": "Consultation 综合诊疗",
                    "general": "General 通用医疗",
                }
                # Escalation is now handled within the diagnosis pipeline — not a separate route
                if intent == "escalation":
                    intent = "diagnosis"
                agent_display = agent_name_map.get(intent, agent_name_map["general"])

                yield f"event: agent_switch\ndata: {json.dumps({'agent': intent, 'agent_display': agent_display, 'message': f'🔄 正在切换到 {agent_display}...'})}\n\n"

                # ─── Step 3: 专科 Agent 处理 + 流式输出 ───
                async with async_session_maker() as db_stream:
                    llm = LLMService(provider=provider, platform=ctx.platform, db=db_stream)

                    # 根据意图构建专属 system prompt
                    system_prompts = {
                        "diagnosis": """You are DiagnosisAgent, an expert diagnostic AI physician.

        ROLE:
        - Analyze patient symptoms thoroughly
        - Consider differential diagnoses
        - Ask clarifying questions when needed
        - Flag emergency conditions immediately

        OUTPUT FORMAT:
        Use Markdown formatting:
        - **bold** for important medical terms
        - bullet lists for findings/suggestions
        - numbered lists for step-by-step advice
        - ### headers for sections

        Always include:
        1. Possible causes analysis
        2. Key questions to narrow down
        3. Self-care recommendations
        4. Red flags requiring immediate medical attention
        5. Disclaimer

        LANGUAGE REQUIREMENT:
        - Respond entirely in Simplified Chinese.
        - Write diagnosis names, explanations, findings, examination recommendations,
          self-care advice, warning signs, follow-up plans, and disclaimers in Simplified Chinese.
        - Keep ICD codes, laboratory units, drug names, and standard medical abbreviations unchanged
          when appropriate.
        - Do not switch to English because the prompt or medical references are in English.

        SAFETY: Never dismiss patient concerns. Flag emergencies.""",

                        "planning": """You are PlanningAgent, an expert treatment planning AI.

        ROLE:
        - Generate evidence-based treatment plans
        - Recommend medications with dosing when appropriate
        - Suggest lifestyle modifications
        - Plan follow-up schedule

        OUTPUT FORMAT:
        Use Markdown formatting with clear sections.""",

                        "monitoring": """You are MonitoringAgent, a patient follow-up AI.

        ROLE:
        - Analyze patient-reported outcomes
        - Detect deterioration or improvement trends
        - Generate alerts when thresholds are crossed

        OUTPUT FORMAT:
        Use Markdown formatting.""",

                        "research": """You are ResearchAgent, a medical research assistant.

        ROLE:
        - Synthesize medical knowledge into clear answers
        - Cite sources when possible
        - Distinguish evidence levels

        OUTPUT FORMAT:
        Use Markdown formatting.""",

                        "general": """You are MedAxis, a helpful medical AI assistant.

        ROLE:
        - Provide accurate, evidence-based medical information
        - Be clear and compassionate
        - Always include appropriate disclaimers

        OUTPUT FORMAT:
        Use Markdown formatting for readability.""",
                    }

                    system_prompt = system_prompts.get(intent, system_prompts["general"])

                    # 添加患者上下文
                    messages: list[dict[str, str]] = [{"role": "user", "content": message}]
                    if patient_history:
                        messages.insert(0, {"role": "system", "content": f"Patient history context: {patient_history}"})

                    # 从当前身份拥有的持久化任务恢复已解析报告。
                    session_id: str | None = None
                    lab_reports: list[dict[str, Any]] = []
                    if query_sid:
                        lab_reports = await _load_session_lab_reports(db, ctx, query_sid)
                        if lab_reports:
                            _inject_lab_context(messages, lab_reports)
                    if intent == "diagnosis":
                        # ─── Interview phase: collect info before diagnosis ───
                        # Create a session to persist interview state (if not already loaded)
                        if not session_id:
                            try:
                                new_session = await master._create_session(
                                    user_id=uuid.UUID(actual_patient_id) if actual_patient_id else None,
                                    session_type=AgentSessionType.DIAGNOSIS,
                                    intent="diagnosis",
                                )
                                if new_session:
                                    session_id = str(new_session.id)
                                    _nctx = dict(new_session.context or {})
                                    if query_sid:
                                        _nctx["_frontend_sid"] = query_sid
                                    if lab_reports:
                                        _nctx["lab_reports"] = lab_reports
                                    new_session.context = _nctx
                                    new_session.guest_session_id = (
                                        uuid.UUID(ctx.guest_id) if ctx.is_guest and ctx.guest_id else None
                                    )
                                    async with async_session_maker() as _bdb:
                                        _bs = await _bdb.get(AgentSession, uuid.UUID(session_id))
                                        if _bs:
                                            _bs.context = _nctx
                                            _bs.guest_session_id = new_session.guest_session_id
                                            if query_sid:
                                                _files = await _bdb.execute(
                                                    select(DocumentParseTask).where(
                                                        _parse_task_owner_filter(ctx),
                                                        DocumentParseTask.client_session_id == query_sid,
                                                    )
                                                )
                                                for _file in _files.scalars().all():
                                                    _file.source_session_id = _bs.id
                                            await _bdb.commit()
                            except Exception:
                                pass

                        if not session_id:
                            yield _patient_error_event(
                                "DIAGNOSIS_SESSION_CREATION_FAILED",
                                "诊断会话未能保存，本次未生成诊断报告，请稍后重试。",
                                "initial_session_creation",
                            )
                            return

                        diag_agent = DiagnosisAgent(provider=provider, platform=ctx.platform)

                        if session_id:
                            try:
                                questions, state, searches, action, reasoning = await diag_agent.interview(
                                    session_id=session_id,
                                    chief_complaint=message,
                                    patient_history=patient_history,
                                )
                                if searches:
                                    yield f"event: thinking\ndata: {json.dumps({'step': 'search', 'message': '🔍 后台搜索中，请先作答...'})}\n\n"
                                if questions:
                                    yield f"event: interview_progress\ndata: {json.dumps({'asked_count': len(state.asked_questions), 'phase': '问诊中'})}\n\n"
                                    q_list = []
                                    for nq in questions:
                                        q_list.append({
                                            "question_id": nq.question_id, "question": nq.question, "type": nq.type,
                                            "options": nq.options, "hint": nq.hint, "allow_skip": nq.allow_skip,
                                            "phase": nq.phase, "colloquial_phase": nq.colloquial_phase, "reason": nq.reason,
                                        })
                                    yield f"event: question\ndata: {json.dumps({'questions': q_list})}\n\n"
                                    yield f"event: complete\ndata: {json.dumps({'status': 'waiting_for_answer', 'session_id': session_id})}\n\n"
                                    return
                                elif state.red_flags_detected:
                                    yield f"event: red_flags\ndata: {json.dumps({'red_flags': state.red_flags_detected, 'message': '检测到危险信号，建议立即就医'})}\n\n"
                                    # Do NOT return — proceed to diagnosis with red flags included

                                if action == "ask":
                                    yield f"event: complete\ndata: {json.dumps({'status': 'waiting_for_answer', 'session_id': session_id})}\n\n"
                                    return

                                # Redis lock first — prevent concurrent diagnoses
                                from app.db.redis_client import get_redis
                                redis_client = get_redis()
                                lock_key = f"diag_lock:{session_id}"
                                locked = await redis_client.set(lock_key, "1", nx=True, ex=300)
                                if not locked:
                                    yield f"event: complete\ndata: {json.dumps({'status': 'already_diagnosed', 'session_id': session_id})}\n\n"
                                    return

                                stage_message = '🧠 正在整理阶段摘要，未确认的信息会保留...' if not state.is_sufficient else '🧠 正在整理问诊信息并检索参考资料...'
                                yield f"event: thinking\ndata: {json.dumps({'step': 'diagnosis', 'message': stage_message})}\n\n"

                                workflow_result = await diag_agent.run_full_diagnosis_workflow(
                                    session_id=session_id,
                                    patient_id=actual_patient_id,
                                    patient_history=patient_history,
                                )
                                if workflow_result.tool_calls_used:
                                    for tc in workflow_result.tool_calls_used:
                                        tname = tc.get('tool', '?')
                                        yield f"event: tool_call\ndata: {json.dumps({'tool': tname, 'params': tc.get('arguments', {}), 'message': '🔍 正在执行 ' + tname + '...'})}\n\n"
                                        await asyncio.sleep(0.2)
                                        yield f"event: tool_result\ndata: {json.dumps({'tool': tname, 'result': tc.get('result', {}), 'message': '✅ ' + tname + ' 执行完成'})}\n\n"
                                if workflow_result.structured_output:
                                    report = workflow_result.structured_output.model_dump()
                                    if actual_patient_id and session_id:
                                        try:
                                            saved_case = await persist_diagnosis_case(
                                                db,
                                                patient_id=uuid.UUID(actual_patient_id),
                                                source_session_id=uuid.UUID(session_id),
                                                report=report,
                                                fallback_chief_complaint=message,
                                            )
                                            completed_case_id = str(saved_case.id)
                                        except DiagnosisCasePersistenceError:
                                            yield _patient_error_event(
                                                "CASE_PERSISTENCE_FAILED",
                                                "诊断结果未能保存为病例，本次未标记为已保存，请稍后重试。",
                                                "initial_case_persistence",
                                            )
                                            return
                                    yield f"event: structured\ndata: {json.dumps(report)}\n\n"
                                    report_md = _diagnosis_report_to_markdown(report)
                                    for chunk in _chunk_text(report_md, chunk_size=80):
                                        yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                                else:
                                    content = workflow_result.content if isinstance(workflow_result.content, str) else ''
                                    for chunk in _chunk_text(content, chunk_size=80):
                                        yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                                yield f"event: complete\ndata: {json.dumps({'message': '✅ 响应完成', 'session_id': session_id, 'case_id': completed_case_id})}\n\n"
                                return
                            except Exception as exc:
                                from app.services.orchestrator import InterviewGenerationError
                                if isinstance(exc, InterviewGenerationError):
                                    yield _patient_llm_error_event(
                                        exc,
                                        "initial_interview",
                                        code="INTERVIEW_GENERATION_FAILED",
                                        message="问诊问题生成失败，请重试；本次未跳过问诊生成诊断报告。",
                                    )
                                    return
                                yield _patient_llm_error_event(exc, "initial_interview")
                                return

                    else:
                        # 其他意图走通用 LLM 流
                        try:
                            async for chunk in llm.chat_stream(
                                messages=messages,
                                system_prompt=system_prompt,
                                max_tokens=2048,
                            ):
                                yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                        except Exception as e:
                            yield _patient_llm_error_event(e, "general_chat")
                            return

                yield f"event: complete\ndata: {json.dumps({'message': '✅ 响应完成', 'case_id': completed_case_id})}\n\n"

        except asyncio.CancelledError:
            _log_patient_llm_interruption("initial_stream")
            raise
        except Exception as e:
            yield _patient_llm_error_event(e, "initial_stream")
    return await stream_guest_submission(
        db,
        ctx,
        submission_id=submission_id,
        endpoint="agents.route.stream",
        request_payload={
            "message": message,
            "session_id": query_sid,
            "patient_history": patient_history,
            "provider": provider,
        },
        event_generator=event_generator,
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/route/stream/continue")
async def route_stream_continue(
    request: Request,
    ctx: CurrentUserContextLenientNoQuery,
    session_id: str = Query(...),
    question_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> StreamingResponse:
    """Continue an interrupted interview/diagnosis stream after user answers."""
    _reject_query_auth_token(request)
    _reject_patient_text_in_query(request, "answer")
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="续答内容格式无效。") from exc
    else:
        # 路由只注册 POST；保留直接调用时的空答案默认值。
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="续答内容格式无效。")
    _answer = body.get("answer") or "无"
    if not isinstance(_answer, str):
        raise HTTPException(status_code=400, detail="续答内容格式无效。")

    try:
        session = await db.get(AgentSession, uuid.UUID(session_id))
    except ValueError:
        session = None
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _require_session_access(db, session, ctx)

    patient_history = await _patient_history_with_profile(
        db, str(session.user_id) if session.user_id else None,
    )

    async def event_generator():
        completed_case_id: str | None = None
        try:
                # If diagnosis is already in progress, skip — avoid snapshot race
                try:
                    from app.db.redis_client import get_redis
                    _r = get_redis()
                    if await _r.exists(f"diag_lock:{session_id}"):
                        yield f"event: complete\ndata: {json.dumps({'status': 'diagnosis_in_progress', 'session_id': session_id})}\n\n"
                        return
                except Exception:
                    pass

                diag_agent = DiagnosisAgent(provider=None, platform=ctx.platform)

                yield f"event: thinking\ndata: {json.dumps({'step': 'processing', 'message': '🧠 正在分析您的回答...'})}\n\n"

                try:
                    import logging as _lmod2
                    questions, state, searches, action, reasoning = await diag_agent.interview_answer(
                        session_id=session_id,
                        question_id=question_id,
                        answer=_answer,
                        patient_history=patient_history,
                    )
                    _lmod2.getLogger("debug.continue").info("[DEBUG-CONT] action=%s questions=%d is_sufficient=%s phase=%s red_flags=%d",
                               action, len(questions), state.is_sufficient, state.phase, len(state.red_flags_detected))
                except Exception as e:
                    yield _patient_llm_error_event(e, "followup_interview")
                    return

                # Interview already completed (phase=completed, regeneration exhausted)
                if action == "completed" and (session.structured_output or {}).get("knowledge_citations"):
                    report = session.structured_output
                    if session.user_id is not None and report:
                        try:
                            saved_case = await persist_diagnosis_case(
                                db,
                                patient_id=session.user_id,
                                source_session_id=session.id,
                                report=report,
                                fallback_chief_complaint="患者问诊",
                            )
                            completed_case_id = str(saved_case.id)
                        except DiagnosisCasePersistenceError:
                            yield _patient_error_event(
                                "CASE_PERSISTENCE_FAILED",
                                "诊断结果未能保存为病例，本次未标记为已保存，请稍后重试。",
                                "followup_case_persistence",
                            )
                            return
                    elif session.user_id is not None:
                        yield f"event: error\ndata: {json.dumps({'error': '诊断报告尚未保存，暂不能确认病例状态'}, ensure_ascii=False)}\n\n"
                        return
                    yield f"event: complete\ndata: {json.dumps({'status': 'already_diagnosed', 'session_id': session_id, 'case_id': completed_case_id})}\n\n"
                    return

                if action == "completed":
                    # 前一次检索失败或旧报告无来源，允许重试证据链，不能永久卡在空报告。
                    action = "synthesize"

                if searches:
                    yield f"event: thinking\ndata: {json.dumps({'step': 'search', 'message': '🔍 后台搜索中...'})}\n\n"

                if questions:
                    yield f"event: interview_progress\ndata: {json.dumps({'asked_count': len(state.asked_questions)})}\n\n"
                    q_list = [{"question_id": nq.question_id, "question": nq.question, "type": nq.type, "options": nq.options, "hint": nq.hint, "allow_skip": nq.allow_skip, "phase": nq.phase, "colloquial_phase": nq.colloquial_phase, "reason": nq.reason} for nq in questions]
                    yield f"event: question\ndata: {json.dumps({'questions': q_list})}\n\n"
                    yield f"event: complete\ndata: {json.dumps({'status': 'waiting_for_answer', 'session_id': session_id})}\n\n"
                    return

                # Check for red flags
                if state.red_flags_detected:
                    yield f"event: red_flags\ndata: {json.dumps({'red_flags': state.red_flags_detected, 'message': '检测到危险信号，建议立即就医'})}\n\n"

                if not state.is_sufficient and action != "synthesize":
                    import logging as _lmod3
                    _lmod3.getLogger("debug.continue").warning("[DEBUG-CONT] EMPTY CARDS — is_sufficient=False, no questions to show (DEADLOCK)")
                    yield f"event: complete\ndata: {json.dumps({'status': 'waiting_for_answer', 'session_id': session_id})}\n\n"
                    await asyncio.sleep(0.1)
                    return

                # Interview complete — proceed to diagnosis using structured summary
                _msg_start = "🧠 正在整理阶段摘要，未确认的信息会保留..." if not state.is_sufficient else "🧠 正在整理问诊信息..."
                yield f"event: thinking\ndata: {json.dumps({'step': 'diagnosis', 'message': _msg_start})}\n\n"

                # Redis lock to prevent concurrent diagnoses
                try:
                    from app.db.redis_client import get_redis
                    redis_client = get_redis()
                    lock_key = f"diag_lock:{session_id}"
                    locked = await redis_client.set(lock_key, "1", nx=True, ex=60)
                    if not locked:
                        yield f"event: complete\ndata: {json.dumps({'status': 'already_diagnosed', 'session_id': session_id})}\n\n"
                        return
                except Exception as e:
                    import logging
                    logging.getLogger("agents").error("Failed to acquire Redis lock: %s", e)

                try:
                    yield f"event: tool_call\ndata: {json.dumps({'tool': 'search_medical_knowledge', 'params': {'query': '基于问诊摘要的医学搜索'}, 'message': '🔍 正在搜索医学知识库和最新文献...'})}\n\n"

                    result = await diag_agent.run_full_diagnosis_workflow(
                        session_id=session_id,
                        patient_id=str(session.user_id) if session.user_id else None,
                        patient_history=patient_history,
                    )

                    if result.tool_calls_used:
                        for tc in result.tool_calls_used:
                            tool_name = tc.get("tool", "unknown")
                            args = tc.get("arguments", {})
                            _tc_msg = f"🔍 正在执行 {tool_name}..."
                            yield f"event: tool_call\ndata: {json.dumps({'tool': tool_name, 'params': args, 'message': _tc_msg})}\n\n"
                            await asyncio.sleep(0.2)
                            result_data = tc.get("result", {})
                            _tr_msg = f"✅ {tool_name} 执行完成"
                            yield f"event: tool_result\ndata: {json.dumps({'tool': tool_name, 'result': result_data, 'message': _tr_msg})}\n\n"

                    _msg_analyze = "🧠 正在综合分析并生成诊断报告..."
                    yield f"event: thinking\ndata: {json.dumps({'step': 'diagnosis', 'message': _msg_analyze})}\n\n"

                    if result.structured_output:
                        structured_data = result.structured_output.model_dump()
                        if session.user_id is not None:
                            try:
                                saved_case = await persist_diagnosis_case(
                                    db,
                                    patient_id=session.user_id,
                                    source_session_id=session.id,
                                    report=structured_data,
                                    fallback_chief_complaint="患者问诊",
                                )
                                completed_case_id = str(saved_case.id)
                            except DiagnosisCasePersistenceError:
                                yield _patient_error_event(
                                    "CASE_PERSISTENCE_FAILED",
                                    "诊断结果未能保存为病例，本次未标记为已保存，请稍后重试。",
                                    "followup_case_persistence",
                                )
                                return
                        yield f"event: structured\ndata: {json.dumps(structured_data)}\n\n"

                        report_md = _diagnosis_report_to_markdown(structured_data)
                        for chunk in _chunk_text(report_md, chunk_size=80):
                            yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                    else:
                        content = result.content if isinstance(result.content, str) else json.dumps(result.content, ensure_ascii=False)
                        for chunk in _chunk_text(content, chunk_size=80):
                            yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                except Exception as e:
                    yield _patient_llm_error_event(e, "followup_diagnosis")
                    return

                yield f"event: complete\ndata: {json.dumps({'message': '✅ 响应完成', 'session_id': session_id, 'case_id': completed_case_id})}\n\n"

        except asyncio.CancelledError:
            _log_patient_llm_interruption("followup_stream")
            raise
        except Exception as e:
            yield _patient_llm_error_event(e, "followup_stream")

    return await stream_guest_submission(
        db,
        ctx,
        submission_id=idempotency_key,
        endpoint="agents.route.stream.continue",
        request_payload={
            "session_id": session_id,
            "question_id": question_id,
            "answer": _answer,
        },
        event_generator=event_generator,
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Plan C: Post-Diagnosis Chat Endpoint
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    patient_history: str | None = Field(None, max_length=5000)


@router.post("/sessions/{session_id}/chat")
async def chat_session(
    session_id: str,
    req: ChatRequest,
    request: Request,
    ctx: CurrentUserContextLenientNoQuery,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> StreamingResponse:
    _reject_query_auth_token(request)
    _reject_patient_text_in_query(request, "message", "patient_history")
    import uuid as _uuid

    try:
        parent = await db.get(AgentSession, _uuid.UUID(session_id))
    except (ValueError, Exception):
        raise HTTPException(status_code=404, detail="Session not found")

    if not parent:
        raise HTTPException(status_code=404, detail="Session not found")
    await _require_session_access(db, parent, ctx)

    interview_data = (parent.context or {}).get("interview", {})
    actual_phase = interview_data.get("phase", "<missing>")
    if actual_phase != "completed":
        import logging as _chat_log_mod
        _chat_log = _chat_log_mod.getLogger("chat")
        _chat_log.error(
            "[CHAT-400] session=%s expected phase=completed, got=%s, "
            "has_structured=%s, status=%s",
            session_id,
            actual_phase,
            bool(parent.structured_output),
            parent.status.value if parent.status else "?",
        )
        raise HTTPException(status_code=400, detail="Diagnosis not yet completed")

    actual_patient_id = str(ctx.user.id) if ctx.user and ctx.user.id else None

    async def event_generator():
        child: AgentSession | None = None
        try:
            child = AgentSession(
                user_id=parent.user_id,
                guest_session_id=parent.guest_session_id,
                session_type=AgentSessionType.CONVERSATION,
                status=AgentSessionStatus.ACTIVE,
                parent_session_id=parent.id,
                context={"user_message": req.message},
            )
            db.add(child)
            await db.commit()
            await db.refresh(child)

            system_prompt = await _build_chat_context(db, parent, user_id=actual_patient_id)

            import logging as _llm_log_mod
            _llm_log = _llm_log_mod.getLogger("chat.llm")
            _llm_log.info(
                "[CHAT-LLM] session=%s prompt_chars=%d user_msg_chars=%d est_tokens=%d",
                session_id, len(system_prompt), len(req.message),
                (len(system_prompt) + len(req.message)) // 4,
            )

            async with async_session_maker() as chat_db:
                llm = LLMService(provider=None, platform=ctx.platform, db=chat_db)
                response = await llm.chat(
                    messages=[{"role": "user", "content": req.message}],
                    system_prompt=system_prompt,
                    max_tokens=2048,
                )
                full_response = response.content
                for chunk in _chunk_text(full_response, chunk_size=80):
                    yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"

            if not full_response:
                _llm_log.warning(
                    "[CHAT-EMPTY] session=%s prompt_chars=%d user_msg_chars=%d",
                    session_id, len(system_prompt), len(req.message),
                )
                child.status = AgentSessionStatus.FAILED
                await db.commit()
                yield _patient_error_event(
                    "LLM_EMPTY_RESPONSE",
                    "AI 暂未生成有效回复，请保留当前内容后重试；如需解读报告，请携带原始报告咨询医生。",
                    "post_diagnosis_chat",
                )
                return

            _llm_log.info("[CHAT-OK] session=%s response_chars=%d", session_id, len(full_response))

            child.context = {
                **(child.context or {}),
                "assistant_response": full_response,
            }
            child.status = AgentSessionStatus.COMPLETED
            child.completed_at = datetime.now(timezone.utc)
            await db.commit()

            yield f"event: complete\ndata: {json.dumps({'session_id': str(child.id), 'parent_session_id': str(parent.id)})}\n\n"

        except asyncio.CancelledError:
            if child is not None:
                child.status = AgentSessionStatus.FAILED
                await db.commit()
            _log_patient_llm_interruption("post_diagnosis_chat")
            raise
        except Exception as e:
            if child is not None:
                child.status = AgentSessionStatus.FAILED
                await db.commit()
            yield _patient_llm_error_event(e, "post_diagnosis_chat")

    return await stream_guest_submission(
        db,
        ctx,
        submission_id=idempotency_key,
        endpoint="agents.sessions.chat",
        request_payload={"session_id": session_id, "request": req.model_dump(mode="json")},
        event_generator=event_generator,
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
