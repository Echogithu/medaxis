"""上下文从工具到来源归一化/保存/历史恢复的完整性；不调用模型或患者数据库。"""
import hashlib
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy.exc import SQLAlchemyError
from app.services.rag_context import expand_retrieved_contexts
from app.services.knowledge_citations import (attach_knowledge_citations,build_knowledge_citations,
    format_knowledge_context,restore_report_sources)
from app.models.rag import DocType


def source():
    text='完整锚点与补充原文。'*90
    return {'citation_id':'S4','source_type':'internal','title':'真实返回的合成资料','document_id':'doc',
        'chunk_id':'a','chunk_index':0,'excerpt':text,'context_metadata':{
        'document_id':'doc','anchor_chunk_id':'a','chunk_ids':['a','b'],'start':20,'end':20+len(text),
        'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),'method':'anchor_neighbors','max_chars':1600}}


def test_long_context_and_metadata_survive_agent_normalization_save_and_history_restore():
    raw=source();citations=build_knowledge_citations([raw])
    assert citations[0].excerpt==raw['excerpt'] and len(citations[0].excerpt)>800
    normalized=build_knowledge_citations([c.model_dump() for c in citations])
    assert normalized[0].context_metadata==raw['context_metadata']
    report=attach_knowledge_citations({'primary_diagnosis':'需要核对[S1]'},normalized)
    assert report['knowledge_citations'][0]['excerpt']==raw['excerpt']
    restored=restore_report_sources({'primary_diagnosis':'核对[S4]','knowledge_retrieval_count':1},
        [{'tool':'search_medical_knowledge','result':{'sources':[raw]}}])
    item=restored['knowledge_citations'][0]
    assert item['citation_id']=='S4' and item['context_metadata']==raw['context_metadata']
    assert item['excerpt']==raw['excerpt']
    assert '相邻内容' in format_knowledge_context(citations)


def test_wrong_anchor_metadata_is_discarded_without_erasing_source():
    raw=source();raw['context_metadata']['anchor_chunk_id']='wrong'
    citations=build_knowledge_citations([raw])
    assert len(citations)==1 and citations[0].context_metadata is None
    assert len(citations[0].excerpt)==800


def fixture():
    did=uuid.uuid4();cid=uuid.uuid4();nid=uuid.uuid4()
    text='命中主题原文。前后条件尚需一起查看。'
    anchor={'document_id':str(did),'chunk_id':str(cid),'chunk_index':0,'content':text[:12],
            'document_title':'合成指南','document_type':'platform_guideline','source_url':None,'rank':.5}
    rows=[SimpleNamespace(id=cid,document_id=did,chunk_index=0,content=text[:12]),
          SimpleNamespace(id=nid,document_id=did,chunk_index=1,content=text[5:])]
    document=SimpleNamespace(id=did,content=text,title='合成指南',source_url=None,doc_type=DocType.PLATFORM_GUIDELINE)
    return anchor,document,rows


@pytest.mark.asyncio
async def test_database_neighbor_queries_are_batched_and_anchor_checked():
    anchor,document,rows=fixture()
    @asynccontextmanager
    async def nested():yield
    db=SimpleNamespace(begin_nested=nested,execute=AsyncMock(side_effect=[SimpleNamespace(all=lambda:[document]),SimpleNamespace(all=lambda:rows)]))
    result=await expand_retrieved_contexts(db,'主题',[anchor,anchor])
    assert db.execute.await_count==2
    assert len(result)==2 and result[0]['content']==document.content
    assert result[0]['context_metadata']['anchor_chunk_id']==anchor['chunk_id']


@pytest.mark.asyncio
async def test_context_database_failure_keeps_original_sources_and_does_not_commit():
    anchor,_,_=fixture()
    @asynccontextmanager
    async def nested():yield
    db=SimpleNamespace(begin_nested=nested,execute=AsyncMock(side_effect=SQLAlchemyError('synthetic error')))
    assert await expand_retrieved_contexts(db,'主题',[anchor])==[anchor]
