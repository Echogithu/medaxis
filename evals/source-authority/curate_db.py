"""4行参数化条件更新，同事务校验除source_url外的全量知识数据未变。"""
import hashlib
import json
from sqlalchemy import text
from app.db.session import async_session_maker,async_engine


async def fingerprint(db):
    # 不向日志输出其它知识正文，仅记录所有字段的哈希。
    documents=(await db.execute(text("SELECT id::text,to_jsonb(d)::text AS value FROM documents d ORDER BY id"))).mappings().all()
    chunks=(await db.execute(text("SELECT to_jsonb(c)::text AS value FROM document_chunks c ORDER BY id"))).scalars().all()
    rows={r['id']:json.loads(r['value']) for r in documents}
    return rows,hashlib.sha256(json.dumps(chunks,sort_keys=True).encode()).hexdigest(),len(chunks)


async def run(payload):
    async_engine.echo=False
    async with async_session_maker() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        if not payload['apply']:await db.execute(text('SET TRANSACTION READ ONLY'))
        for r in payload['rows']:
            suffix=' FOR UPDATE' if payload['apply'] else ''
            doc=(await db.execute(text('SELECT title,content,source_url,is_active,doc_type FROM documents WHERE id=CAST(:id AS uuid)'+suffix),
                                  {'id':r['document_id']})).mappings().one()
            if (doc['source_url']!=r['old_source_url'] or doc['title']!=r['title'] or not doc['is_active']
                or doc['doc_type']!='platform_guideline' or hashlib.sha256(doc['content'].encode()).hexdigest()!=r['content_sha256']):
                raise ValueError('数据库旧值或正文漂移，停止更新')
        before,chunk_hash,count=await fingerprint(db)
        if payload['apply']:
            for r in payload['rows']:
                updated=await db.execute(text('UPDATE documents SET source_url=:url WHERE id=CAST(:id AS uuid) AND source_url IS NOT DISTINCT FROM :old'),
                    {'id':r['document_id'],'url':r['new_source_url'],'old':r['old_source_url']})
                if updated.rowcount!=1:raise ValueError('条件更新行数不同')
        after,after_chunk_hash,after_count=await fingerprint(db)
        expected=json.loads(json.dumps(before))
        if payload['apply']:
            for r in payload['rows']:expected[r['document_id']]['source_url']=r['new_source_url']
        if after!=expected or chunk_hash!=after_chunk_hash or count!=after_count:raise ValueError('发生计划外数据变更，事务回滚')
        receipt={'mode':'apply' if payload['apply'] else 'dry_run','rows':payload['rows'],'changed_fields':['source_url'] if payload['apply'] else [],
            'updated_rows':4 if payload['apply'] else 0,'all_document_other_fields_unchanged':True,'all_chunks_unchanged':True,
            'chunk_count':count,'chunk_rows_sha256':chunk_hash,'transaction_committed':payload['apply']}
        if payload['apply']:await db.commit()
        else:await db.rollback()
        return receipt
