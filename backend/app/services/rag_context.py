"""用已有片段关系补可核对的原文；定位歧义回退，禁止读取gold挑窗口。"""
from __future__ import annotations

import hashlib
import re
from typing import Any

def select_context(query: str, anchor: dict[str, Any], document: str,
                   siblings: list[dict[str, Any]], *, max_chars: int = 1600, margin: int = 300):
    """返回连续原文与定位元信息；定位不唯一时让调用端保留原来源。"""
    del query  # 接口保留query，但此版本只用元信息，避免查询窗口替换命中内容。
    if margin < 0:
        return None
    max_chars = min(max_chars, 1600)
    body=anchor['content']
    if not body or max_chars<=0 or len(body)>max_chars or document.count(body)!=1:
        return None
    start=document.index(body);end=start+len(body)
    ranges=[]
    for chunk in siblings:
        if chunk['document_id']!=anchor['document_id'] or abs(chunk['chunk_index']-anchor['chunk_index'])>1:
            continue
        content=chunk['content']
        if not content or document.count(content)!=1:
            continue
        position=document.index(content)
        ranges.append((position,position+len(content),chunk['chunk_id']))
    if not any(chunk['chunk_id']==anchor['chunk_id'] and
               all(chunk[key]==anchor[key] for key in ('document_id','chunk_index','content'))
               for chunk in siblings):
        return None
    # 只补已核对的相邻片段，不让有缺口的邻接关系跨越未知原文。
    ordered=sorted(ranges)
    left,right=start,end
    for a,b,_cid in ordered:
        if a<=start<=b:left=min(left,a)
        if a<=end<=b:right=max(right,b)
    padding=min(margin,max(0,(max_chars-len(body))//2))
    left=max(left,start-padding);right=min(right,end+padding)
    # 标点/行边界只用于选窗口，不能当作医学条件完整性的判定。
    boundaries=sorted({left+m.end() for m in re.finditer(r'[。！？!?]|\.(?!\d)|\n+',document[left:right])})
    # 截取补充部分时不切掉整个命中chunk；query不用于挑选或猜测gold位置。
    a=next((value for value in boundaries if value>=left and value<=start),start)
    b=next((value for value in reversed(boundaries) if end<=value<=right),end)
    raw=document[a:b]
    a+=len(raw)-len(raw.lstrip());b=a+len(raw.strip())
    if a>=b:return None
    covered=list(dict.fromkeys(cid for x,y,cid in ordered if max(x,a)<min(y,b)))
    return document[a:b],{'anchor_chunk_id':anchor['chunk_id'],'document_id':anchor['document_id'],
            'start':a,'end':b,'chunk_ids':covered,'source_text_sha256':hashlib.sha256(document.encode()).hexdigest(),
            'method':'anchor_neighbors',
            'max_chars':max_chars}


async def expand_retrieved_contexts(db, query: str, chunks: list[dict[str, Any]]):
    """批量只读加载命中文档及index±1；失败时原始来源保留，savepoint隔离查询失败。"""
    import logging
    import uuid
    from sqlalchemy import and_, or_, select
    from sqlalchemy.exc import SQLAlchemyError
    from app.models.rag import Document, DocumentChunk

    targets = {}
    for chunk in chunks:
        try:
            doc_id = uuid.UUID(chunk['document_id'])
            uuid.UUID(chunk['chunk_id'])
            index = chunk['chunk_index']
            if type(index) is not int or index < 0:
                continue
            targets.setdefault(doc_id, set()).update(range(max(0, index-1), index+2))
        except (ValueError, KeyError, TypeError):
            continue
    if not targets:
        return chunks
    try:
        async with db.begin_nested():
            documents = (await db.execute(select(Document.id, Document.content, Document.title,
                Document.source_url, Document.doc_type).where(Document.id.in_(targets), Document.is_active == True))).all()
            found = {str(row.id): row for row in documents}
            conditions = [and_(DocumentChunk.document_id == doc_id, DocumentChunk.chunk_index.in_(indices))
                          for doc_id, indices in targets.items() if str(doc_id) in found]
            if not conditions:
                return chunks
            neighbors = (await db.execute(select(DocumentChunk.id, DocumentChunk.document_id,
                DocumentChunk.chunk_index, DocumentChunk.content).where(or_(*conditions)))).all()
        siblings = [{'chunk_id':str(row.id),'document_id':str(row.document_id),
                     'chunk_index':row.chunk_index,'content':row.content} for row in neighbors]
        by_id = {row['chunk_id']:row for row in siblings}
        expanded = []
        for chunk in chunks:
            document = found.get(chunk.get('document_id'))
            anchor = by_id.get(chunk.get('chunk_id'))
            result = None
            if (document and anchor and all(anchor[k] == chunk.get(k) for k in ('document_id','chunk_index','content'))
                and document.title == chunk.get('document_title') and document.source_url == chunk.get('source_url')
                and document.doc_type.value == chunk.get('document_type')):
                result = select_context(query, anchor, document.content, siblings)
            expanded.append({**chunk, 'content': result[0], 'context_metadata': result[1]} if result else chunk)
        return expanded
    except SQLAlchemyError as exc:
        logging.getLogger(__name__).warning('原文上下文加载失败，保留原始来源：%s',type(exc).__name__)
        return chunks
