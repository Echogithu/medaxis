"""在冻结语料副本上运行原RAG源码和SQL；无网络调用，不冒充在线基线。"""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time
import shutil
import platform
from importlib.metadata import version
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from build import read,digest,validate
from score import score,summarize


class Rows:
    def __init__(self,rows): self.rows=rows
    def all(self): return self.rows
    def scalars(self): return self
    def first(self): return self.rows[0] if self.rows else None


class SnapshotDb:
    def __init__(self,corpus):
        self.connection=sqlite3.connect(':memory:')
        self.connection.row_factory=sqlite3.Row
        self.connection.execute('CREATE TABLE documents (id TEXT,title TEXT,doc_type TEXT,source_url TEXT,is_active INTEGER)')
        self.connection.execute('CREATE TABLE document_chunks (id TEXT,document_id TEXT,chunk_index INTEGER,content TEXT,embedding_json TEXT)')
        self.connection.executemany('INSERT INTO documents VALUES (?,?,?,?,?)',
            [(d['id'],d['title'],'platform_guideline',d['source_url'],1) for d in corpus['documents']])
        self.connection.executemany('INSERT INTO document_chunks VALUES (?,?,?,?,?)',
            [(c['id'],c['document_id'],c['chunk_index'],c['content'],json.dumps(c['embedding_json'])) for c in corpus['chunks']])
        self.coarse_ids=[]
    async def execute(self,statement):
        from sqlalchemy.dialects.sqlite import dialect
        from app.models.rag import DocType
        compiled=statement.compile(dialect=dialect())
        if 'llm_provider_configs' in str(compiled):
            return Rows([])
        if 'document_chunks' not in str(compiled):
            raise ValueError('离线副本禁止查询其他表')
        params=[compiled.params[n] for n in compiled.positiontup]
        params=[p.value if isinstance(p,DocType) else p for p in params]
        raw=self.connection.execute(str(compiled),params).fetchall()
        rows=[]
        for r in raw:
            fields=dict(r)
            fields['doc_type']=DocType(fields['doc_type'])
            rows.append(SimpleNamespace(**fields))
        self.coarse_ids=[str(r.id) for r in rows]
        return Rows(rows)


async def execute(args):
    frozen=args.frozen.resolve()
    corpus=read(frozen/'corpus.json')
    dataset=read(frozen/'dataset.json')
    if dataset['snapshot_sha256']!=digest(frozen/'corpus.json'):
        raise ValueError('语料与题库指纹不一致')
    validate(corpus,dataset)
    for name,value in corpus['source_sha256'].items():
        if digest(frozen/'source'/name)!=value:
            raise ValueError('冻结源码已改变')
    if any(p['model_type']=='reranking' for p in corpus['providers']):
        raise ValueError('该离线入口尚不支持重排供应商响应重放，不能伪装缺少供应商')
    sys.path.insert(0,str(frozen/'source'))
    os.environ['SECRET_KEY']='synthetic-evaluation-not-a-secret'
    os.environ['DATABASE_URL']='postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic_import_only'
    os.environ['ASYNC_DATABASE_URL']=os.environ['DATABASE_URL']
    from app.services import rag as module
    from app.services.embedding import EmbeddingService
    from app.services.knowledge_citations import build_knowledge_citations,rank_knowledge_citations
    from app.models.rag import DocType
    from sqlalchemy import event
    from app.db.session import async_engine
    @event.listens_for(async_engine.sync_engine,'do_connect')
    def block_connect(*_args):
        raise AssertionError('离线重放禁止实际数据库连接')
    logging.disable(logging.CRITICAL)
    vectors=None
    if args.embeddings:
        artifact=read(args.embeddings)
        if artifact['mode']!='real_provider_query_embeddings' or len(artifact['queries'])!=len(artifact['vectors']):
            raise ValueError('缺少完整真实查询向量')
        vectors=dict(zip(artifact['queries'],artifact['vectors']))
        expected={d['embedding_model'] for d in corpus['documents']}
        models={c['model'] for c in artifact['calls']}
        if models!=expected:
            raise ValueError('查询向量模型与文档向量不同')
        import math
        dimensions={len(c['embedding_json']) for c in corpus['chunks']}
        if len(dimensions)!=1 or any(len(v) not in dimensions or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v) for v in vectors.values()):
            raise ValueError('向量维度或数值不兼容')
    async def embed(_self,queries):
        if vectors is None:
            raise ValueError('explicit_offline_no_query_embedding')
        return [vectors[q] for q in queries]
    cases=dataset['cases']
    if args.ids:
        wanted=set(args.ids.split(','))
        if not wanted<={c['id'] for c in cases}:
            raise ValueError('冒烟题目不存在')
        cases=[c for c in cases if c['id'] in wanted]
    args.output.mkdir(parents=True,exist_ok=False)
    docs={d['id']:d for d in corpus['documents']}
    chunks={c['id']:c for c in corpus['chunks']}
    units={u['id']:u for u in dataset['gold_units']}
    rows=[]
    db=SnapshotDb(corpus)
    config=corpus['policy']
    with patch.object(EmbeddingService,'embed',embed), patch.object(module.settings,'rag_coarse_multiplier',config['coarse_multiplier']), \
         patch.object(module.settings,'rag_coarse_min',config['coarse_min']),patch.object(module.settings,'rag_query_term_length',config['query_term_length']):
        for case in cases:
            begin=time.perf_counter()
            try:
                retrieved=await module.RAGService(db).search(case['query'],doc_type=DocType.PLATFORM_GUIDELINE,top_k=config['internal_candidates'])
                candidates=build_knowledge_citations([{'source_type':'internal','title':r['document_title'],'document_id':r['document_id'],
                              'chunk_id':r['chunk_id'],'chunk_index':r['chunk_index'],'excerpt':r['content']} for r in retrieved])
                selected=(await rank_knowledge_citations(case['query'],candidates,db,min_relevance=config['min_relevance']))[:config['report_limit']]
                sources=[]
                for c in selected:
                    original=chunks[c.chunk_id]
                    local=original['content'].find(c.excerpt)
                    if local<0: raise ValueError('选中摘录不在真实片段中')
                    start=original['start']+local
                    sources.append({'document_id':c.document_id,'chunk_id':c.chunk_id,'start':start,'end':start+len(c.excerpt),
                                    'excerpt':c.excerpt,'relevance':c.relevance,'method':c.relevance_method})
                row={'id':case['id'],'split':case['split'],'family':case['family'],'status':'success',
                     'coarse_chunk_ids':db.coarse_ids[:],'internal_chunk_ids':[r['chunk_id'] for r in retrieved],
                     'sources':sources,'score':score(case,units,sources,docs)}
            except Exception as exc:
                row={'id':case['id'],'status':'failed','error_type':type(exc).__name__}
            row['offline_replay_ms']=round((time.perf_counter()-begin)*1000,2)
            rows.append(row)
    db.connection.close()
    groups={}
    for field in ('split','family'):
        groups[field]={}
        for value in sorted({c[field] for c in cases}):
            subset=[c for c in cases if c[field]==value]
            keys={c['id'] for c in subset}
            groups[field][value]=summarize(subset,[r for r in rows if r['id'] in keys])
    executor_dir=args.output/'executor'
    executor_dir.mkdir()
    executor_hashes={}
    for name in ('build.py','score.py','replay.py','collect.py','topics.json'):
        source=Path(__file__).with_name(name)
        shutil.copyfile(source,executor_dir/name)
        executor_hashes[name]=digest(source)
    if vectors is not None:
        shutil.copyfile(args.embeddings,args.output/'query-embeddings.json')
    result={'mode':'frozen_sqlite_original_code_real_vector_replay' if vectors is not None else 'frozen_sqlite_original_code_keyword_fallback_diagnostic',
            'recorded_at':datetime.now(timezone.utc).isoformat(),
            'environment':{'python':platform.python_version(),'packages':{n:version(n) for n in ('sqlalchemy','pydantic','openai','numpy')}},
            'executor_sha256':executor_hashes,'groups':groups,'k':config['report_limit'],
            'dataset_sha256':digest(frozen/'dataset.json'),'corpus_sha256':digest(frozen/'corpus.json'),
            'source_sha256':corpus['source_sha256'],'query_embeddings_sha256':digest(args.embeddings) if args.embeddings else None,
            'runner_sha256':digest(Path(__file__)),'scorer_sha256':digest(Path(__file__).with_name('score.py')),
            'cases':rows,'summary':summarize(cases,rows),'metrics_status':'provisional_gold_not_clinically_reviewed',
            'production_latency_ms':None,'provider_usage':artifact['calls'] if vectors is not None else None,'online_baseline_complete':False}
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    by_case={c['id']:c for c in cases}
    report=['# 冻结语料检索诊断','',f"模式：{result['mode']}",'',
            '不是在线完整基线。使用冻结语料SQLite副本、原检索源码；无查询向量时显式禁用向量排序，不能称为当前生产效果。',
            'gold为AI草稿；以下指标仅供诊断，不是医学正确率。','', '```json',json.dumps(result['summary'],ensure_ascii=False,indent=2),'```','',
            'Hit表示摘录与必需证据有任意字符重叠；完整证据Recall要求原文范围无缺口覆盖。MRR按首个重叠来源排名，非专业相关性分级。',
            '无答案候选返回率只统计来源候选，未运行诊断报告，不等于错误诊断或错误成功率。','',
            '分组指标见results.json的groups，开发集与验收集按证据主题隔离。','',
            '| ID | 类型 | 命中 | 完整证据Recall | 限定词覆盖 | 来源数 |','|---|---|---|---|---|---|']
    for r in rows:
        s=r.get('score',{})
        report.append(f"| {r['id']} | {by_case[r['id']]['family']} | {s.get('hit_at_k')} | {s.get('evidence_recall_at_k')} | {s.get('qualifier_recall')} | {len(r.get('sources',[]))} |")
    (args.output/'REPORT.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(json.dumps({'mode':result['mode'],**result['summary']},ensure_ascii=False))
    return 0 if result['summary']['status']=='complete_diagnostic' else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frozen',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--embeddings',type=Path)
    p.add_argument('--ids')
    args=p.parse_args()
    try: return asyncio.run(execute(args))
    except (ValueError,OSError,KeyError) as exc:
        print(f'评测拒绝：{exc}',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
