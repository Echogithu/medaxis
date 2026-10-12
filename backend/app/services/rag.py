"""RAG (Retrieval-Augmented Generation) service.

关键词召回和同模型向量语义召回独立执行，候选并集使用共同语义量尺并可选重排。
当前对JSON向量流式精确扫描；大语料的向量索引仍待单独建设。

SearXNG integration planned for real-time external knowledge retrieval.
"""

import heapq
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.rag import Document, DocumentChunk, DocType
from app.services.embedding import EmbeddingService
from app.services.llm import LLMService
from app.services.reranker import RerankerService

settings = get_settings()

# Simple chunking strategy: split by paragraphs, configurable via env
_CHUNK_SIZE = settings.rag_chunk_size
_CHUNK_OVERLAP = settings.rag_chunk_overlap
_MAX_COARSE_TERMS = 32


def _safe_similarity(query_vector: list[float], stored_vector: Any) -> float | None:
    """坏向量、不同维度或零向量不参与语义召回。"""
    try:
        vector = json.loads(stored_vector) if isinstance(stored_vector, str) else stored_vector
        if not isinstance(vector, (list, tuple)) or len(vector) != len(query_vector):
            return None
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in vector) or not any(vector):
            return None
        value = EmbeddingService.cosine_similarity(query_vector, vector)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _coarse_search_terms(query: str, term_len: int) -> list[str]:
    """覆盖整句中的中文症状词，避免只按开头词筛选片段。"""
    short_terms: list[str] = []
    long_terms: list[str] = []
    width = min(max(term_len, 2), 4)
    for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", query):
        if "\u4e00" <= part[0] <= "\u9fff":
            short_terms.extend(part[i:i + 2] for i in range(len(part) - 1))
            if len(part) >= width and width > 2:
                long_terms.extend(part[i:i + width] for i in range(len(part) - width + 1))
        elif len(part) >= 2:
            short_terms.append(part)

    short_terms = list(dict.fromkeys(short_terms))
    if not short_terms:
        return [query.strip()] if query.strip() else []
    if len(short_terms) >= _MAX_COARSE_TERMS:
        last = len(short_terms) - 1
        return [
            short_terms[round(i * last / (_MAX_COARSE_TERMS - 1))]
            for i in range(_MAX_COARSE_TERMS)
        ]
    return list(dict.fromkeys(short_terms + long_terms))[:_MAX_COARSE_TERMS]


def _reserve_keyword_candidate(query, vector_top, keyword_rows, similarities, top_k):
    """最多保留一个具体词命中席位；原始余弦分、首位语义结果和预算不变。"""
    from app.services.knowledge_citations import _specific_query_terms

    if top_k < 2 or not keyword_rows:
        return vector_top
    terms = _specific_query_terms(query)
    # 连续具体短语比零碎bigram更可靠；通用词不参与组成4字短语。
    phrases = {part for part in re.findall(r"[a-z][a-z0-9-]{3,}", query.casefold()) if part in terms}
    for part in re.findall(r"[\u4e00-\u9fff]+", query):
        phrases.update(part[i:i + 4] for i in range(len(part) - 3)
                       if all(part[j:j + 2] in terms for j in range(i, i + 3)))
    pool = {str(row.id): row for _, row in vector_top}
    pool.update({str(row.id): row for row in keyword_rows})
    if len(terms) < 2:
        return vector_top
    texts = {key: row.content.casefold() for key, row in pool.items()}
    weights = {term: math.log((len(pool) + 1) / (1 + sum(term in value for value in texts.values())))
               for term in terms}
    ranked = []
    for row in keyword_rows:
        matched = [term for term in terms if term in texts[str(row.id)]]
        if len(matched) >= 2 and any(phrase in texts[str(row.id)] for phrase in phrases):
            ranked.append((sum(weights[term] for term in matched), str(row.id), row))
    if not ranked:
        return vector_top
    weight, key, row = sorted(ranked, key=lambda item: (-item[0], item[1]))[0]
    if weight <= 0 or key in {str(r.id) for _, r in vector_top[:top_k]}:
        return vector_top
    # 权重仅用于候选保护，绝不写成语义相关分；不同模型仍沿用0分降级。
    similarity = similarities.get(key)
    reserved = (similarity if similarity is not None else 0., row)
    remaining = [item for item in vector_top if str(item[1].id) != key]
    position = min(top_k - 1, len(remaining))
    return (remaining[:position] + [reserved] + remaining[position:])[:top_k * 2]


class RAGService:
    """Retrieval-Augmented Generation service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _semantic_candidates(self, stmt, query_vector: list[float], model: str, limit: int):
        """独立扫描同模型向量；流式读取，仅保留top候选，避免关键词漏召回。"""
        stmt = stmt.where(DocumentChunk.embedding_json.is_not(None), Document.embedding_model == model)
        result = await self.db.stream(stmt.execution_options(yield_per=64))
        heap = []
        try:
            async for batch in result.partitions(64):
                for row in batch:
                    similarity = _safe_similarity(query_vector, row.embedding_json)
                    if similarity is None:
                        continue
                    item = (similarity, -uuid.UUID(str(row.id)).int, row)
                    if len(heap) < limit:
                        heapq.heappush(heap, item)
                    elif item[:2] > heap[0][:2]:
                        heapq.heapreplace(heap, item)
        finally:
            await result.close()
        return [(value, row) for value, _tie, row in sorted(heap, reverse=True)]

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
        """Split text into overlapping chunks."""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end < len(text):
                search_start = max(start, end - 100)
                for i in range(end, search_start, -1):
                    if text[i] in "\n\u3002\uff01\uff1f.!？":
                        end = i + 1
                        break
            chunks.append(text[start:end])
            start = end - overlap
            if start >= len(text):
                break
        return chunks

    async def create_document(
        self,
        title: str,
        content: str,
        doc_type: DocType = DocType.PLATFORM_GUIDELINE,
        source_url: str | None = None,
        department: str | None = None,
        disease_tags: list[str] | None = None,
        drug_name: str | None = None,
        language: str = "zh",
    ) -> Document:
        """Create a document with auto-chunking."""
        doc = Document(
            title=title,
            doc_type=doc_type,
            content=content,
            source_url=source_url,
            department=department,
            disease_tags=disease_tags or [],
            drug_name=drug_name,
            language=language,
        )
        self.db.add(doc)
        await self.db.flush()

        # Generate tsvector for full document (kept for future use)
        await self.db.execute(
            text(
                "UPDATE documents SET search_vector = "
                "to_tsvector(:lang, :content) WHERE id = :id"
            ),
            {"lang": "simple" if language == "zh" else "english",
             "content": content, "id": str(doc.id)},
        )

        chunks_texts = self._chunk_text(content)
        chunk_objs: list[DocumentChunk] = []
        for idx, chunk_text in enumerate(chunks_texts):
            chunk = DocumentChunk(
                document_id=doc.id,
                content=chunk_text,
                chunk_index=idx,
            )
            self.db.add(chunk)
            await self.db.flush()
            chunk_objs.append(chunk)

            await self.db.execute(
                text(
                    "UPDATE document_chunks SET search_vector = "
                    "to_tsvector(:lang, :content) WHERE id = :id"
                ),
                {"lang": "simple" if language == "zh" else "english",
                 "content": chunk_text, "id": str(chunk.id)},
            )

        # Vectorize chunks asynchronously
        try:
            embed_svc = EmbeddingService(self.db)
            chunk_texts = [c.content for c in chunk_objs]
            embeddings = await embed_svc.embed(chunk_texts)
            for chunk_obj, emb in zip(chunk_objs, embeddings):
                await self.db.execute(
                    text(
                        "UPDATE document_chunks SET embedding_json = :emb WHERE id = :id"
                    ),
                    {"emb": str(emb), "id": str(chunk_obj.id)},
                )
            doc.vectorized_at = datetime.now(timezone.utc)
            doc.embedding_model = embed_svc._model or "unknown"
        except ValueError:
            # Embedding provider not configured — skip silently, keep doc usable
            pass

        doc.chunk_count = len(chunk_objs)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def search(
        self,
        query: str,
        doc_type: DocType | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Semantic search: hybrid keyword + vector similarity + rerank.

        Phase 1: independent keyword and same-model semantic candidates
        Phase 2: same-model cosine ordering of candidate union, retain 2*top_k
        Phase 3: optional reranker, with candidates preserved on failure
        """
        if top_k <= 0:
            return []
        # Phase 1: coarse keyword retrieval (expand to configurable multiplier for re-ranking)
        coarse_k = max(top_k * settings.rag_coarse_multiplier, settings.rag_coarse_min)
        search_terms = _coarse_search_terms(query, settings.rag_query_term_length)
        if not search_terms:
            return []
        matches = [DocumentChunk.content.ilike(f"%{term}%") for term in search_terms]
        overlap_score = sum(case((match, 1), else_=0) for match in matches)

        base_stmt = select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.chunk_index,
            DocumentChunk.embedding_json,
            Document.id.label("doc_id"),
            Document.title,
            Document.doc_type,
            Document.source_url,
            Document.embedding_model,
        ).join(Document).where(Document.is_active == True)

        if doc_type:
            base_stmt = base_stmt.where(Document.doc_type == doc_type)

        stmt = base_stmt.where(or_(*matches)).order_by(overlap_score.desc(), DocumentChunk.id).limit(coarse_k)
        result = await self.db.execute(stmt)
        rows = result.all()

        # 语义候选独立于关键词候选，空关键词结果也继续尝试语义召回。
        retrieval_metadata = {}
        try:
            embed_svc = EmbeddingService(self.db)
            try:
                query_emb = (await embed_svc.embed([query]))[0]
            finally:
                if embed_svc._client is not None:
                    await embed_svc._client.close()
            if not query_emb or any(type(v) not in (int, float) or not math.isfinite(v) for v in query_emb) or not any(query_emb):
                raise ValueError("Invalid query embedding")
            semantic = await self._semantic_candidates(base_stmt, query_emb, embed_svc._model, coarse_k) if embed_svc._model else []
            if semantic:
                candidates = {str(r.id): r for r in rows}
                similarities = {str(r.id): _safe_similarity(query_emb, r.embedding_json)
                                for r in rows if r.embedding_model == embed_svc._model}
                for similarity, row in semantic:
                    key = str(row.id)
                    candidates[key] = row
                    similarities[key] = similarity
                # 两路命中不额外加分，避免宽泛关键词挤掉正确的跨语言原文。
                # 未向量化/不同模型的关键词来源只补充空位，不伪造可比较的向量分数。
                keys = sorted(candidates, key=lambda key: (
                    similarities.get(key) is None,
                    -(similarities[key] if similarities.get(key) is not None else 0.), key))[:top_k * 2]
                vector_top = [(similarities[key] if similarities.get(key) is not None else 0., candidates[key]) for key in keys]
                vector_top = _reserve_keyword_candidate(query, vector_top, rows, similarities, top_k)
            else:
                scored = [(_safe_similarity(query_emb, r.embedding_json) or 0., r)
                          if not embed_svc._model or r.embedding_model == embed_svc._model else (0., r) for r in rows]
                scored.sort(key=lambda item: item[0], reverse=True)
                vector_top = scored[:top_k * 2]
            if embed_svc._model:
                for _, row in vector_top:
                    similarity = _safe_similarity(query_emb, row.embedding_json) if row.embedding_model == embed_svc._model else None
                    if similarity is not None:
                        retrieval_metadata[str(row.id)] = {
                            "retrieval_method": "embedding_cosine", "retrieval_model": embed_svc._model,
                            "retrieval_dimension": len(query_emb), "retrieval_score": similarity,
                            "retrieval_query_fingerprint": hashlib.sha256(query.strip()[:512].encode()).hexdigest(),
                            "retrieval_anchor_excerpt": row.content.strip()[:800],
                        }
        except ValueError:
            # Embedding provider not configured — use keyword results as-is
            vector_top = [(0.0, r) for r in rows[:top_k * 2]]

        if not vector_top:
            return []

        # Phase 3: reranker refinement (optional)
        try:
            reranker = RerankerService(self.db)
            docs_for_rerank = [r.content for _, r in vector_top]
            reranked = await reranker.rerank(query, docs_for_rerank, top_n=top_k)
            # 空、重复或越界响应不能把已召回原文变成“未检索到资料”。
            if len(reranked) != min(top_k, len(vector_top)) or len({idx for idx, _ in reranked}) != len(reranked):
                raise ValueError("Incomplete reranking response")
            if any(type(idx) is not int or not 0 <= idx < len(vector_top)
                   or not isinstance(score, (int, float)) or not math.isfinite(score)
                   for idx, score in reranked):
                raise ValueError("Invalid reranking response")
            final = []
            for idx, score in reranked[:top_k]:
                _, row = vector_top[idx]
                final.append({
                    "chunk_id": str(row.id),
                    "content": row.content,
                    "chunk_index": row.chunk_index,
                    "document_id": str(row.doc_id),
                    "document_title": row.title,
                    "document_type": row.doc_type.value,
                    "source_url": row.source_url,
                    "rank": round(score, 4),
                    **retrieval_metadata.get(str(row.id), {}),
                })
            return final
        except Exception as exc:
            # 供应商不可用或响应损坏时保留已召回片段，后续统一相关性评估仍照常执行。
            import logging
            logging.getLogger(__name__).warning("RAG 重排不可用，保留候选原文：%s", type(exc).__name__)
            return [
                {
                    "chunk_id": str(row.id),
                    "content": row.content,
                    "chunk_index": row.chunk_index,
                    "document_id": str(row.doc_id),
                    "document_title": row.title,
                    "document_type": row.doc_type.value,
                    "source_url": row.source_url,
                    "rank": round(score, 4),
                    **retrieval_metadata.get(str(row.id), {}),
                }
                for score, row in vector_top[:top_k]
            ]

    async def generate_answer(
        self,
        query: str,
        context_chunks: list[dict[str, Any]],
        system_prompt: str | None = None,
        provider: str | None = None,
    ) -> str:
        """Generate answer using retrieved context + LLM."""
        context = "\n\n---\n\n".join(
            f"[来源: {c['document_title']}]\n{c['content']}"
            for c in context_chunks
        )

        # Try LLM generation; fallback to context summary if no API key
        try:
            default_system = (
                "你是一位专业的医疗AI助手。请基于以下参考文献回答问题，"
                "如果参考文献不足以回答，请明确告知。"
                "回答要求：准确、简洁、专业。"
            )

            messages = [
                {"role": "system", "content": system_prompt or default_system},
                {"role": "user", "content": f"问题：{query}\n\n参考文献：\n{context}"},
            ]

            llm = LLMService(provider=provider, db=self.db)
            resp = await llm.chat(
                messages=messages,
                temperature=settings.rag_llm_temperature,
                max_tokens=settings.rag_llm_max_tokens,
            )
            return resp.content
        except ValueError:
            # No API key configured — return context as-is with disclaimer
            return (
                "[LLM 未配置] 以下是检索到的相关参考文献：\n\n"
                + context
                + "\n\n注：当前未配置 LLM API Key，因此返回原文摘要。"
            )

    async def query(
        self,
        query: str,
        doc_type: DocType | None = None,
        top_k: int = 5,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """End-to-end RAG pipeline: search + generate."""
        chunks = await self.search(query, doc_type=doc_type, top_k=top_k)
        if not chunks:
            return {
                "answer": "未找到相关参考文献，无法回答该问题。",
                "sources": [],
                "retrieved_chunks": 0,
            }

        answer = await self.generate_answer(query, chunks, provider=provider)
        return {
            "answer": answer,
            "sources": [
                {
                    "source_type": "internal",
                    "title": c["document_title"],
                    "type": c["document_type"],
                    "document_type": c["document_type"],
                    "document_id": c["document_id"],
                    "chunk_id": c["chunk_id"],
                    "chunk_index": c["chunk_index"],
                    "source_url": c.get("source_url"),
                    "excerpt": c["content"],
                    "relevance": c["rank"],
                }
                for c in chunks
            ],
            "retrieved_chunks": len(chunks),
        }
