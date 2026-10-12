"""固定开发集三路检索及上下文消融；只用已核验真实向量，禁止新增HTTP。"""
import json
import logging
import math
import time
from pathlib import Path
from unittest.mock import patch
from resume_embedding_runtime import SOURCE_PATHS as EMBEDDING_SOURCES,corpus_snapshot,run as embedding_probe
from resume_keyword_runtime import SOURCE_PATHS as KEYWORD_SOURCES,project,sha,require

SOURCE_PATHS=tuple(dict.fromkeys((*EMBEDDING_SOURCES,*KEYWORD_SOURCES,'app/services/knowledge_citations.py')))
VARIANTS=('keyword','semantic','hybrid')


def validate_payload(value):
    require(set(value)=={'protocol','mode','questions','documents','input_sha256','source_sha256','top_k',
                         'embedding_probe','expected_snapshot','vectors','vector_evidence_sha256'}
            and value['protocol']=='resume-retrieval-ablation-v1' and value['mode'] in {'preflight','run'}
            and type(value['top_k']) is int and value['top_k']==10,'检索消融协议/字段/固定K非法')
    require(isinstance(value['questions'],list) and len(value['questions'])==24
            and len({q['id'] for q in value['questions']})==24
            and all(set(q)=={'id','query'} and isinstance(q['query'],str) and 0<len(q['query'].strip())<=300 for q in value['questions']),'仅允许开发24查询，无gold')
    require(set(value['source_sha256'])==set(SOURCE_PATHS),'检索源码白名单不同')
    probe=value['embedding_probe']
    require(probe['mode']=='preflight' and probe['max_http_requests']==0 and probe['questions']==value['questions']
            and probe['documents']==value['documents'] and probe['input_sha256']==value['input_sha256'],'向量只读探针范围不同')
    require(isinstance(value['expected_snapshot'],dict),'缺实际预检模型和语料指纹')
    if value['mode']=='preflight':require(value['vectors'] is None and value['vector_evidence_sha256'] is None,'预检禁止注入查询向量')
    else:
        vectors=value['vectors'];dimension=value['expected_snapshot']['dimension']
        require(isinstance(vectors,list) and len(vectors)==24 and all(isinstance(v,list) and len(v)==dimension
                and all(type(x) in (int,float) and math.isfinite(x) for x in v) and any(v) for v in vectors),'真实查询向量缺失/非法/错维度')
        require(isinstance(value['vector_evidence_sha256'],str) and len(value['vector_evidence_sha256'])==64,'缺实际向量证据指纹')


def base_statement():
    from sqlalchemy import select
    from app.models.rag import Document,DocumentChunk,DocType
    # 与生产search的同一语义投影及过滤；相似度和top候选直接调用生产核心。
    return select(DocumentChunk.id,DocumentChunk.content,DocumentChunk.chunk_index,DocumentChunk.embedding_json,
                  Document.id.label('doc_id'),Document.title,Document.doc_type,Document.source_url,Document.embedding_model
                 ).join(Document).where(Document.is_active==True,Document.doc_type==DocType.PLATFORM_GUIDELINE)


async def semantic_search(service,vector,model):
    found=await service._semantic_candidates(base_statement(),vector,model,10)
    return [{'chunk_id':str(row.id),'content':row.content,'chunk_index':row.chunk_index,'document_id':str(row.doc_id),
             'document_title':row.title,'document_type':row.doc_type.value,'source_url':row.source_url,
             'rank':round(score,4),'retrieval_method':'embedding_cosine','retrieval_model':model,
             'retrieval_dimension':len(vector),'retrieval_score':score} for score,row in found]


async def run(value):
    validate_payload(value)
    from sqlalchemy import text
    from app.db.session import async_session_maker,async_engine
    from app.services.rag import RAGService,settings
    from app.services.rag_context import expand_retrieved_contexts
    from app.services.embedding import EmbeddingService
    from app.services.reranker import RerankerService
    from app.services.llm import LLMService
    from app.models.rag import DocType
    from openai import DefaultAsyncHttpxClient
    import httpx
    async_engine.echo=False;logging.disable(logging.CRITICAL)
    hashes={name:sha(Path(name).read_bytes()) for name in SOURCE_PATHS}
    require(hashes==value['source_sha256'],'容器检索源码漂移')
    probe=await embedding_probe(value['embedding_probe'])
    require(probe['complete'] and probe['model_snapshot']==value['expected_snapshot'] and probe['requests']==[],'实际模型/SDK/语料与向量预检不同')
    snapshot=probe['model_snapshot'];counts={'keyword_embedding_disabled':0,'cached_embedding':0,'reranking_disabled':0,'forbidden_http':0,'unexpected_model':0}
    active={};rows=[]
    async def cached_embed(self,queries):
        require(queries==[active['query']],'缓存只允许当前一个真实查询')
        if active['variant']=='keyword':counts['keyword_embedding_disabled']+=1;raise ValueError('EXPERIMENT_KEYWORD_ONLY')
        require(active['variant']=='hybrid','意外向量服务调用')
        counts['cached_embedding']+=1;self._model=snapshot['model'];return [active['vector']]
    async def no_rerank(*args,**kwargs):counts['reranking_disabled']+=1;raise ValueError('EXPERIMENT_NO_RERANKER')
    async def no_http(*args,**kwargs):counts['forbidden_http']+=1;raise AssertionError('检索比较禁止新HTTP')
    async def no_model(*args,**kwargs):counts['unexpected_model']+=1;raise AssertionError('检索比较禁止LLM')
    with patch.object(EmbeddingService,'embed',cached_embed),patch.object(RerankerService,'rerank',no_rerank),\
         patch.object(LLMService,'chat',no_model),patch.object(httpx.AsyncClient,'send',no_http),patch.object(DefaultAsyncHttpxClient,'send',no_http):
        async with async_session_maker() as db:
            await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            require((await db.execute(text('SHOW transaction_read_only'))).scalar()=='on','检索事务非只读')
            settings_sql="SELECT key,value FROM system_settings WHERE key IN ('interview_demo.enabled','interview_demo.limit','interview_demo.used')"
            before=dict((await db.execute(text(settings_sql))).all());require(before==probe['settings_before'],'保护设置在两个只读快照间变化')
            found=(await db.execute(text("SELECT id,title,content,source_url FROM documents WHERE is_active AND doc_type='platform_guideline'"))).mappings().all()
            docs={str(d['id']):{**dict(d),'sha256':sha(d['content'].encode())} for d in found}
            require(set(docs)=={d['document_id'] for d in value['documents']},'语料范围变化')
            for d in value['documents']:
                actual=docs[d['document_id']]
                require(actual['sha256']==d['document_sha256'] and actual['title']==d['title'] and actual['source_url']==d['source_url'],'语料身份变化')
            stored=(await db.execute(text("SELECT c.id,c.document_id,c.chunk_index,c.content,c.embedding_json,d.embedding_model FROM document_chunks c JOIN documents d ON d.id=c.document_id WHERE d.is_active AND d.doc_type='platform_guideline'"))).mappings().all()
            chunks=[{**dict(c),'id':str(c['id']),'document_id':str(c['document_id']),
                     'embedding_json':json.loads(c['embedding_json']) if isinstance(c['embedding_json'],str) else c['embedding_json']} for c in stored]
            corpus=corpus_snapshot(chunks,snapshot['model'])
            require(all(snapshot[k]==v for k,v in corpus.items()),'同数量索引内容变化')
            technical_probe=None
            if value['mode']=='preflight':
                # 自身向量检索只检验数据库/生产语义核心可运行，不是查询语义或效果评测。
                chunk=min(chunks,key=lambda c:c['id']);vector=chunk['embedding_json'];query='索引链路技术探针'
                active.update(query=query,vector=vector,variant='hybrid')
                semantic=await semantic_search(RAGService(db),vector,snapshot['model'])
                hybrid=await RAGService(db).search(query,doc_type=DocType.PLATFORM_GUIDELINE,top_k=10)
                expanded=await expand_retrieved_contexts(db,query,hybrid)
                require(semantic and math.isclose(semantic[0]['retrieval_score'],1.0,abs_tol=1e-8)
                        and [c['chunk_id'] for c in hybrid]==[c['chunk_id'] for c in expanded],'真实索引探针或上下文锚点失败')
                technical_probe={'purpose':'index_self_match_pipeline_only','query_is_evaluation_question':False,
                                 'semantic_anchor_count':len(semantic),'hybrid_anchor_count':len(hybrid),
                                 'self_similarity':semantic[0]['retrieval_score'],'query_embedding_generated':False,
                                 'retrieval_metrics':None}
            else:
                for i,q in enumerate(value['questions']):
                    for j in range(3):
                        variant=VARIANTS[(i+j)%3];active.update(query=q['query'],vector=value['vectors'][i],variant=variant)
                        tick=time.perf_counter()
                        if variant=='semantic':raw=await semantic_search(RAGService(db),active['vector'],snapshot['model'])
                        else:raw=await RAGService(db).search(q['query'],doc_type=DocType.PLATFORM_GUIDELINE,top_k=10)
                        search_ms=round((time.perf_counter()-tick)*1000,3)
                        tick=time.perf_counter();expanded=await expand_retrieved_contexts(db,q['query'],raw)
                        context_ms=round((time.perf_counter()-tick)*1000,3)
                        require([c['chunk_id'] for c in raw]==[c['chunk_id'] for c in expanded],'补全改变排序')
                        row={'id':q['id'],'variant':variant,'status':'success','error_type':None,
                             'anchors':[{k:c[k] for k in ('chunk_id','document_id','chunk_index','content','rank')}
                                        |{k:c[k] for k in ('retrieval_model','retrieval_dimension','retrieval_score') if k in c} for c in raw],
                             'raw_sources':project(raw,docs),'context_sources':project(expanded,docs),
                             'search_ms':search_ms,'context_ms':context_ms}
                        rows.append(row);print(json.dumps({'checkpoint':row},ensure_ascii=False),flush=True)
            after=dict((await db.execute(text(settings_sql))).all());require(before==after,'保护设置变化');await db.rollback()
    require(counts['forbidden_http']==counts['unexpected_model']==0,'发生额外HTTP/模型尝试')
    return {'protocol':value['protocol'],'mode':value['mode'],'input_sha256':value['input_sha256'],'source_sha256':hashes,
            'model_snapshot':snapshot,'vector_evidence_sha256':value['vector_evidence_sha256'],'top_k':10,'rows':rows,
            'vector_corpus':chunks,'counts':counts,'technical_probe':technical_probe,
            'policy':{'rag_query_term_length':settings.rag_query_term_length,'rag_coarse_multiplier':settings.rag_coarse_multiplier,'rag_coarse_min':settings.rag_coarse_min},
            'settings_before':before,'settings_after':after,'read_only':True,'rolled_back':True,'read_gold':False,'holdout_loaded':False,
            'reranking_executed':False,'coverage_model_executed':False,'external_search_executed':False,'full_production_pipeline':False,
            'complete':len(rows)==72 if value['mode']=='run' else not rows}
