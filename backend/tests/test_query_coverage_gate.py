"""覆盖判断接入与缓存/引用恢复合同；模型输出为替身，不称真实模型评测。"""
import hashlib
from unittest.mock import AsyncMock
import pytest
from app.services import knowledge_citations as kc


def candidate(cid, text):
    return kc.KnowledgeCitation(citation_id=cid, source_type='internal', title='合成资料',
                               excerpt=text, document_id='doc', chunk_id=cid, url='https://example.org/source')


def assessment():
    return {'status': 'assessed', 'requirements': ['甲条件', '乙条件'], 'candidates': [
        {'id': 'S3', 'label': 'does_not_answer', 'retain': False, 'coverage_fraction': 0,
         'covered_requirements': [], 'missing_requirements': ['甲条件', '乙条件'], 'uncertain_requirements': []},
        {'id': 'S7', 'label': 'partial_answer', 'retain': True, 'coverage_fraction': .5,
         'covered_requirements': ['甲条件'], 'missing_requirements': ['乙条件'], 'uncertain_requirements': []},
        {'id': 'S9', 'label': 'answers', 'retain': True, 'coverage_fraction': 1,
         'covered_requirements': ['甲条件', '乙条件'], 'missing_requirements': [], 'uncertain_requirements': []}]}


@pytest.mark.asyncio
async def test_partial_kept_wrong_removed_ids_and_excerpts_preserved(monkeypatch):
    sources = [candidate('S3', '另一用途。'), candidate('S7', '甲条件。'), candidate('S9', '甲条件和乙条件。')]
    monkeypatch.setattr(kc, '_assess_query_coverage', AsyncMock(return_value=assessment()))
    ranked = await kc.rank_knowledge_citations('甲条件乙条件', sources, None)
    assert ['S9', 'S7'] == [c.citation_id for c in ranked]
    assert sources[2].excerpt == ranked[0].excerpt
    assert sources[1].url == ranked[1].url
    assert 'query_requirements' == ranked[0].relevance_method
    assert ['乙条件'] == ranked[1].query_coverage['missing_requirements']
    assert sources[0].query_coverage is None
    report = kc.attach_knowledge_citations({'key_findings': ['根据甲条件推断乙情况[S7]']}, ranked)
    assert ['S9', 'S7'] == [c['citation_id'] for c in report['knowledge_citations']]
    assert 'needs_review' == report['knowledge_evidence'][0]['status']


@pytest.mark.asyncio
async def test_same_query_and_excerpt_cache_avoids_second_model_call(monkeypatch):
    mock = AsyncMock(return_value=assessment())
    monkeypatch.setattr(kc, '_assess_query_coverage', mock)
    sources = [candidate('S3', '另一用途。'), candidate('S7', '甲条件。'), candidate('S9', '甲乙条件。')]
    first = await kc.rank_knowledge_citations('甲条件乙条件', sources, None)
    second = await kc.rank_knowledge_citations('甲条件乙条件', first, None)
    assert ['S9', 'S7'] == [c.citation_id for c in second]
    assert 1 == mock.await_count


@pytest.mark.asyncio
async def test_changed_excerpt_invalidates_coverage_cache(monkeypatch):
    async def filtered(query, citations, db):
        value = assessment()
        value['candidates'] = [r for r in value['candidates'] if r['id'] in {c.citation_id for c in citations}]
        return value
    mock = AsyncMock(side_effect=filtered)
    monkeypatch.setattr(kc, '_assess_query_coverage', mock)
    first = await kc.rank_knowledge_citations('甲乙条件', [candidate('S3', '另一用途'), candidate('S7', '甲条件'), candidate('S9', '甲乙条件')], None)
    await kc.rank_knowledge_citations('甲乙条件', [c.model_copy(update={'excerpt': c.excerpt + '新增内容'}) for c in first], None)
    assert 2 == mock.await_count


@pytest.mark.asyncio
async def test_failed_assessment_falls_back_without_claiming_coverage(monkeypatch):
    monkeypatch.setattr(kc, '_assess_query_coverage', AsyncMock(return_value={'status': 'assessment_error'}))
    from app.services.reranker import RerankerService
    monkeypatch.setattr(RerankerService, 'rerank', AsyncMock(side_effect=ValueError('未配置')))
    ranked = await kc.rank_knowledge_citations('甲条件', [candidate('S5', '甲条件应记录。')], None)
    assert ['S5'] == [c.citation_id for c in ranked]
    assert 'keyword' == ranked[0].relevance_method
    assert ranked[0].query_coverage is None


def test_builder_keeps_coverage_only_when_excerpt_is_identical():
    source = candidate('S8', '甲条件。').model_dump()
    source.update(relevance_method='query_requirements', query_coverage={'excerpt_sha256': hashlib.sha256('甲条件。'.encode()).hexdigest(),
                  'requirements': ['甲条件'], 'covered_requirements': ['甲条件'], 'missing_requirements': [],
                  'uncertain_requirements': [], 'status': 'answers'})
    restored = kc.build_knowledge_citations([source])[0]
    assert 'query_requirements' == restored.relevance_method
    assert 'answers' == restored.query_coverage['status']


@pytest.mark.asyncio
async def test_invalidated_coverage_cleared_when_reassessment_fails(monkeypatch):
    monkeypatch.setattr(kc, '_assess_query_coverage', AsyncMock(return_value={'status': 'assessment_error'}))
    from app.services.reranker import RerankerService
    monkeypatch.setattr(RerankerService, 'rerank', AsyncMock(side_effect=ValueError('未配置')))
    source = candidate('S5', '甲条件已改写。').model_copy(update={
        'relevance_method': 'query_requirements', 'relevance': 1,
        'relevance_policy_version': kc.SOURCE_POLICY_VERSION,
        'relevance_query_fingerprint': hashlib.sha256('甲条件'.encode()).hexdigest(),
        'query_coverage': {'status': 'answers', 'excerpt_sha256': hashlib.sha256('旧摘录'.encode()).hexdigest()}})
    ranked = await kc.rank_knowledge_citations('甲条件', [source], None)
    assert ['S5'] == [c.citation_id for c in ranked]
    assert 'keyword' == ranked[0].relevance_method
    assert ranked[0].query_coverage is None
