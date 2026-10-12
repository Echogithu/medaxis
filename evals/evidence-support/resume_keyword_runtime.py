"""实际RAG关键词回退及邻接补全的只读开发集消融；不执行模型或gold。"""
import hashlib
import json
import logging
import time
from pathlib import Path
from unittest.mock import patch

SOURCE_PATHS=('app/services/rag.py','app/services/rag_context.py','app/services/embedding.py',
              'app/services/reranker.py','app/models/rag.py','app/db/session.py','app/core/config.py')


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(data):return hashlib.sha256(data).hexdigest()


def validate_payload(payload):
    require(set(payload)=={'protocol','questions','documents','input_sha256','source_sha256','top_k'}
            and payload['protocol']=='resume-keyword-context-ablation-v1' and payload['top_k']==10,'关键词消融协议/固定K不同')
    require(len(payload['questions'])==24 and len({q['id'] for q in payload['questions']})==24,'仅允许开发24组')
    require(all(set(q)=={'id','query'} and isinstance(q['query'],str) and bool(q['query'].strip()) for q in payload['questions']),'执行输入含gold或非法查询')
    require(set(payload['source_sha256'])==set(SOURCE_PATHS),'源码白名单不同')
    require(len(payload['documents'])==len({d['document_id'] for d in payload['documents']})==4
            and all(set(d)=={'document_id','document_sha256','title','source_url'} for d in payload['documents']),'文档身份清单非法')


def project(chunks,documents):
    results=[];seen=set()
    for item in chunks:
        require(item['document_id'] in documents,'检索到冻结语料外的文档')
        doc=documents[item['document_id']]
        require(item['document_title']==doc['title'] and item['source_url']==doc['source_url'],'检索出处不同')
        quote=item['content'];meta=item.get('context_metadata')
        if meta:
            require(set(meta)>= {'start','end','source_text_sha256'} and meta['source_text_sha256']==doc['sha256'],'上下文原文SHA不同')
            start,end=meta['start'],meta['end']
        else:
            require(bool(quote) and doc['content'].count(quote)==1,'原始chunk定位不唯一，不能伪造坐标')
            start=doc['content'].index(quote);end=start+len(quote)
        require(type(start) is int and type(end) is int and 0<=start<end<=len(doc['content'])
                and doc['content'][start:end]==quote,'实际摘录与原文坐标不一致')
        key=(item['document_id'],start,end)
        # 相邻命中可能补成同一窗口；稳定去重，不重复计算同一证据。
        if key not in seen:
            seen.add(key);results.append({'document_id':key[0],'start':start,'end':end,'quote':quote})
    return results


async def run(payload):
    validate_payload(payload)
    from sqlalchemy import text
    from app.db.session import async_session_maker,async_engine
    from app.services.rag import RAGService,settings
    from app.services.rag_context import expand_retrieved_contexts
    from app.services.embedding import EmbeddingService
    from app.services.reranker import RerankerService
    from app.services.llm import LLMService
    from openai import DefaultAsyncHttpxClient
    import httpx
    async_engine.echo=False;logging.disable(logging.CRITICAL)
    hashes={name:sha(Path(name).read_bytes()) for name in SOURCE_PATHS}
    require(hashes==payload['source_sha256'],'容器关键词源码与本地不同')
    counts={'embedding_disabled':0,'reranking_disabled':0,'unexpected_model':0,'forbidden_http':0}
    async def disable_embedding(*args,**kwargs):
        counts['embedding_disabled']+=1;raise ValueError('EXPERIMENT_KEYWORD_ONLY')
    async def disable_reranking(*args,**kwargs):
        counts['reranking_disabled']+=1;raise ValueError('EXPERIMENT_NO_RERANKER')
    async def forbidden_model(*args,**kwargs):
        counts['unexpected_model']+=1;raise AssertionError('关键词消融禁止模型')
    async def forbidden_http(*args,**kwargs):
        counts['forbidden_http']+=1;raise AssertionError('关键词消融禁止HTTP')
    rows=[]
    with patch.object(EmbeddingService,'embed',disable_embedding),patch.object(RerankerService,'rerank',disable_reranking),\
         patch.object(LLMService,'chat',forbidden_model),patch.object(httpx.AsyncClient,'send',forbidden_http),\
         patch.object(DefaultAsyncHttpxClient,'send',forbidden_http):
        async with async_session_maker() as db:
            await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            transaction=(await db.execute(text('SHOW transaction_read_only'))).scalar()
            require(transaction=='on','事务非只读')
            found=(await db.execute(text("SELECT id,title,content,source_url FROM documents WHERE is_active AND doc_type='platform_guideline'"))).mappings()
            docs={str(d['id']):{**dict(d),'sha256':sha(d['content'].encode())} for d in found}
            require(set(docs)=={d['document_id'] for d in payload['documents']},'当前语料范围不同')
            for d in payload['documents']:
                actual=docs[d['document_id']]
                require(actual['sha256']==d['document_sha256'] and actual['title']==d['title'] and actual['source_url']==d['source_url'],'当前语料身份不同')
            from app.models.rag import DocType
            for q in payload['questions']:
                tick=time.perf_counter()
                raw=await RAGService(db).search(q['query'],doc_type=DocType.PLATFORM_GUIDELINE,top_k=10)
                raw_ms=round((time.perf_counter()-tick)*1000,3)
                tick=time.perf_counter();expanded=await expand_retrieved_contexts(db,q['query'],raw)
                context_ms=round((time.perf_counter()-tick)*1000,3)
                require([c['chunk_id'] for c in raw]==[c['chunk_id'] for c in expanded],'补全改变了命中排序')
                row={'id':q['id'],'status':'success','error_type':None,'anchor_chunk_ids':[c['chunk_id'] for c in raw],
                     'raw_sources':project(raw,docs),'context_sources':project(expanded,docs),
                     'raw_keyword_ms':raw_ms,'context_only_ms':context_ms,
                     'expanded_anchor_count':sum('context_metadata' in c for c in expanded)}
                rows.append(row);print(json.dumps({'checkpoint':row},ensure_ascii=False),flush=True)
            await db.rollback()
    require(counts['forbidden_http']==counts['unexpected_model']==0,'发生额外模型或网络尝试')
    return {'protocol':payload['protocol'],'input_sha256':payload['input_sha256'],'source_sha256':hashes,
            'mode':'actual_keyword_fallback_context_ablation','top_k':10,'rows':rows,'complete':len(rows)==24,
            'read_only':True,'rolled_back':True,'read_gold':False,'holdout_loaded':False,'counts':counts,
            'policy':{'rag_query_term_length':settings.rag_query_term_length,'rag_coarse_multiplier':settings.rag_coarse_multiplier,'rag_coarse_min':settings.rag_coarse_min},
            'embedding_executed':False,'reranking_executed':False,'coverage_model_executed':False,
            'external_search_executed':False,'full_production_pipeline':False}
