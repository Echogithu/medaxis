"""锁定真实检索已有候选却筛空，以及无依据仍生成报告的回归。"""
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import agents as agents_module
from app.services.agents import DiagnosisAgent, DiagnosisReport, AgentResult
from app.services.knowledge_citations import KnowledgeCitation, rank_knowledge_citations
from app.services.reranker import RerankerService

QUERY = '成人轻度腹部不适腹泻两天大便性状次数黏液血便未核对无明确发烧既往轻度焦虑甲状腺功能亢进严重程度未知近期饮食和接触病人情况不清楚用药过敏不详医学鉴别诊断'

@pytest.mark.asyncio
async def test_长查询的词覆盖率不能套用语义阈值清空有主题匹配的来源(monkeypatch):
    monkeypatch.setattr(RerankerService, 'rerank', AsyncMock(side_effect=ValueError('unconfigured')))
    related=KnowledgeCitation(citation_id='S1',source_type='internal',title='腹泻资料',excerpt='腹泻时需记录大便性状与次数。',document_id='doc',chunk_id='chunk')
    unrelated=related.model_copy(update={'citation_id':'S2','title':'骨折资料','excerpt':'骨折的影像检查。'})
    ranked=await rank_knowledge_citations(QUERY,[related,unrelated],None,min_relevance=.25)
    assert ['S1']==[c.citation_id for c in ranked]
    assert 'keyword'==ranked[0].relevance_method
    # 第二次工作流筛选也不能把缓存的词匹配分数当语义分。
    cached=await rank_knowledge_citations(QUERY,ranked,None,min_relevance=.9)
    assert ['S1']==[c.citation_id for c in cached]

def setup_workflow(monkeypatch, sources):
    @asynccontextmanager
    async def fake_db():
        yield SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda:None)))
    monkeypatch.setattr(agents_module,'async_session_maker',fake_db)
    monkeypatch.setattr(agents_module.DynamicConfigService,'diagnosis_report_source_limit',AsyncMock(return_value=10))
    monkeypatch.setattr(agents_module.DynamicConfigService,'knowledge_source_policy',AsyncMock(return_value={'min_relevance':.25}))
    monkeypatch.setattr(agents_module.GLOBAL_REGISTRY,'execute',AsyncMock(return_value={'success':True,'result':{'sources':sources}}))
    agent=DiagnosisAgent()
    agent._generate_search_query=AsyncMock(return_value='腹泻')
    agent._update_session=AsyncMock()
    return agent

@pytest.mark.asyncio
async def test_真实工作流零来源必须阻止诊断和保存且向入口抛明确错误(monkeypatch):
    agent=setup_workflow(monkeypatch,[])
    agent.analyze=AsyncMock(return_value=AgentResult(agent_type='diagnosis',content={},structured_output=DiagnosisReport(primary_diagnosis='无依据的结论',confidence='high')))
    with pytest.raises(ValueError,match='可核验'):
        await agent.run_full_diagnosis_workflow(str(uuid.uuid4()))
    agent.analyze.assert_not_awaited()
    agent._update_session.assert_not_awaited()

@pytest.mark.asyncio
async def test_直接诊断入口也必须检索且保留实际来源(monkeypatch):
    source={'source_type':'internal','title':'腹泻资料','document_id':'doc','chunk_id':'chunk','excerpt':'记录大便性状。'}
    agent=setup_workflow(monkeypatch,[source])
    llm=SimpleNamespace(chat_with_tools=AsyncMock(return_value=SimpleNamespace(content='{"primary_diagnosis":"需进一步核对[S1]","confidence":"low"}',tool_calls=None)))
    monkeypatch.setattr(agents_module,'LLMService',lambda **_kwargs:llm)
    monkeypatch.setattr(agents_module.GLOBAL_REGISTRY,'list_schemas',lambda:[])
    result=await agent.analyze(symptoms='合成腹泻主诉')
    assert 1==agents_module.GLOBAL_REGISTRY.execute.await_count
    assert 1==len(result.structured_output.knowledge_citations)
    assert 'doc'==result.structured_output.knowledge_citations[0].document_id
    assert '[S1]' in llm.chat_with_tools.await_args.kwargs['messages'][0]['content']

@pytest.mark.asyncio
async def test_资料存在但正文无有效引用时不能保存医学报告(monkeypatch):
    agent=setup_workflow(monkeypatch,[{'source_type':'internal','title':'腹泻资料','document_id':'doc','chunk_id':'chunk','excerpt':'腹泻资料。'}])
    agent.analyze=AsyncMock(return_value=AgentResult(agent_type='diagnosis',content={},structured_output=DiagnosisReport(primary_diagnosis='未绑定的医学判断',confidence='high')))
    agent._restore_missing_citation_markers=AsyncMock(side_effect=lambda report,_sources:report)
    with pytest.raises(ValueError,match='可核验'):
        await agent.run_full_diagnosis_workflow(str(uuid.uuid4()))
    agent._update_session.assert_not_awaited()

@pytest.mark.asyncio
async def test_已完成问诊但无有据报告允许重试并返回可识别的检索错误(monkeypatch):
    import json
    from starlette.requests import Request
    from app.api.v1 import agents as api
    from app.db import redis_client
    from app.services.llm_errors import MedicalEvidenceUnavailableError
    patient_id,session_id=uuid.uuid4(),uuid.uuid4()
    session=SimpleNamespace(id=session_id,user_id=patient_id,structured_output=None)
    db=SimpleNamespace(get=AsyncMock(return_value=session),execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:[]))))
    state=SimpleNamespace(asked_questions=[],is_sufficient=True,phase='completed',red_flags_detected=[])
    diagnostic=SimpleNamespace(interview_answer=AsyncMock(return_value=([],state,[],'completed','')),
                               run_full_diagnosis_workflow=AsyncMock(side_effect=MedicalEvidenceUnavailableError('可核验资料缺失')))
    monkeypatch.setattr(api,'_require_session_access',AsyncMock())
    monkeypatch.setattr(api,'_patient_history_with_profile',AsyncMock(return_value=None))
    monkeypatch.setattr(api,'DiagnosisAgent',lambda **_kwargs:diagnostic)
    monkeypatch.setattr(redis_client,'get_redis',lambda:SimpleNamespace(exists=AsyncMock(return_value=False),set=AsyncMock(return_value=True),delete=AsyncMock()))
    request=Request({'type':'http','method':'GET','query_string':b'','headers':[]})
    stream=await api.route_stream_continue(request=request,ctx=SimpleNamespace(user=SimpleNamespace(id=patient_id),is_guest=False,platform='web'),
                                          session_id=str(session_id),question_id='hpi_onset',db=db)
    events=''.join([chunk async for chunk in stream.body_iterator])
    assert 'event: structured' not in events and 'event: complete' not in events
    payload=json.loads(events.split('event: error\ndata: ',1)[1].split('\n\n',1)[0])
    assert 'MEDICAL_EVIDENCE_UNAVAILABLE'==payload['code']
    diagnostic.run_full_diagnosis_workflow.assert_awaited_once()

@pytest.mark.asyncio
async def test_直接HTTP诊断无证据返回明确503而非成功报告(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1 import agents as api
    from app.services.llm_errors import MedicalEvidenceUnavailableError
    async def operation(_db,_ctx,**kwargs): return await kwargs['operation']()
    diagnostic=SimpleNamespace(analyze=AsyncMock(side_effect=MedicalEvidenceUnavailableError('可核验资料缺失')))
    monkeypatch.setattr(api,'_resolve_patient_scope',lambda *_args:None)
    monkeypatch.setattr(api,'_patient_history_with_profile',AsyncMock(return_value=None))
    monkeypatch.setattr(api,'DiagnosisAgent',lambda **_kwargs:diagnostic)
    monkeypatch.setattr(api,'run_guest_submission',operation)
    with pytest.raises(HTTPException) as caught:
        await api.diagnose(api.DiagnosisRequest(symptoms='合成腹泻主诉'),SimpleNamespace(),object(),idempotency_key=None)
    assert 503==caught.value.status_code
    assert 'MEDICAL_EVIDENCE_UNAVAILABLE'==caught.value.detail['code']
