"""Reranker service for refining retrieval results.

Reads reranking provider config from llm_provider_configs (model_type='reranking').
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_value
from app.models.config import LLMProviderConfig
from app.services.interview_demo import provider_http_client


class RerankerService:
    """Unified reranker client for RAG result refinement."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._client: AsyncOpenAI | None = None
        self._model: str = ""

    async def _get_client(self) -> AsyncOpenAI:
        """Lazy-init reranker client from admin config."""
        if self._client is not None:
            return self._client

        config = await self._resolve_provider()
        self._model = config["default_model"]
        self._client = AsyncOpenAI(
            http_client=provider_http_client(),
            base_url=config["base_url"],
            api_key=config["api_key"],
            timeout=30.0,
            max_retries=2,
        )
        return self._client

    async def _resolve_provider(self) -> dict[str, str]:
        """Fetch active reranking provider from database."""
        result = await self.db.execute(
            select(LLMProviderConfig).where(
                LLMProviderConfig.model_type == "reranking",
                LLMProviderConfig.is_active == True,
            ).limit(1)
        )
        cfg = result.scalars().first()
        if cfg is None:
            raise ValueError(
                "No active reranking provider configured. "
                "Please add one via Admin > LLM Providers (model_type='reranking')."
            )

        api_key = decrypt_value(cfg.api_key_encrypted)
        if not api_key:
            raise ValueError(f"Reranking provider '{cfg.provider}' has no API key.")

        return {
            "base_url": cfg.base_url,
            "api_key": api_key,
            "default_model": cfg.default_model,
        }

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 5,
    ) -> list[tuple[int, float]]:
        """Rerank documents by relevance to query.

        返回按相关度排序的 (原始序号, 分数)。无供应商时抛出 ValueError，
        由调用方保留向量检索的顺序与分数。
        """
        client = await self._get_client()

        response = await client.post(
            "/rerank",
            body={
                "model": self._model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
            cast_to=dict,
        )

        results: list[dict[str, Any]] = response.get("results", [])
        return [(r["index"], r["relevance_score"]) for r in results]

    async def health_check(self) -> dict[str, Any]:
        """Quick health check."""
        try:
            await self._resolve_provider()
            return {"status": "ok", "model": self._model or "pending"}
        except ValueError as e:
            return {"status": "error", "detail": str(e)}
