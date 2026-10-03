"""通过真实报告入口验证跨来源选择，不把可信度当作相关性。"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import agents as agents_module
from app.services.agents import AgentResult, DiagnosisAgent, DiagnosisReport


@pytest.mark.asyncio
async def test_可信但无关的外部来源不能挤走相关内部来源(monkeypatch):
    @asynccontextmanager
    async def fake_db():
        yield SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))

    monkeypatch.setattr(agents_module, "async_session_maker", fake_db)
    monkeypatch.setattr(agents_module.DynamicConfigService, "diagnosis_report_source_limit", AsyncMock(return_value=1))
    monkeypatch.setattr(agents_module.GLOBAL_REGISTRY, "execute", AsyncMock(return_value={
        "success": True, "result": {"sources": [
            {"source_type": "internal", "title": "发热资料", "excerpt": "发热主题的合成原文。",
             "document_id": "doc-fever", "chunk_id": "chunk-fever", "relevance": 0.1},
            {"source_type": "external", "title": "牙齿资料", "excerpt": "牙齿主题的合成原文。",
             "url": "https://www.who.int/synthetic-dental", "is_trusted": True,
             "trust_score": 91, "relevance": 0.91},
        ]},
    }))
    agent = DiagnosisAgent()
    agent._generate_search_query = AsyncMock(return_value="发热")
    agent._update_session = AsyncMock()
    agent.analyze = AsyncMock(return_value=AgentResult(
        agent_type="diagnosis", content={}, confidence="low", tool_calls_used=[],
        structured_output=DiagnosisReport(primary_diagnosis="合成摘要[S1]", confidence="low"),
        session_id=str(uuid.uuid4()),
    ))
    result = await agent.run_full_diagnosis_workflow(session_id=str(uuid.uuid4()))
    assert "internal" == result.structured_output.knowledge_citations[0].source_type
    assert "chunk-fever" == result.structured_output.knowledge_citations[0].chunk_id


@pytest.mark.asyncio
async def test_阶段摘要保存缺口及低置信度且传递到结果对象(monkeypatch):
    from app.models.interview import InterviewState
    state = InterviewState(chief_complaint="合成主诉", stop_reason="budget_reached", is_sufficient=False,
                           information_gaps=["med_current：患者尚未确认"], phase="completed")
    session = SimpleNamespace(context={"interview": state.to_dict()})

    @asynccontextmanager
    async def fake_db():
        yield SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: session)))

    monkeypatch.setattr(agents_module, "async_session_maker", fake_db)
    monkeypatch.setattr(agents_module.GLOBAL_REGISTRY, "execute", AsyncMock(return_value={"success": True, "result": {"sources": [
        {"source_type": "internal", "title": "合成参考资料", "document_id": "doc", "chunk_id": "chunk", "excerpt": "合成阶段资料。"}]}}))
    agent = DiagnosisAgent()
    agent._generate_search_query = AsyncMock(return_value="合成")
    agent._update_session = AsyncMock()
    agent.analyze = AsyncMock(return_value=AgentResult(agent_type="diagnosis", content={}, confidence="high", tool_calls_used=[],
                                                      structured_output=DiagnosisReport(primary_diagnosis="合成[S1]", confidence="high")))
    result = await agent.run_full_diagnosis_workflow(str(uuid.uuid4()))
    assert "low" == result.confidence == result.structured_output.confidence
    assert result.structured_output.interview_is_sufficient is False
    assert "budget_reached" == result.structured_output.interview_stop_reason
    assert ["当前用药：患者尚未确认"] == result.structured_output.interview_information_gaps
    assert agent._update_session.await_args.kwargs["structured"]["interview_is_sufficient"] is False
