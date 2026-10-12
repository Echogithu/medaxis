"""语义优先保留一个明确词命中席位，不扩大候选预算或伪造语义分。"""
import uuid
import pytest
from unittest.mock import AsyncMock
from types import SimpleNamespace
from app.services import rag


def row(i,content='背景文字'):
    return SimpleNamespace(id=uuid.UUID(int=i),content=content)


def test_explicit_lexical_best_survives_semantic_top_k_without_budget_growth():
    semantic=[(.9-i*.01,row(i+1)) for i in range(20)]
    target=row(99,'ALPHASYNDROME 12h 定义的原文。')
    scores={str(r.id):s for s,r in semantic};scores[str(target.id)]=.31
    selected=rag._reserve_keyword_candidate('ALPHASYNDROME 12h 定义',semantic,[target],scores,10)
    assert len(selected)==20
    assert [r.id for _,r in selected[:9]]==[r.id for _,r in semantic[:9]]
    assert selected[9]==(.31,target)
    assert len({r.id for _,r in selected})==20


def test_generic_overlap_cannot_take_semantic_seat():
    semantic=[(.9,row(1)),(.8,row(2))]
    target=row(3,'治疗时间需要记录。')
    assert rag._reserve_keyword_candidate('专题治疗时间需要资料',semantic,[target],{str(target.id):.2},2)==semantic


def test_one_result_keeps_best_semantic_and_existing_keyword_does_not_reorder():
    semantic=[(.9,row(1,'ALPHASYNDROME 12h 定义')), (.8,row(2))]
    scores={str(r.id):s for s,r in semantic}
    assert rag._reserve_keyword_candidate('ALPHASYNDROME 12h 定义',semantic,[semantic[0][1]],scores,2)==semantic
    target=row(3,'ALPHASYNDROME 12h 定义')
    assert rag._reserve_keyword_candidate('ALPHASYNDROME 12h 定义',semantic,[target],{str(target.id):.2},1)==semantic


def test_scattered_words_do_not_reserve_an_unrelated_disease():
    semantic=[(.9,row(1)),(.8,row(2))]
    target=row(3,'慢性呼吸系统疾病、肾病是某病的高危因素。')
    assert rag._reserve_keyword_candidate('慢性肾病腹膜透析液交换',semantic,[target],{str(target.id):.25},2)==semantic


def test_contiguous_specific_phrase_reserves_without_changing_cosine():
    semantic=[(.9,row(1)),(.8,row(2))]
    target=row(3,'真正耐药需要进一步核实。')
    selected=rag._reserve_keyword_candidate('是否真正耐药',semantic,[target],{str(target.id):.28},2)
    assert selected==[semantic[0],(.28,target),semantic[1]]


@pytest.mark.asyncio
async def test_real_search_seam_preserves_keyword_url_and_raw_score(monkeypatch):
    from tests.test_rag_relevance import _SemanticDb, _semantic_row, _configured_embed
    semantic=[_semantic_row(i,[1.,i*.02]) for i in range(20)]
    target=_semantic_row(100,[.3,1.]);target.content='ALPHASYNDROME 12h 定义的原文'
    target.source_url='https://www.nhc.gov.cn/verified.pdf'
    monkeypatch.setattr(rag.EmbeddingService,'embed',_configured_embed)
    monkeypatch.setattr(rag.RerankerService,'rerank',AsyncMock(side_effect=ValueError('offline')))
    result=await rag.RAGService(_SemanticDb([target],semantic)).search('ALPHASYNDROME 12h 定义',top_k=10)
    assert len(result)==10
    assert result[9]['chunk_id']==str(target.id)
    assert result[9]['source_url']==target.source_url
    assert result[9]['retrieval_score']==pytest.approx(.3/(1.09**.5))
