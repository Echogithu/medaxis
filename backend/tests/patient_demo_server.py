"""本地端到端演示服务器：仅替换 LLM 生成边界，认证和业务 API 使用真实实现。"""

from __future__ import annotations

import uuid
import os
from types import SimpleNamespace

from app.models.interview import InterviewState
from app.services.agents import AgentResult, DiagnosisAgent, DiagnosisReport, MasterAgent


async def _classify_demo_intent(
    self,
    user_input: str,
    patient_history: str | None = None,
    session_context: dict | None = None,
):
    return {"intent": "diagnosis", "confidence": 1.0, "reason": "synthetic demo substitute"}


async def _generate_demo_question(
    self,
    session_id: str,
    collected_info=None,
    chief_complaint: str = "",
    patient_history: str | None = None,
):
    state = InterviewState(chief_complaint=chief_complaint)
    state.current_question_id = "demo_duration"
    state.pending_question_ids = ["demo_duration"]
    await self._update_interview_state(session_id, state)
    question = SimpleNamespace(
        question_id="demo_duration",
        question="这次不适大约持续了多久？（合成演示问题）",
        type="choice",
        options=["今天开始", "超过一天"],
        hint="请选择一项演示答案",
        allow_skip=False,
        phase="hpi_timing",
        colloquial_phase="症状情况",
    )
    return [question], state, [], "continue", "synthetic demo substitute"


async def _accept_demo_answer(
    self,
    session_id: str,
    question_id: str,
    answer: str,
    patient_history: str | None = None,
):
    from app.db.session import async_session_maker
    from app.models.agent import AgentSession

    async with async_session_maker() as db:
        session = await db.get(AgentSession, uuid.UUID(session_id))
        state = InterviewState.from_dict((session.context or {}).get("interview", {}))
    state.raw_answers[question_id] = answer
    state.collected_info[question_id] = answer
    state.asked_questions.append(question_id)
    state.pending_question_ids = []
    state.is_sufficient = True
    state.phase = "completed"
    await self._update_interview_state(session_id, state)
    return [], state, [], "diagnosis", "synthetic demo substitute"


async def _generate_demo_report(
    self,
    session_id: str,
    patient_id: str | None = None,
    patient_history: str | None = None,
):
    report = DiagnosisReport(
        primary_diagnosis="合成演示报告（不是医学判断）",
        confidence="low",
        severity="unknown",
        key_findings=["本条内容由确定性演示替身生成，不代表真实患者病情。"],
        red_flags=[],
        knowledge_sources=[],
        disclaimer="演示样例；未经临床审核，不构成诊断、分诊或治疗建议。",
    )
    await self._update_session(
        session_id=session_id,
        messages=[],
        tool_calls=[],
        structured=report.model_dump(),
    )
    return AgentResult(
        agent_type="diagnosis",
        content=report.model_dump(),
        structured_output=report,
        tool_calls_used=[],
        session_id=session_id,
    )


MasterAgent.classify_intent = _classify_demo_intent
DiagnosisAgent.interview = _generate_demo_question
DiagnosisAgent.interview_answer = _accept_demo_answer
DiagnosisAgent.run_full_diagnosis_workflow = _generate_demo_report


class _LocalDemoLock:
    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        return True

    async def exists(self, key: str):
        return False


from app.db import redis_client as _redis_client

_redis_client.get_redis = lambda: _LocalDemoLock()


if __name__ == "__main__":
    from urllib.parse import urlparse

    from app.core.config import get_settings

    settings = get_settings()
    database = urlparse(str(settings.database_url))
    if (
        database.hostname not in {"127.0.0.1", "localhost"}
        or not (database.path or "").lstrip("/").startswith("medaxis_demo_e2e_")
    ):
        raise SystemExit("Refusing to start: use a loopback PostgreSQL database named medaxis_demo_e2e_*")

    import uvicorn
    from app.main import app

    print("SYNTHETIC DEMO MODE: LLM generation is deterministic; auth, persistence, and APIs are real.")
    port = int(os.getenv("DEMO_API_PORT", "8012"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
