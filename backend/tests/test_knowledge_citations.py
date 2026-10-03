import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import agents as agents_module
from app.services.agents import AgentResult, DiagnosisAgent, DiagnosisReport
from app.services.knowledge_citations import (
    attach_knowledge_citations,
    build_knowledge_citations,
    format_knowledge_context,
)
from app.services.external_search import ExternalSearchAgent, SearchResult
from app.tools.medical import SearchMedicalKnowledgeTool
from app.api.v1.agents import _diagnosis_report_to_markdown
from app.api.v1.admin import DEFAULT_SETTINGS


def test_external_trusted_domain_requires_hostname_boundary():
    agent = ExternalSearchAgent(base_url="http://searxng:8080")
    results = agent._filter_trusted([
        {"title": "lookalike", "url": "https://fakewho.int/example", "engine": "bing", "content": "sample"},
        {"title": "subdomain", "url": "https://www.who.int/example", "engine": "bing", "content": "sample"},
    ])

    trusted_by_title = {item.title: item.is_trusted for item in results}
    assert trusted_by_title == {"lookalike": False, "subdomain": True}


def test_admin_exposes_report_source_limit_with_default_ten():
    setting = next(item for item in DEFAULT_SETTINGS if item.key == "diagnosis.report_source_limit")
    assert setting.value == "10"
    assert setting.category == "diagnosis"
    assert setting.value_type == "select"
    assert setting.options.split(",") == [str(value) for value in range(1, 11)]


def test_stream_markdown_renders_inline_markers_and_verifiable_citations():
    markdown = _diagnosis_report_to_markdown({
        "primary_diagnosis": "急性感染性腹泻 [S1]",
        "knowledge_citations": [
            {
                "citation_id": "S1",
                "source_type": "internal",
                "title": "儿童急性感染性腹泻病诊疗规范",
                "document_id": "doc-1",
                "chunk_id": "chunk-3",
                "chunk_index": 2,
                "excerpt": "建议使用口服补液盐。",
            },
            {
                "citation_id": "S2",
                "source_type": "external",
                "title": "WHO guidance",
                "url": "https://www.who.int/example",
                "excerpt": "External source excerpt.",
            },
            {
                "citation_id": "S3",
                "source_type": "external",
                "title": "Unsafe link",
                "url": "javascript:alert(1)",
                "excerpt": "Untrusted link is not rendered.",
            },
        ],
    })

    assert "急性感染性腹泻 [S1]" in markdown
    assert "内部知识库｜儿童急性感染性腹泻病诊疗规范" in markdown
    assert "文档ID：doc-1；片段序号：3；片段ID：chunk-3" in markdown
    assert "<https://www.who.int/example>" in markdown
    assert "javascript:" not in markdown
    assert "原文摘录" not in markdown
    assert "External source excerpt." in markdown


def test_citations_keep_traceable_internal_and_external_provenance():
    citations = build_knowledge_citations([
        {
            "source_type": "internal",
            "title": "儿童发热指南",
            "document_id": "doc-1",
            "chunk_id": "chunk-7",
            "chunk_index": 6,
            "document_type": "platform_guideline",
            "excerpt": "原文：发热儿童应观察精神状态。",
            "relevance": 0.91,
        },
        {
            "source_type": "external",
            "title": "WHO guidance",
            "url": "https://www.who.int/example",
            "source_engine": "searxng",
            "snippet": "External source excerpt.",
            "trust_score": 81,
            "is_trusted": True,
        },
        {"source_type": "external", "title": "unsafe", "url": "javascript:alert(1)"},
        {"title": "model invented this source"},
    ])

    assert [item.citation_id for item in citations] == ["S1", "S2"]
    assert citations[0].source_type == "internal"
    assert (citations[0].document_id, citations[0].chunk_id, citations[0].chunk_index) == (
        "doc-1", "chunk-7", 6,
    )
    assert citations[1].source_type == "external"
    assert citations[1].url == "https://www.who.int/example"
    assert citations[1].source_engine == "searxng"


def test_report_uses_only_retrieved_citations_and_removes_unknown_markers():
    citations = build_knowledge_citations([
        {
            "source_type": "internal", "title": "儿童发热指南",
            "document_id": "doc-1", "chunk_id": "chunk-1", "excerpt": "原文摘录",
        },
    ])

    report = attach_knowledge_citations(
        {
            "primary_diagnosis": "需结合症状评估[S1][S9]",
            "knowledge_sources": ["模型编造来源"],
        },
        citations,
    )

    assert report["primary_diagnosis"] == "需结合症状评估[S1]"
    assert report["knowledge_sources"] == ["儿童发热指南"]
    assert report["knowledge_citations"] == [citations[0].model_copy(update={"used_in_report": True}).model_dump()]
    assert report["knowledge_retrieval_status"] == "used"
    assert report["knowledge_retrieval_count"] == 1


def test_report_keeps_actual_reference_materials_but_marks_only_body_citations_used():
    citations = build_knowledge_citations([
        {
            "source_type": "internal", "title": "儿童发热指南",
            "document_id": "doc-1", "chunk_id": "chunk-1", "excerpt": "发热原文",
        },
        {
            "source_type": "external", "title": "WHO guidance",
            "url": "https://www.who.int/example", "snippet": "External excerpt",
        },
    ])

    report = attach_knowledge_citations(
        {"primary_diagnosis": "需要结合情况评估[S1]", "knowledge_sources": ["伪来源[S2]"]},
        citations,
        retrieval_status="retrieved_not_cited",
    )

    assert [item["citation_id"] for item in report["knowledge_citations"]] == ["S1", "S2"]
    assert [True, False] == [item["used_in_report"] for item in report["knowledge_citations"]]
    assert report["knowledge_sources"] == ["儿童发热指南", "WHO guidance"]
    assert report["knowledge_retrieval_status"] == "used"
    assert report["knowledge_retrieval_count"] == 2


def test_citation_context_includes_only_actual_reference_ids_and_excerpts():
    citations = build_knowledge_citations([
        {
            "source_type": "internal", "title": "儿童发热指南",
            "document_id": "doc-1", "chunk_id": "chunk-1", "chunk_index": 0,
            "excerpt": "原文摘录",
        },
        {
            "source_type": "external", "title": "WHO guidance",
            "url": "https://www.who.int/example", "snippet": "External excerpt",
        },
    ])

    context = format_knowledge_context(citations)

    assert "[S1]" in context
    assert "doc-1" in context and "chunk-1" in context
    assert "[S2]" in context
    assert "https://www.who.int/example" in context
    assert "原文摘录" in context and "External excerpt" in context


@pytest.mark.parametrize("configured_limit", [None, 3, 10])
@pytest.mark.asyncio
async def test_real_diagnosis_workflow_binds_retriever_sources_to_report(monkeypatch, configured_limit):
    class EmptySession:
        async def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    @asynccontextmanager
    async def fake_session_maker():
        yield EmptySession()

    source = {
        "source_type": "internal",
        "title": "儿童急性感染性腹泻诊疗规范",
        "document_id": "doc-1",
        "chunk_id": "chunk-2",
        "chunk_index": 1,
        "document_type": "platform_guideline",
        "excerpt": "原文摘录：建议关注脱水程度。",
    }
    monkeypatch.setattr(agents_module, "async_session_maker", fake_session_maker)
    if configured_limit is not None:
        monkeypatch.setattr(
            agents_module.DynamicConfigService,
            "diagnosis_report_source_limit",
            AsyncMock(return_value=configured_limit),
        )
    extra_sources = [
        {**source, "chunk_id": f"chunk-{index}", "chunk_index": index}
        for index in (range(3, 12) if configured_limit in (None, 10) else (3, 4, 5))
    ]
    external_source = {
        "source_type": "external",
        "title": "WHO 口服补液指南",
        "excerpt": "口服补液相关原文摘录",
        "url": "https://www.who.int/publications/example",
        "source_engine": "searxng",
        "is_trusted": True,
    }
    monkeypatch.setattr(
        agents_module.GLOBAL_REGISTRY,
        "execute",
        AsyncMock(return_value={
            "success": True,
            "result": {
                "sources": [source, *extra_sources, external_source],
                "retrieved_chunks": len(extra_sources) + 2,
                "internal_sources": len(extra_sources) + 1,
                "external_sources": 1,
            },
        }),
    )

    agent = DiagnosisAgent()
    agent._generate_search_query = AsyncMock(return_value="儿童腹泻脱水")
    agent._update_session = AsyncMock()
    agent.analyze = AsyncMock(return_value=AgentResult(
        agent_type="diagnosis",
        content={},
        structured_output=DiagnosisReport(
            primary_diagnosis="需结合症状评估[S1][S99]",
            key_findings=["原文摘录：建议关注脱水程度。[S1]", "建议关注脱水程度。[S1]"],
            confidence="low",
            knowledge_sources=["模型自报来源"],
        ),
        confidence="low",
        tool_calls_used=[],
        session_id=str(uuid.uuid4()),
    ))
    session_id = str(uuid.uuid4())

    result = await agent.run_full_diagnosis_workflow(session_id=session_id)
    expected_limit = configured_limit or 10

    assert result.structured_output.primary_diagnosis == "需结合症状评估[S1]"
    assert result.structured_output.knowledge_sources == ["儿童急性感染性腹泻诊疗规范"]
    assert result.structured_output.knowledge_citations[0].chunk_id == "chunk-2"
    assert result.structured_output.knowledge_retrieval_count == expected_limit
    sent_context = agent.analyze.await_args.kwargs["knowledge_context"]
    assert "[S1]" in sent_context and "chunk-2" in sent_context
    assert f"[S{expected_limit}]" in sent_context
    # 不再为外部来源保留固定席位；无主题词匹配的来源不能仅凭可信域名入选。
    assert external_source["url"] not in sent_context
    assert f"[S{expected_limit + 1}]" not in sent_context
    assert result.tool_calls_used[0]["tool"] == "search_medical_knowledge"
    assert result.tool_calls_used[0]["arguments"]["top_k"] == expected_limit
    assert result.tool_calls_used[0]["result"]["sources"][expected_limit - 1]["source_type"] == "internal"
    assert agent._update_session.await_args.kwargs["structured"]["knowledge_citations"][0]["citation_id"] == "S1"
    rows = agent._update_session.await_args.kwargs["structured"]["knowledge_evidence"]
    assert ["needs_review", "excerpt_matched", "needs_review"] == [row["status"] for row in rows]
    assert result.content["knowledge_evidence"] == rows


@pytest.mark.asyncio
async def test_search_tool_keeps_internal_chunk_and_external_url_metadata(monkeypatch):
    from app.services.external_search import ExternalSearchAgent
    import app.services.rag

    class FakeRag:
        def __init__(self, _db):
            pass

        async def search(self, **_kwargs):
            return [{
                    "document_title": "儿童发热指南", "rank": 0.1,
                    "document_id": "doc-1", "chunk_id": "chunk-1", "chunk_index": 0,
                    "document_type": "platform_guideline", "content": "原文摘录",
                }]

    class FakeExternal:
        async def search_guidelines(self, _query, lang):
            assert lang == "zh-CN"
            return [SearchResult(
                title="WHO guidance", url="https://www.who.int/example",
                snippet="External excerpt", source_engine="searxng",
                trust_score=81, is_trusted=True,
            )]

        async def _searxng_search(self, _query, lang):
            assert lang == "zh-CN"
            return []

        def _filter_trusted(self, _results):
            return []

    @asynccontextmanager
    async def fake_session_maker():
        yield object()

    monkeypatch.setattr(app.services.rag, "RAGService", FakeRag)
    monkeypatch.setattr(ExternalSearchAgent, "from_config", AsyncMock(return_value=FakeExternal()))
    import app.db.session
    monkeypatch.setattr(app.db.session, "async_session_maker", fake_session_maker)

    result = await SearchMedicalKnowledgeTool().execute(query="儿童发热指南")

    assert result["sources"][0]["source_type"] == "internal"
    assert result["sources"][0]["chunk_id"] == "chunk-1"
    assert result["sources"][1]["source_type"] == "external"
    assert result["sources"][1]["url"] == "https://www.who.int/example"
    assert result["sources"][1]["excerpt"] == "External excerpt"


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted_only", [True, False])
async def test_patient_search_tool_respects_external_trusted_only_setting(monkeypatch, trusted_only):
    import app.db.session
    import app.services.rag
    from app.services.config import DynamicConfigService
    from app.services.external_search import ExternalSearchAgent

    sources = [
        SearchResult(
            title="WHO guidance", url="https://www.who.int/example",
            snippet="Trusted excerpt", source_engine="searxng",
            trust_score=81, is_trusted=True,
        ),
        SearchResult(
            title="Baidu Baike", url="https://baike.baidu.com/item/diarrhea",
            snippet="Untrusted excerpt", source_engine="searxng",
            trust_score=6, is_trusted=False,
        ),
    ]

    class FakeRag:
        def __init__(self, _db):
            pass

        async def search(self, **_kwargs):
            return []

    class FakeExternal:
        async def search_guidelines(self, _query, lang):
            assert lang == "zh-CN"
            return sources

        async def _searxng_search(self, _query, lang):
            assert lang == "zh-CN"
            return sources

        def _filter_trusted(self, _results):
            return sources

    @asynccontextmanager
    async def fake_session_maker():
        yield object()

    monkeypatch.setattr(app.services.rag, "RAGService", FakeRag)
    monkeypatch.setattr(ExternalSearchAgent, "from_config", AsyncMock(return_value=FakeExternal()))
    monkeypatch.setattr(
        DynamicConfigService,
        "external_search_trusted_only",
        AsyncMock(return_value=trusted_only),
    )
    monkeypatch.setattr(app.db.session, "async_session_maker", fake_session_maker)

    result = await SearchMedicalKnowledgeTool().execute(query="腹泻处理")

    external_urls = {
        source["url"] for source in result["sources"]
        if source["source_type"] == "external"
    }
    expected_urls = {sources[0].url} if trusted_only else {source.url for source in sources}
    assert external_urls == expected_urls
