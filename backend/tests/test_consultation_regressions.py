"""复现患者截图：检索来源丢失、必要缺口提前结束、互补病史误报冲突。"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.interview import InterviewState
from app.services.agents import _patient_information_gap
from app.services.knowledge_citations import attach_knowledge_citations, build_knowledge_citations
from app.services.knowledge_citations import apply_report_citation_bindings, restore_report_sources
from app.services.llm import LLMResponse
from app.services.orchestrator import InterviewOrchestrator


def response(data):
    return LLMResponse(content=json.dumps(data, ensure_ascii=False), model="synthetic", provider="synthetic",
                       usage_prompt_tokens=0, usage_completion_tokens=0, finish_reason="stop")


def stool_question():
    return {"question_id": "adv_stool_pattern", "information_key": "adv_stool_pattern",
            "priority": "essential", "question": "您这次大便的性状是什么样的？", "type": "choice",
            "options": ["稀水样", "糊状", "带血或黏液", "不清楚"],
            "reason": "明确本次主诉的症状特点", "phase": "adv_stool_pattern"}


def test_正文未引用时仍保留可查看的实际检索来源():
    sources = build_knowledge_citations([
        {"source_type": "internal", "title": "合成内部资料", "document_id": "doc", "chunk_id": "chunk",
         "excerpt": "合成原文。"},
        {"source_type": "external", "title": "合成外部资料", "url": "https://example.org/reference",
         "excerpt": "合成外部原文。"},
    ])
    report = attach_knowledge_citations({"primary_diagnosis": "合成总结"}, sources)
    assert ["S1", "S2"] == [item["citation_id"] for item in report["knowledge_citations"]]
    assert "retrieved_not_cited" == report["knowledge_retrieval_status"]
    assert [] == report["knowledge_evidence"]


@pytest.mark.asyncio
async def test_模型有未问关键缺口却返回摘要时必须补问():
    state = InterviewState(chief_complaint="合成腹泻主诉", collected_info={"hpi_onset": "昨天"})
    llm = SimpleNamespace(chat=AsyncMock(side_effect=[
        response({"action": "synthesize", "basic_module": [], "needs_more_info": ["adv_stool_pattern"]}),
        response({"action": "ask", "basic_module": [stool_question()], "needs_more_info": ["adv_stool_pattern"]}),
    ]))
    cards, state, _, action, _ = await InterviewOrchestrator(llm).decide_next(state)
    assert "ask" == action
    assert len(cards) == 1
    assert "大便" in cards[0].question
    assert "interviewing" == state.phase


@pytest.mark.asyncio
async def test_达到体验预算也不能丢掉未问的必要题():
    state = InterviewState(chief_complaint="合成腹泻主诉", collected_info={"hpi_onset": "昨天"}, interview_rounds=6)
    llm = SimpleNamespace(chat=AsyncMock(return_value=response({"action": "ask", "basic_module": [stool_question()]})))
    cards, state, _, action, _ = await InterviewOrchestrator(llm).decide_next(state)
    assert "ask" == action
    assert len(cards) == 1
    assert not state.is_sufficient


def test_不同既往疾病是互补信息而不是前后矛盾():
    state = InterviewState()
    state.remember_information("pmh_chronic", "焦虑障碍轻度", "patient_history")
    state.remember_information("pmh_chronic", "甲亢，程度未知", "patient_history")
    assert "needs_review" != state.information_status("pmh_chronic")
    state.refresh_information_gaps()
    assert not any("不一致" in gap for gap in state.information_gaps)


@pytest.mark.parametrize("gap", ["adv_stool_pattern", "adv_epidemic", "adv_unfamiliar_key", "adv_stool_pattern: 尚未确认"])
def test_患者缺口文案不能暴露内部标识(gap):
    assert "adv_" not in _patient_information_gap(gap)


def test_补引用只接受实际来源完整句且不改正文或患者自述():
    sources = build_knowledge_citations([{"source_type": "internal", "title": "合成原文", "document_id": "doc",
                                          "chunk_id": "chunk", "excerpt": "建议记录变化。没有发热。"}])
    report = {"recommended_actions": ["建议记录变化。"], "key_findings": ["患者没有发热"]}
    patched = apply_report_citation_bindings(report, sources, [
        {"claim_path": "recommended_actions.0", "citation_id": "S1", "quote": "建议记录变化。"},
        {"claim_path": "key_findings.0", "citation_id": "S1", "quote": "没有发热。"},
        {"claim_path": "recommended_actions.0", "citation_id": "S999", "quote": "建议记录变化。"},
        {"claim_path": "recommended_actions.0", "citation_id": [], "quote": "建议记录变化。"},
        {"claim_path": "recommended_actions.0", "citation_id": "S1", "quote": "发热"},
    ])
    assert ["建议记录变化。[S1]"] == patched["recommended_actions"]
    assert report["key_findings"] == patched["key_findings"]
    assert ["建议记录变化。"] == report["recommended_actions"]
    assert 1 == len(patched["knowledge_evidence"])


def test_历史来源只读恢复保持原编号且没有检索记录不能编造():
    report = {"primary_diagnosis": "合成报告[S4]", "knowledge_citations": [], "knowledge_retrieval_count": 2}
    calls = [{"tool": "search_medical_knowledge", "result": {"sources": [
        {"citation_id": "S4", "source_type": "internal", "title": "合成来源", "document_id": "doc",
         "chunk_id": "chunk", "excerpt": "合成原文。"},
        {"citation_id": "S8", "source_type": "external", "title": "危险链接", "url": "javascript:alert(1)", "excerpt": "原文"},
    ]}}]
    restored = restore_report_sources(report, calls)
    assert ["S4"] == [source["citation_id"] for source in restored["knowledge_citations"]]
    assert restored["knowledge_citations"][0]["used_in_report"] is True
    assert [] == report["knowledge_citations"]
    assert report == restore_report_sources(report, [])


@pytest.mark.asyncio
async def test_实际诊断入口漏写编号后补齐引用并保存可查看来源(monkeypatch):
    import uuid
    from contextlib import asynccontextmanager
    from app.services import agents as module
    @asynccontextmanager
    async def db():
        yield SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
    llm = SimpleNamespace(
        chat_with_tools=AsyncMock(return_value=response({"primary_diagnosis": "合成报告", "confidence": "low",
                                                         "recommended_actions": ["建议记录变化。"]})),
        chat=AsyncMock(return_value=response({"bindings": [{"claim_path": "recommended_actions.0",
                                                            "citation_id": "S1", "quote": "建议记录变化。"}]})))
    monkeypatch.setattr(module, "async_session_maker", db)
    monkeypatch.setattr(module, "LLMService", lambda **kwargs: llm)
    monkeypatch.setattr(module.GLOBAL_REGISTRY, "list_schemas", lambda: [])
    monkeypatch.setattr(module.GLOBAL_REGISTRY, "execute", AsyncMock(return_value={"success": True, "result": {"sources": [
        {"source_type": "internal", "title": "记录变化资料", "document_id": "doc", "chunk_id": "chunk",
         "excerpt": "建议记录变化。"}]}}))
    agent = module.DiagnosisAgent()
    agent._generate_search_query = AsyncMock(return_value="记录变化")
    agent._update_session = AsyncMock()
    result = await agent.run_full_diagnosis_workflow(str(uuid.uuid4()))
    assert ["建议记录变化。[S1]"] == result.structured_output.recommended_actions
    assert result.structured_output.knowledge_citations[0].used_in_report is True
    assert "excerpt_matched" == result.structured_output.knowledge_evidence[0].status
    assert agent._update_session.await_args.kwargs["structured"]["knowledge_citations"][0]["chunk_id"] == "chunk"


@pytest.mark.asyncio
async def test_病例恢复接口只为本人恢复历史来源且不写库():
    import uuid
    from app.api.v1.patient import get_case_recovery
    from app.models.user import UserRole
    owner, case_id, session_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    case = SimpleNamespace(id=case_id, source_session_id=session_id, title="合成病例", chief_complaint="合成主诉",
                           status=SimpleNamespace(value="open"), created_at=None)
    source_session = SimpleNamespace(user_id=owner, context={}, structured_output={"primary_diagnosis": "合成报告",
        "knowledge_citations": [], "knowledge_retrieval_count": 1}, tool_calls=[{"tool": "search_medical_knowledge", "result": {"sources": [
            {"citation_id": "S3", "source_type": "internal", "title": "合成来源", "document_id": "doc", "chunk_id": "chunk", "excerpt": "合成原文。"}]}}])
    db = SimpleNamespace(execute=AsyncMock(side_effect=[SimpleNamespace(scalar_one_or_none=lambda: case),
                                                       SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))]),
                         get=AsyncMock(return_value=source_session), commit=AsyncMock())
    result = await get_case_recovery(case_id, SimpleNamespace(id=owner, role=UserRole.PATIENT), db)
    assert ["S3"] == [source["citation_id"] for source in result["report"]["knowledge_citations"]]
    assert [] == source_session.structured_output["knowledge_citations"]
    db.commit.assert_not_awaited()
    from fastapi import HTTPException
    foreign = SimpleNamespace(**{**source_session.__dict__, "user_id": uuid.uuid4()})
    foreign_db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: case)),
                                 get=AsyncMock(return_value=foreign), commit=AsyncMock())
    with pytest.raises(HTTPException) as caught:
        await get_case_recovery(case_id, SimpleNamespace(id=owner, role=UserRole.PATIENT), foreign_db)
    assert 404 == caught.value.status_code
    assert 1 == foreign_db.execute.await_count
    foreign_db.commit.assert_not_awaited()


def test_阶段缺口的来源编号不能冒充正文引文():
    sources = build_knowledge_citations([{"source_type": "internal", "title": "合成来源", "document_id": "doc",
                                          "chunk_id": "chunk", "excerpt": "合成原文。"}])
    report = attach_knowledge_citations({"primary_diagnosis": "合成总结", "interview_information_gaps": ["未知[S1]"]}, sources)
    assert report["knowledge_citations"][0]["used_in_report"] is False
