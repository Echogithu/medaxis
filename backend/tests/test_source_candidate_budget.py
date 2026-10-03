"""候选池额度与最终来源上限独立；检索阶段不再生成弃用摘要。"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.config import DynamicConfigService
from app.services.external_search import ExternalSearchAgent
from app.services.rag import RAGService
from app.services.reranker import RerankerService
from app.tools.medical import SearchMedicalKnowledgeTool


@pytest.mark.asyncio
@pytest.mark.parametrize("external_enabled", [True, False])
async def test_候选额度独立于最终条数且关闭外搜不请求外网(monkeypatch, external_enabled):
    @asynccontextmanager
    async def db():
        yield object()

    import app.db.session
    monkeypatch.setattr(app.db.session, "async_session_maker", db)
    monkeypatch.setattr(DynamicConfigService, "knowledge_source_policy", AsyncMock(return_value={
        "internal_candidates": 2, "external_candidates": 3, "min_relevance": .25}))
    monkeypatch.setattr(DynamicConfigService, "external_search_max_results", AsyncMock(return_value=20))
    monkeypatch.setattr(DynamicConfigService, "external_search_enabled", AsyncMock(return_value=external_enabled))
    monkeypatch.setattr(DynamicConfigService, "external_search_trusted_only", AsyncMock(return_value=True))
    chunks = [{"document_title": "合成内部", "document_type": "platform_guideline", "document_id": "doc",
               "chunk_id": str(i), "chunk_index": i, "content": "发热", "rank": .99} for i in range(2)]
    search = AsyncMock(return_value=chunks)
    generate = AsyncMock(side_effect=AssertionError("不应生成弃用摘要"))
    monkeypatch.setattr(RAGService, "search", search)
    monkeypatch.setattr(RAGService, "generate_answer", generate)
    external = SimpleNamespace(search_guidelines=AsyncMock(return_value=[SimpleNamespace(
        title="合成外部", snippet="发热", url=f"https://example.org/synthetic-{i}", source_engine="synthetic",
        trust_score=80, is_trusted=True) for i in range(5)]), _searxng_search=AsyncMock(return_value=[]),
        _filter_trusted=lambda rows: rows)
    from_config = AsyncMock(return_value=external)
    monkeypatch.setattr(ExternalSearchAgent, "from_config", from_config)

    async def rank(_self, query, documents, top_n):
        return [(i, .9 if "外部" in doc else .6) for i, doc in enumerate(documents)]

    monkeypatch.setattr(RerankerService, "rerank", rank)
    result = await SearchMedicalKnowledgeTool().execute("发热", top_k=1)
    assert 2 == search.await_args.kwargs["top_k"]
    assert 1 == result["selected_count"]
    assert (5 if external_enabled else 2) == result["candidate_count"]
    assert ("external" if external_enabled else "internal") == result["sources"][0]["source_type"]
    generate.assert_not_awaited()
    if external_enabled:
        from_config.assert_awaited_once()
    else:
        from_config.assert_not_awaited()
