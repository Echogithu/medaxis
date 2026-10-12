"""只读核对现有数据库关系，验证定位候选；不运行新检索或问诊。"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = '''
import asyncio,hashlib,json,logging,uuid
from sqlalchemy import select,text
from unittest.mock import AsyncMock,patch
import httpx
from app.db.session import async_session_maker,async_engine
from app.models.rag import Document,DocumentChunk
from app.services.rag_context import select_context
import app.services.rag_context as context_module
async def main():
    async_engine.echo=False
    logging.disable(logging.CRITICAL)
    network=AsyncMock(side_effect=AssertionError('禁止外部调用'))
    corpus=payload['corpus']
    documents={d['id']:d for d in corpus['documents']}
    chunks={c['id']:c for c in corpus['chunks']}
    async with async_session_maker() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        with patch.object(httpx.AsyncClient,'send',network):
            docs=(await db.execute(select(Document.id,Document.title,Document.content,Document.source_url,Document.is_active).where(Document.id.in_([uuid.UUID(x) for x in documents])))).all()
            actual=(await db.execute(select(DocumentChunk.id,DocumentChunk.document_id,DocumentChunk.chunk_index,DocumentChunk.content).where(DocumentChunk.document_id.in_([uuid.UUID(x) for x in documents])))).all()
            if len(docs)!=len(documents) or len(actual)!=len(chunks):raise ValueError('文档或片段数量漂移')
            for d in docs:
                old=documents[str(d.id)]
                if not d.is_active or any(getattr(d,key)!=old[key] for key in ('title','content','source_url')):raise ValueError('文档原文或出处漂移')
            siblings=[]
            for c in actual:
                old=chunks[str(c.id)]
                if str(c.document_id)!=old['document_id'] or c.chunk_index!=old['chunk_index'] or c.content!=old['content']:raise ValueError('片段漂移')
                siblings.append({'chunk_id':str(c.id),'document_id':str(c.document_id),'chunk_index':c.chunk_index,'content':c.content})
            rows=[]
            for c in siblings:
                document=documents[c['document_id']]['content']
                result=select_context('',c,document,siblings)
                if result:
                    excerpt,meta=result
                    if excerpt!=document[meta['start']:meta['end']] or c['content'].strip() not in excerpt or len(excerpt)>1600:raise ValueError('上下文或锚点定位错误')
                    rows.append({'chunk_id':c['chunk_id'],'status':'located','metadata':meta,'excerpt_chars':len(excerpt)})
                else:rows.append({'chunk_id':c['chunk_id'],'status':'fallback_required'})
        await db.rollback()
    if network.call_count:raise ValueError('发生网络尝试')
    print(json.dumps({'mode':'postgres_metadata_inspection','documents':len(docs),'chunks':len(actual),'source_url_missing':sum(d.source_url is None for d in docs),'rows':rows,'read_only':True,'rolled_back':True,'network_attempts':network.call_count,'provider_calls':0,'retrieval_executed':False,'api_feature_enabled':None,'executed_context_sha256':hashlib.sha256(open(context_module.__file__,'rb').read()).hexdigest()},ensure_ascii=False))
asyncio.run(main())
'''


def main(args):
    frozen = ROOT / '.ai/tasks/2026-10-07-rag-baseline/frozen-v1/corpus.json'
    code = "import base64,json\npayload=json.loads(base64.b64decode(" + repr(base64.b64encode(
        json.dumps({'corpus': json.loads(frozen.read_text(encoding='utf-8'))}, ensure_ascii=False).encode()
    ).decode()) + "))\n" + PROGRAM
    actual = subprocess.run(['docker', 'exec', '-i', '-w', '/app', 'medaxis-backend', 'python', '-'],
                            input=code, capture_output=True, text=True, encoding='utf-8')
    args.output.mkdir(parents=True, exist_ok=False)
    execution = {'exit_code': actual.returncode, 'stderr': actual.stderr,
                 'corpus_sha256': hashlib.sha256(frozen.read_bytes()).hexdigest(),
                 'context_code_sha256': hashlib.sha256((ROOT/'backend/app/services/rag_context.py').read_bytes()).hexdigest()}
    (args.output/'execution.json').write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding='utf-8')
    if actual.returncode:
        raise RuntimeError('数据库核对失败；见execution.json')
    result = json.loads(actual.stdout)
    if result['executed_context_sha256'] != execution['context_code_sha256']:
        raise ValueError('容器与本地上下文源码不同')
    (args.output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output/'inspect_metadata.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
