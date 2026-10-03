"""跨来源统一口径、异常降级和配置边界；不调用外部服务。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.config import DynamicConfigService
from app.services.knowledge_citations import KnowledgeCitation, rank_knowledge_citations
from app.services.reranker import RerankerService


def source(index, title, **metadata):
    return KnowledgeCitation(citation_id=f"S{index}", source_type="internal", title=title,
                             excerpt=title, document_id="synthetic-doc", chunk_id=str(index), **metadata)


@pytest.mark.asyncio
async def test_统一重排不能沿用向量分或可信度分(monkeypatch):
    rerank = AsyncMock(return_value=[(1, .9), (0, .2)])
    monkeypatch.setattr(RerankerService, "rerank", rerank)
    result = await rank_knowledge_citations("合成 query", [source(1, "first", relevance=.99), source(2, "second", relevance=.01)], None)
    assert ["S2"] == [c.citation_id for c in result]
    assert "reranker" == result[0].relevance_method
    assert .9 == result[0].relevance
    assert "不代表原文支持" in result[0].relevance_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("scores", [[(0, float("nan")), (1, .9)], [(0, .8)], [(0, .8), (0, .7)], [(0, 91), (1, .1)]])
async def test_损坏重排整个候选池降级不混合口径(monkeypatch, scores):
    monkeypatch.setattr(RerankerService, "rerank", AsyncMock(return_value=scores))
    result = await rank_knowledge_citations("发热", [source(1, "发热"), source(2, "牙齿")], None)
    assert ["S1"] == [c.citation_id for c in result]
    assert "keyword" == result[0].relevance_method


@pytest.mark.asyncio
async def test_跨语言无法词匹配不伪装成不相关(monkeypatch):
    monkeypatch.setattr(RerankerService, "rerank", AsyncMock(side_effect=TimeoutError()))
    result = await rank_knowledge_citations("发热", [source(1, "fever guideline")], None)
    assert 1 == len(result)
    assert result[0].relevance is None
    assert "unassessed" == result[0].relevance_method


@pytest.mark.asyncio
async def test_缓存同主题也要重新应用阈值(monkeypatch):
    rerank = AsyncMock(return_value=[(0, .6), (1, .9)])
    monkeypatch.setattr(RerankerService, "rerank", rerank)
    ranked = await rank_knowledge_citations("发热", [source(1, "发热 A"), source(2, "发热 B")], None)
    result = await rank_knowledge_citations("发热", ranked, None, min_relevance=.8)
    assert ["S2"] == [c.citation_id for c in result]
    assert 1 == rerank.await_count


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "broken"])
async def test_无效相关性阈值恢复默认(monkeypatch, raw):
    monkeypatch.setattr(DynamicConfigService, "get_str", AsyncMock(return_value=raw))
    policy = await DynamicConfigService.knowledge_source_policy(SimpleNamespace())
    assert .25 == policy["min_relevance"]
    assert 10 == policy["internal_candidates"]
