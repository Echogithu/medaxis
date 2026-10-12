"""泛词误入、跨语言、版本和缓存门禁反例；全部为合成资料，不作医学gold。"""
import hashlib
from unittest.mock import AsyncMock
import pytest
from app.services.knowledge_citations import build_knowledge_citations, rank_knowledge_citations
from app.services.reranker import RerankerService


def source(query,score=None,**fields):
    return {'source_type':'internal','title':'合成主题资料','document_id':'doc','chunk_id':'chunk',
            'excerpt':'当前需要记录观察信息。','retrieval_method':'embedding_cosine',
            'retrieval_model':'text-embedding-3-small','retrieval_dimension':1536,
            'retrieval_score':score,'retrieval_query_fingerprint':hashlib.sha256(query.strip()[:512].encode()).hexdigest(),**fields}


@pytest.fixture(autouse=True)
def no_reranker(monkeypatch):
    monkeypatch.setattr(RerankerService,'rerank',AsyncMock(side_effect=ValueError('无供应商')))


@pytest.mark.asyncio
async def test_low_semantic_match_is_not_rescued_by_generic_word_in_long_context():
    query='合成问题需要哪些信息'
    sources=build_knowledge_citations([source(query,.2)],max_excerpt_chars=1600)
    assert await rank_knowledge_citations(query,sources,None)==[]


@pytest.mark.asyncio
async def test_high_cross_language_match_is_kept_but_not_labelled_clinical_support():
    query='中文问题'
    ranked=await rank_knowledge_citations(query,build_knowledge_citations([source(query,.6,title='English heading',excerpt='English text only.')]),None)
    assert len(ranked)==1
    assert ranked[0].relevance_method=='unassessed'
    assert ranked[0].retrieval_score==.6


@pytest.mark.asyncio
async def test_low_cross_language_match_cannot_bypass_gate_as_unassessed():
    query='中文问题'
    assert await rank_knowledge_citations(query,build_knowledge_citations([source(query,.2,title='English',excerpt='English text.')]),None)==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('fields',[{'retrieval_model':'other-model'},{'retrieval_dimension':12},
    {'retrieval_score':float('nan')},{'retrieval_method':'keyword'},
    {'retrieval_query_fingerprint':'wrong'},{'retrieval_score':None}])
async def test_uncalibrated_or_unverifiable_semantic_metadata_does_not_pretend_reliable(fields):
    query='中文问题'
    data=source(query,.2,title='English',excerpt='English text.',**fields)
    ranked=await rank_knowledge_citations(query,build_knowledge_citations([data]),None)
    assert len(ranked)==1 and ranked[0].relevance_method=='unassessed'


@pytest.mark.asyncio
async def test_explicit_requested_release_version_is_not_replaced_by_older_article():
    query='2029年新发布的合成主题指南更新了什么'
    assert await rank_knowledge_citations(query,build_knowledge_citations([source(query,.9,title='合成主题指南（2025年版）')]),None)==[]


@pytest.mark.asyncio
async def test_birth_year_is_not_a_requested_release_version():
    query='2020年出生的孩子发热'
    assert len(await rank_knowledge_citations(query,build_knowledge_citations([source(query,.9,excerpt='发热需记录症状。')]),None))==1


@pytest.mark.asyncio
async def test_same_query_cached_keyword_score_cannot_bypass_new_semantic_gate():
    query='需要记录信息'
    data=source(query,.2,relevance=.8,relevance_method='keyword',relevance_level='matched',
                relevance_query_fingerprint=hashlib.sha256(query.encode()).hexdigest())
    assert await rank_knowledge_citations(query,build_knowledge_citations([data]),None)==[]


@pytest.mark.asyncio
async def test_low_semantic_score_does_not_delete_specific_topic_word():
    query='口语描述奶粉问题需要哪些信息'
    ranked=await rank_knowledge_citations(query,build_knowledge_citations([source(query,.3,excerpt='记录奶粉摄入与反应。')]),None)
    assert len(ranked)==1


@pytest.mark.asyncio
async def test_treatment_and_time_alone_do_not_override_low_semantic_score():
    query='合成稀有主题治疗时间本知识库有依据吗'
    assert await rank_knowledge_citations(query,build_knowledge_citations([source(query,.3,excerpt='治疗时间需要观察。')]),None)==[]


@pytest.mark.asyncio
async def test_neighbor_added_topic_word_cannot_rescue_unrelated_anchor():
    query='合成主题需要资料'
    data=source(query,.3,title='背景资料',excerpt='前段合成主题说明。',retrieval_anchor_excerpt='完全不同的背景段落。')
    assert await rank_knowledge_citations(query,build_knowledge_citations([data]),None)==[]


@pytest.mark.asyncio
async def test_valid_reranker_is_not_overridden_by_embedding_screen(monkeypatch):
    query='中文问题'
    monkeypatch.setattr(RerankerService,'rerank',AsyncMock(return_value=[(0,.9)]))
    ranked=await rank_knowledge_citations(query,build_knowledge_citations([source(query,.2,title='English',excerpt='English text.')]),None)
    assert len(ranked)==1 and ranked[0].relevance_method=='reranker'


@pytest.mark.asyncio
async def test_category_label_alone_does_not_override_low_semantic_score():
    query='专题甲需要哪些治疗时间资料'
    assert await rank_knowledge_citations(query,build_knowledge_citations([
        source(query,.2,title='其他专题',excerpt='治疗时间需要记录。')]),None)==[]
