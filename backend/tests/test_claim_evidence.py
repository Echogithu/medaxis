"""引用编号可追溯不等于整条陈述已有原文支持。"""
from app.services.knowledge_citations import attach_knowledge_citations, build_knowledge_citations
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def citations(excerpt="目前没有发热。"):
    return build_knowledge_citations([{"source_type": "internal", "title": "合成原文",
                                      "document_id": "synthetic", "chunk_id": "s1", "excerpt": excerpt}])


def test_actual_binding_matches_whole_original_and_withholds_removed_negation():
    result = attach_knowledge_citations({"key_findings": ["目前没有发热。[S1]", "发热[S1]"],
        "knowledge_evidence": [{"claim_path": "key_findings.1", "citation_id": "S1",
                                 "quote": "发热", "status": "excerpt_matched", "start": 0, "end": 6}]}, citations())
    rows = result["knowledge_evidence"]
    assert ["excerpt_matched", "needs_review"] == [r["status"] for r in rows]
    assert 0 == rows[0]["start"] and 7 == rows[0]["end"]
    assert "目前没有发热。" == rows[0]["quote"]
    assert rows[1]["start"] is None and rows[1]["end"] is None
    assert "发热[S1]" == result["key_findings"][1]


def test_condition_partial_paraphrase_and_duplicate_quote_cannot_pass():
    cases = [("如果出现脱水，需要就医。", "需要就医。", "需要就医。"),
             ("目前没有发热。", "目前无发热。", "目前没有发热。"),
             ("目前没有发热。目前没有发热。", "目前没有发热。", "目前没有发热。")]
    for excerpt, claim, quote in cases:
        report = attach_knowledge_citations({"key_findings": [claim + "[S1]"],
            "knowledge_evidence": [{"claim_path": "key_findings.0", "citation_id": "S1", "quote": quote}]}, citations(excerpt))
        assert "needs_review" == report["knowledge_evidence"][0]["status"]
        assert report["knowledge_evidence"][0]["start"] is None


def test_evidence_metadata_cannot_make_unused_sources_look_cited():
    result = attach_knowledge_citations({"key_findings": ["待核对"], "knowledge_evidence": [
        {"claim_path": "key_findings.0", "citation_id": "S1", "quote": "目前没有发热。[S1]"}]}, citations())
    assert [] == result["knowledge_evidence"]
    assert result["knowledge_citations"][0]["used_in_report"] is False
    assert "retrieved_not_cited" == result["knowledge_retrieval_status"]


def test_failed_retrieval_has_no_checked_evidence_or_fabricated_marker():
    result = attach_knowledge_citations({"key_findings": ["无发热[S9]"], "knowledge_evidence": [
        {"claim_path": "key_findings.0", "citation_id": "S9", "quote": "无发热", "status": "excerpt_matched"}]}, [], "failed")
    assert "failed" == result["knowledge_retrieval_status"]
    assert [] == result["knowledge_evidence"] == result["knowledge_citations"]
    assert ["无发热"] == result["key_findings"]


@pytest.mark.asyncio
async def test_direct_analyze_clears_model_claimed_sources_and_checked_status(monkeypatch):
    from app.services import agents as module
    @asynccontextmanager
    async def session():
        yield object()
    fake = {"primary_diagnosis": "合成结论[S1]", "confidence": "low",
            "knowledge_sources": ["模型编造来源"], "knowledge_citations": [citations()[0].model_dump()],
            "knowledge_retrieval_status": "used", "knowledge_retrieval_count": 1,
            "knowledge_evidence": [{"claim_path": "primary_diagnosis", "citation_id": "S1",
                                    "quote": "合成结论", "status": "excerpt_matched", "start": 0, "end": 4}]}
    llm = SimpleNamespace(chat_with_tools=AsyncMock(return_value=SimpleNamespace(
        content=json.dumps(fake, ensure_ascii=False), tool_calls=None)))
    monkeypatch.setattr(module, "async_session_maker", session)
    monkeypatch.setattr(module, "LLMService", lambda **kwargs: llm)
    monkeypatch.setattr(module.GLOBAL_REGISTRY, "list_schemas", lambda: [])
    agent = module.DiagnosisAgent()
    agent._update_session = AsyncMock()
    result = await agent.analyze("合成主诉", session_id="synthetic", knowledge_context="预检来源由外层工作流挂接")
    report = result.structured_output
    assert [] == report.knowledge_citations == report.knowledge_sources
    assert "no_sources" == report.knowledge_retrieval_status and 0 == report.knowledge_retrieval_count
    assert "needs_review" == report.knowledge_evidence[0].status
    assert report.knowledge_evidence[0].start is None and report.knowledge_evidence[0].end is None
    assert "合成结论[S1]" == report.primary_diagnosis
    assert "needs_review" == agent._update_session.await_args.kwargs["structured"]["knowledge_evidence"][0]["status"]


def test_markdown_damaged_evidence_fails_closed_and_legacy_has_no_checked_label():
    from app.api.v1.agents import _diagnosis_report_to_markdown
    report = attach_knowledge_citations({"key_findings": ["目前没有发热。[S1]"]}, citations())
    assert "原文一致（适用性待专业核对）" in _diagnosis_report_to_markdown(report)
    report["knowledge_evidence"][0]["start"] = 1
    assert "原文一致（适用性待专业核对）" not in _diagnosis_report_to_markdown(report)
    assert "待核对：" in _diagnosis_report_to_markdown(report)
    report.pop("knowledge_evidence")
    assert "尚无逐条原文核对记录" in _diagnosis_report_to_markdown(report)
