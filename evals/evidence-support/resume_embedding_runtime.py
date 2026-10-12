"""开发24题真实批量向量入口；只读、单次请求、原生响应与即时证据。"""
import asyncio
import base64
import hashlib
import inspect
import json
import logging
import math
import struct
import sys
import time
from pathlib import Path
from unittest.mock import patch

SOURCE_PATHS=('app/services/embedding.py','app/services/text_privacy.py','app/services/interview_demo.py',
              'app/db/session.py','app/core/config.py','app/core/encryption.py','app/models/config.py','app/models/rag.py')


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(data):return hashlib.sha256(data).hexdigest()


def validate_payload(payload):
    require(set(payload)=={'protocol','mode','questions','documents','input_sha256','source_sha256','expected_snapshot','max_http_requests'}
            and payload['protocol']=='resume-query-embeddings-v1' and payload['mode'] in {'preflight','collect'},'向量协议或字段非法/gold泄漏')
    require(isinstance(payload['questions'],list) and len(payload['questions'])==24
            and len({q['id'] for q in payload['questions']})==24
            and all(set(q)=={'id','query'} and isinstance(q['query'],str) and 0<len(q['query'].strip())<=300 for q in payload['questions']),'仅允许冻结开发24题')
    require(len(payload['documents'])==4 and len({d['document_id'] for d in payload['documents']})==4
            and all(set(d)=={'document_id','document_sha256','title','source_url'} for d in payload['documents']),'文档清单非法')
    require(set(payload['source_sha256'])==set(SOURCE_PATHS),'业务源码白名单变化')
    require(type(payload['max_http_requests']) is int and payload['max_http_requests']==(0 if payload['mode']=='preflight' else 1),'预检0/收集1次HTTP预算')


def decode_response(data,count,dimension):
    require(isinstance(data,dict) and isinstance(data.get('model'),str) and bool(data['model'].strip()),'缺供应商响应模型')
    usage=data.get('usage')
    require(isinstance(usage,dict) and type(usage.get('prompt_tokens')) is int and usage['prompt_tokens']>=0,'缺原生输入usage，不填0')
    native={k:v for k,v in usage.items() if k.endswith('tokens') and type(v) is int and v>=0}
    items=data.get('data')
    require(isinstance(items,list) and len(items)==count and [x.get('index') for x in items]==list(range(count))
            and all(type(x.get('index')) is int for x in items),'向量索引缺失/重复/顺序变化')
    vectors=[];selected=[]
    for item in items:
        raw=item.get('embedding')
        if isinstance(raw,str):
            binary=base64.b64decode(raw,validate=True)
            require(len(binary)==dimension*4,'base64向量维度不同')
            vector=list(struct.unpack('<'+'f'*dimension,binary))
        else:vector=raw
        require(isinstance(vector,list) and len(vector)==dimension
                and all(type(v) in (int,float) and math.isfinite(v) for v in vector) and any(vector),'向量为空、非有限或维度不同')
        vectors.append(vector);selected.append({'index':item['index'],'embedding':raw})
    return vectors,{'model':data['model'],'usage':native,'data':selected}


def corpus_snapshot(rows,model):
    """绑定实际向量和分块内容，防止数量相同却换了索引而被当成同次实验。"""
    dimensions=set();selected=[]
    for row in rows:
        require(row['embedding_model']==model,'文档向量模型与当前配置不同，停止而不重建数据库')
        raw=row['embedding_json'];vector=json.loads(raw) if isinstance(raw,str) else raw
        require(isinstance(vector,list) and bool(vector)
                and all(type(v) in (int,float) and math.isfinite(v) for v in vector) and any(vector),'文档向量缺失/非法')
        dimensions.add(len(vector))
        selected.append({'id':str(row['id']),'document_id':str(row['document_id']),
                         'chunk_index':row['chunk_index'],'content_sha256':sha(row['content'].encode()),
                         'embedding_model':row['embedding_model'],'vector':vector})
    require(len(dimensions)==1 and bool(selected) and len({r['id'] for r in selected})==len(selected),'文档向量维度不一致/重复')
    selected.sort(key=lambda r:r['id'])
    return {'dimension':next(iter(dimensions)),'chunks':len(selected),
            'corpus_sha256':sha(json.dumps(selected,sort_keys=True,ensure_ascii=False,allow_nan=False).encode())}


class Observer:
    def __init__(self,budget,wire,origin):
        self.budget=budget;self.wire=wire;self.origin=origin;self.records=[]

    def before(self,request):
        require(len(self.records)<self.budget,'超向量预算或预检发生HTTP')
        body=json.loads(request.content)
        require(request.method=='POST' and request.url.path.endswith('/embeddings') and body==self.wire,'实际批量输入/模型/SDK编码与预注册不同')
        require(sha(json.dumps([request.url.scheme,request.url.host,request.url.port]).encode())==self.origin,'实际供应商端点变化')
        record={'wire_request':body,'request_sha256':sha(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()),
                'status_code':None,'raw_response':None,'native_usage':None,'response_error_type':None}
        self.records.append(record)
        print(json.dumps({'http_started':{k:record[k] for k in ('wire_request','request_sha256')}},ensure_ascii=False),flush=True)
        return record

    @staticmethod
    def after(record,response,count,dimension):
        record['status_code']=response.status_code
        try:
            require(response.status_code==200,'供应商HTTP非200')
            data=response.json()
            if isinstance(data,dict) and isinstance(data.get('usage'),dict):
                record['native_usage']={k:v for k,v in data['usage'].items() if k.endswith('tokens') and type(v) is int and v>=0}
            vectors,selected=decode_response(data,count,dimension)
            record['raw_response']=selected
            return vectors
        except Exception as exc:
            record['response_error_type']=type(exc).__name__;raise
        finally:
            print(json.dumps({'http_finished':record},ensure_ascii=False,allow_nan=False),flush=True)


async def run(payload):
    validate_payload(payload)
    import openai
    import httpx
    from openai import DefaultAsyncHttpxClient
    from openai.resources.embeddings import AsyncEmbeddings
    from sqlalchemy import text
    from app.db.session import async_session_maker,async_engine
    from app.services.embedding import EmbeddingService
    from app.services.text_privacy import redact_for_provider
    async_engine.echo=False;logging.disable(logging.CRITICAL)
    hashes={name:sha(Path(name).read_bytes()) for name in SOURCE_PATHS}
    require(hashes==payload['source_sha256'] and sys.byteorder=='little','容器源码或向量解码字节序不同')
    original_send=DefaultAsyncHttpxClient.send;forbidden=[];observer=None;native_vectors=None
    async def blocked(*args,**kwargs):forbidden.append(1);raise ValueError('禁止额外HTTP')
    async def send(client,request,*args,**kwargs):
        nonlocal native_vectors
        record=observer.before(request)
        response=await original_send(client,request,*args,**kwargs)
        native_vectors=observer.after(record,response,24,snapshot['dimension'])
        return response
    with patch.object(httpx.AsyncClient,'send',blocked),patch.object(DefaultAsyncHttpxClient,'send',send):
        async with async_session_maker() as db:
            await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            require((await db.execute(text('SHOW transaction_read_only'))).scalar()=='on','事务非只读')
            settings_sql="SELECT key,value FROM system_settings WHERE key IN ('interview_demo.enabled','interview_demo.limit','interview_demo.used')"
            before=dict((await db.execute(text(settings_sql))).all())
            require(before.get('interview_demo.enabled','false')=='false','演示保护开启，停止而不改配置')
            docs={str(d['id']):dict(d) for d in (await db.execute(text("SELECT id,title,content,source_url,embedding_model FROM documents WHERE is_active AND doc_type='platform_guideline'"))).mappings()}
            require(set(docs)=={d['document_id'] for d in payload['documents']},'当前语料范围不同')
            for d in payload['documents']:
                actual=docs[d['document_id']]
                require(sha(actual['content'].encode())==d['document_sha256'] and actual['title']==d['title'] and actual['source_url']==d['source_url'],'语料原文/出处变化')
            service=EmbeddingService(db);client=await service._get_client()
            try:
                require(type(client._client) is DefaultAsyncHttpxClient,'SDK传输实现不同，不能漏计HTTP')
                client.max_retries=0;client._client.follow_redirects=False
                chunk_rows=(await db.execute(text("SELECT c.id,c.document_id,c.chunk_index,c.content,c.embedding_json,d.embedding_model FROM document_chunks c JOIN documents d ON d.id=c.document_id WHERE d.is_active AND d.doc_type='platform_guideline'"))).mappings().all()
                corpus=corpus_snapshot(chunk_rows,service._model)
                origin=sha(json.dumps([client.base_url.scheme,client.base_url.host,client.base_url.port]).encode())
                snapshot={'model':service._model,**corpus,'sdk_retries':0,
                          'follow_redirects':False,'timeout_seconds':30,'encoding_format':'base64','openai_version':openai.__version__,
                          'sdk_create_sha256':sha(inspect.getsource(AsyncEmbeddings.create).encode()),
                          'endpoint_sha256':sha(str(client.base_url).encode()),'origin_sha256':origin}
                require('params["encoding_format"] = "base64"' in inspect.getsource(AsyncEmbeddings.create),'SDK默认编码变化，需重新核对实际请求')
                wire={'model':service._model,'input':redact_for_provider([q['query'] for q in payload['questions']]),'encoding_format':'base64'}
                observer=Observer(payload['max_http_requests'],wire,origin)
                vectors=[];status='success';error_type=None;tick=time.perf_counter()
                if payload['mode']=='collect':
                    require(snapshot==payload['expected_snapshot'],'模型/语料向量/SDK与预检不同')
                    try:
                        vectors=await asyncio.wait_for(service.embed([q['query'] for q in payload['questions']]),timeout=35)
                        require(len(observer.records)==1 and vectors==native_vectors,'实际请求次数或SDK解码结果与原生响应不同')
                    except Exception as exc:status='error';error_type=type(exc).__name__
                elapsed=round((time.perf_counter()-tick)*1000,3)
                after=dict((await db.execute(text(settings_sql))).all());await db.rollback()
            finally:await client.close()
        async with async_session_maker() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'));outside=dict((await db.execute(text(settings_sql))).all());await db.rollback()
    require(before==after==outside and not forbidden,'只读/保护设置或额外网络变化')
    return {'protocol':payload['protocol'],'mode':payload['mode'],'input_sha256':payload['input_sha256'],'source_sha256':hashes,
            'model_snapshot':snapshot,'wire_request':wire,'questions':payload['questions'],'vectors':vectors,'requests':observer.records,
            'status':status,'error_type':error_type,'elapsed_ms':elapsed,'read_only':True,'rolled_back':True,'read_gold':False,
            'settings_before':before,'settings_after':outside,'settings_unchanged':True,'forbidden_http_attempts':len(forbidden),
            'complete':status=='success' and (len(vectors)==24 if payload['mode']=='collect' else not vectors and not observer.records)}
