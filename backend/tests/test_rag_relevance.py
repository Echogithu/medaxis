"""验证粗筛召回和缺少重排模型时的检索结果契约。"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.models.rag import DocType
from app.services import rag as rag_module
from app.services.rag import RAGService


class _EmptyResult:
    def all(self):
        return []


class _CaptureDb:
    statement = None

    async def execute(self, statement):
        self.statement = statement
        return _EmptyResult()


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _RowsDb:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        return _RowsResult(self.rows)


@pytest.mark.asyncio
async def test_coarse_search_includes_late_symptom_and_treatment_terms():
    db = _CaptureDb()

    result = await RAGService(db).search(
        "儿童急性感染性腹泻病脱水评估和口服补液盐治疗原则",
        top_k=5,
    )

    assert result == []
    compiled = db.statement.compile(dialect=postgresql.dialect())
    patterns = {value for value in compiled.params.values() if isinstance(value, str)}
    assert "%脱水%" in patterns
    assert "%补液%" in patterns
    assert "ORDER BY" in str(compiled)


@pytest.mark.asyncio
async def test_missing_reranker_keeps_top_k_and_vector_relevance(monkeypatch):
    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            content=f"腹泻补液片段 {index}",
            chunk_index=index,
            embedding_json=embedding,
            doc_id=uuid.uuid4(),
            title="儿童腹泻指南",
            doc_type=DocType.PLATFORM_GUIDELINE,
            source_url=None,
        )
        for index, embedding in enumerate(
            ([1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.7, 0.3])
        )
    ]

    async def embed(_self, _texts):
        return [[1.0, 0.0]]

    async def missing_reranker(_self):
        raise ValueError("No active reranking provider")

    monkeypatch.setattr(rag_module.EmbeddingService, "embed", embed)
    monkeypatch.setattr(rag_module.RerankerService, "_get_client", missing_reranker)

    result = await RAGService(_RowsDb(rows)).search("儿童腹泻补液", top_k=2)

    assert len(result) == 2
    assert [item["chunk_index"] for item in result] == [0, 1]
    assert result[1]["rank"] < 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize('reranked', [[], [(99, .9)], [(0, float('nan'))], [(0, .9), (0, .8)]])
async def test_空或损坏重排不能丢掉已检索到的原始片段(monkeypatch, reranked):
    row=SimpleNamespace(id=uuid.uuid4(),content='腹泻补液相关指南。',chunk_index=0,embedding_json=None,
                        doc_id=uuid.uuid4(),title='腹泻指南',doc_type=DocType.PLATFORM_GUIDELINE,source_url=None)
    monkeypatch.setattr(rag_module.EmbeddingService,'embed',AsyncMock(return_value=[[1.,0.]]))
    monkeypatch.setattr(rag_module.RerankerService,'rerank',AsyncMock(return_value=reranked))
    result=await RAGService(_RowsDb([row])).search('腹泻补液',top_k=1)
    assert 1==len(result)
    assert str(row.id)==result[0]['chunk_id']
    assert 0.0==result[0]['rank']
