"""RAG (Retrieval-Augmented Generation) service.

MVP implementation using PostgreSQL ILIKE for Chinese text search.
Phase 2: upgrade to pgvector for semantic search.

SearXNG integration planned for real-time external knowledge retrieval.
"""

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


class RAGService:
    """Retrieval-Augmented Generation service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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

        Phase 1: keyword-based coarse retrieval (top 50)
        Phase 2: vector cosine similarity re-rank
        Phase 3: cross-encoder reranker refinement (if configured)
        """
        # Phase 1: coarse keyword retrieval (expand to configurable multiplier for re-ranking)
        coarse_k = max(top_k * settings.rag_coarse_multiplier, settings.rag_coarse_min)
        search_terms = _coarse_search_terms(query, settings.rag_query_term_length)
        if not search_terms:
            return []
        matches = [DocumentChunk.content.ilike(f"%{term}%") for term in search_terms]
        overlap_score = sum(case((match, 1), else_=0) for match in matches)

        stmt = select(
            DocumentChunk.id,
            DocumentChunk.content,
            DocumentChunk.chunk_index,
            DocumentChunk.embedding_json,
            Document.id.label("doc_id"),
            Document.title,
            Document.doc_type,
            Document.source_url,
        ).join(Document).where(
            or_(*matches),
            Document.is_active == True,
        )

        if doc_type:
            stmt = stmt.where(Document.doc_type == doc_type)

        stmt = stmt.order_by(overlap_score.desc(), DocumentChunk.id).limit(coarse_k)
        result = await self.db.execute(stmt)
        rows = result.all()

        if not rows:
            return []

        # Phase 2: vector similarity ranking
        try:
            embed_svc = EmbeddingService(self.db)
            query_emb = (await embed_svc.embed([query]))[0]

            scored = []
            for row in rows:
                if row.embedding_json:
                    emb = row.embedding_json
                    if isinstance(emb, str):
                        import json
                        emb = json.loads(emb)
                    score = EmbeddingService.cosine_similarity(query_emb, emb)
                else:
                    score = 0.0  # fallback for non-vectorized chunks
                scored.append((score, row))

            scored.sort(key=lambda x: x[0], reverse=True)
            vector_top = scored[:top_k * 2]
        except ValueError:
            # Embedding provider not configured — use keyword results as-is
            vector_top = [(0.0, r) for r in rows[:top_k * 2]]

        # Phase 3: reranker refinement (optional)
        try:
            reranker = RerankerService(self.db)
            docs_for_rerank = [r.content for _, r in vector_top]
            reranked = await reranker.rerank(query, docs_for_rerank, top_n=top_k)
            # 空、重复或越界响应不能把已召回原文变成“未检索到资料”。
            import math
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
