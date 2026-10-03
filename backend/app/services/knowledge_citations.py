"""Build patient-facing citations from sources returned by the retriever."""

from __future__ import annotations

import re
import asyncio
import hashlib
import logging
import math
from copy import deepcopy
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

MAX_CITATIONS = 10
MAX_EXCERPT_CHARS = 800
_CITATION_MARKER = re.compile(r"\[(S\d+)\]")


class KnowledgeEvidence(BaseModel):
    """生成端仅提供路径和摘录，匹配状态及坐标一律由服务端重算。"""
    claim_path: str
    citation_id: str
    quote: str = ""
    claim: str = ""
    status: Literal["excerpt_matched", "needs_review"] = "needs_review"
    reason: str = "尚未核对原文"
    start: int | None = None
    end: int | None = None


def evidence_matches_excerpt(row: dict, citation: dict) -> bool:
    """导出时也核对坐标与原文，缺记录或损坏记录保持待核对。"""
    start, end, quote = row.get("start"), row.get("end"), row.get("quote")
    excerpt = citation.get("excerpt")
    return (row.get("status") == "excerpt_matched"
            and row.get("citation_id") == citation.get("citation_id")
            and isinstance(quote, str) and bool(quote) and quote == row.get("claim")
            and isinstance(excerpt, str) and type(start) is int and type(end) is int
            and 0 <= start < end <= len(excerpt) and excerpt[start:end] == quote)


_SOURCE_FIELDS = {
    "knowledge_sources", "knowledge_citations", "knowledge_evidence",
    "knowledge_retrieval_status", "knowledge_retrieval_count", "disclaimer",
    "interview_information_gaps", "interview_stop_reason", "interview_is_sufficient",
}


def _claim_strings(value: Any, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _claim_strings(item, f"{path}.{index}" if path else str(index))
    elif isinstance(value, dict):
        for key, item in value.items():
            if not path and key in _SOURCE_FIELDS:
                continue
            yield from _claim_strings(item, f"{path}.{key}" if path else key)


def check_claim_evidence(report: dict[str, Any], citations: list[KnowledgeCitation]) -> list[dict]:
    """整条文本精确对应完整摘录句才能匹配；意译与半句仍待核对，非NLI。"""
    proposals = report.get("knowledge_evidence")
    proposals = proposals if isinstance(proposals, list) else []
    sources = {item.citation_id: item for item in citations}
    rows = []
    for path, text in _claim_strings(report):
        claim = _CITATION_MARKER.sub("", text).strip()
        for cid in dict.fromkeys(_CITATION_MARKER.findall(text)):
            if cid not in sources:
                continue
            suggested = [p for p in proposals if isinstance(p, dict)
                         and p.get("claim_path") == path and p.get("citation_id") == cid]
            row = KnowledgeEvidence(claim_path=path, citation_id=cid, claim=claim)
            quote = suggested[0].get("quote") if len(suggested) == 1 else claim if not suggested else None
            excerpt = sources[cid].excerpt
            if not isinstance(quote, str) or not quote or quote != claim:
                row.reason = "陈述与摘录不一致或定位重复，需核对"
            elif excerpt.count(quote) != 1:
                row.reason = "摘录不存在或出现多次，无法唯一定位"
            else:
                start = excerpt.index(quote)
                end = start + len(quote)
                left = excerpt[:start].rstrip()
                right = excerpt[end:].lstrip()
                full_left = not left or left[-1] in "。！？.!?\n"
                full_right = not right or quote[-1] in "。！？.!?\n" or right[0] in "。！？.!?\n"
                # 逗号、分号、冒号不作为起始边界，避免丢掉否定和条件前提。
                if full_left and full_right:
                    row.status = "excerpt_matched"
                    row.reason = "整条陈述与完整原文片段一致；适用性仍需专业核对"
                    row.quote, row.start, row.end = quote, start, end
                else:
                    row.reason = "只匹配句内片段，可能丢失否定或条件范围"
            rows.append(row.model_dump())
    return rows


class KnowledgeCitation(BaseModel):
    """A retrieved source with enough metadata for a patient to inspect it."""

    citation_id: str
    source_type: Literal["internal", "external"]
    title: str
    excerpt: str
    used_in_report: bool | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    chunk_index: int | None = None
    document_type: str | None = None
    url: str | None = None
    source_engine: str | None = None
    trust_score: int | None = None
    is_trusted: bool | None = None
    relevance: float | None = None
    relevance_method: Literal["reranker", "keyword", "unassessed"] = "unassessed"
    relevance_level: Literal["matched", "unassessed"] = "unassessed"
    relevance_reason: str = "未使用统一相关性评估"
    relevance_query_fingerprint: str = ""


def _safe_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


def build_knowledge_citations(
    sources: Any, max_citations: int = MAX_CITATIONS
) -> list[KnowledgeCitation]:
    """Normalize only traceable records returned by internal/external search."""
    if not isinstance(sources, list) or max_citations <= 0:
        return []

    citations: list[KnowledgeCitation] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue

        source_type = source.get("source_type")
        title = source.get("title") or source.get("document_title")
        excerpt = source.get("excerpt") or source.get("snippet") or source.get("content")
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(excerpt, str) or not excerpt.strip():
            continue

        document_id = source.get("document_id")
        chunk_id = source.get("chunk_id")
        url = _safe_http_url(source.get("url") or source.get("source_url"))

        if source_type == "internal":
            if not isinstance(document_id, str) or not document_id.strip():
                continue
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                continue
            dedupe_key = ("internal", chunk_id)
        elif source_type == "external":
            if not url:
                continue
            dedupe_key = ("external", url)
        else:
            continue

        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        citations.append(KnowledgeCitation(
            citation_id=f"S{len(citations) + 1}",
            source_type=source_type,
            title=title.strip(),
            excerpt=excerpt.strip()[:MAX_EXCERPT_CHARS],
            document_id=document_id if isinstance(document_id, str) else None,
            chunk_id=chunk_id if isinstance(chunk_id, str) else None,
            chunk_index=source.get("chunk_index") if isinstance(source.get("chunk_index"), int) else None,
            document_type=(
                source.get("document_type") or source.get("type")
                if isinstance(source.get("document_type") or source.get("type"), str)
                else None
            ),
            url=url,
            source_engine=source.get("source_engine") if isinstance(source.get("source_engine"), str) else None,
            trust_score=source.get("trust_score") if isinstance(source.get("trust_score"), int) else None,
            is_trusted=source.get("is_trusted") if isinstance(source.get("is_trusted"), bool) else None,
            relevance=source.get("relevance") if isinstance(source.get("relevance"), (int, float)) else None,
            relevance_method=source.get("relevance_method") if source.get("relevance_method") in {"reranker", "keyword"} else "unassessed",
            relevance_level="matched" if source.get("relevance_level") == "matched" else "unassessed",
            relevance_reason=source.get("relevance_reason") if isinstance(source.get("relevance_reason"), str) else "未使用统一相关性评估",
            relevance_query_fingerprint=source.get("relevance_query_fingerprint") if isinstance(source.get("relevance_query_fingerprint"), str) else "",
        ))
        if len(citations) >= max_citations:
            break

    return citations


_GENERIC_QUERY_TERMS = {"儿童", "患者", "指南", "诊疗", "方案", "临床", "相关", "资料", "信息", "合成", "原文", "主题",
                        "the", "and", "with", "for", "of", "in", "to"}


def _query_terms(query: str) -> set[str]:
    terms = set(re.findall(r"[a-z][a-z0-9-]{1,}", query.casefold()))
    for phrase in re.findall(r"[\u4e00-\u9fff]+", query):
        terms.update(phrase[index:index + 2] for index in range(len(phrase) - 1))
    return terms - _GENERIC_QUERY_TERMS


async def rank_knowledge_citations(
    query: str, citations: list[KnowledgeCitation], db: Any, *, min_relevance: float = 0.25,
) -> list[KnowledgeCitation]:
    """相同query和摘录口径重排两类来源；无供应商时明确降级为词匹配。"""
    if not citations:
        return []
    query = query.strip()[:512]
    fingerprint = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if (len({c.relevance_method for c in citations if c.relevance_method != "unassessed"}) <= 1
        and all(c.relevance_query_fingerprint == fingerprint for c in citations)) and all(
        (c.relevance_method in {"reranker", "keyword"} and c.relevance is not None
         and math.isfinite(c.relevance) and 0 <= c.relevance <= 1)
        or (c.relevance_method == "unassessed" and c.relevance is None) for c in citations
    ):
        retained = [c for c in citations if c.relevance is None or (
            c.relevance > 0 and (c.relevance_method == "keyword" or c.relevance >= min_relevance))]
        return sorted(retained, key=lambda c: c.relevance if c.relevance is not None else -1, reverse=True)
    scored: list[tuple[int, float | None, str, str]] = []
    try:
        from app.services.reranker import RerankerService
        reranked = await asyncio.wait_for(
            RerankerService(db).rerank(query, [f"{c.title}\n{c.excerpt}" for c in citations], top_n=len(citations)),
            timeout=8.0,
        )
        if len(reranked) != len(citations) or {index for index, _ in reranked} != set(range(len(citations))):
            raise ValueError("Incomplete reranking response")
        for index, score in reranked:
            if type(index) is not int or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("Invalid reranking score")
            scored.append((index, float(score), "reranker", "与本次检索主题统一进行语义重排；不代表原文支持报告结论"))
    except Exception as exc:
        logging.getLogger(__name__).info("来源相关性降级为词匹配：%s", type(exc).__name__)
        terms = _query_terms(query)
        scored = []
        for index, citation in enumerate(citations):
            text = f"{citation.title}\n{citation.excerpt}".casefold()
            matches = sorted(term for term in terms if term in text)
            different_language = bool(re.search(r"[\u4e00-\u9fff]", query)) != bool(re.search(r"[\u4e00-\u9fff]", text))
            if not terms or (different_language and not matches):
                scored.append((index, None, "unassessed", "当前词匹配无法评估该来源；未认定其语义相关或不相关"))
            else:
                score = len(matches) / len(terms)
                reason = "原文或标题匹配主题词：" + "、".join(matches[:8]) if matches else "未匹配本次检索主题词"
                scored.append((index, score, "keyword", reason + "；词覆盖率不套用语义阈值，不等于语义支持"))
    ranked = []
    for index, score, method, reason in scored:
        # 无法评估不伪装成低相关；放在已匹配来源之后，并显式保留待核对状态。
        if score is not None and (score <= 0 or (method == "reranker" and score < min_relevance)):
            continue
        ranked.append(citations[index].model_copy(update={
            "relevance": score, "relevance_method": method,
            "relevance_level": "matched" if score is not None else "unassessed",
            "relevance_reason": reason, "relevance_query_fingerprint": fingerprint,
        }))
    logging.getLogger(__name__).info("来源筛选：候选=%d 保留=%d 方法=%s", len(citations), len(ranked),
                                    ",".join(sorted({method for _, _, method, _ in scored})))
    return sorted(ranked, key=lambda c: -(c.relevance if c.relevance is not None else -1.0))


def format_knowledge_context(citations: list[KnowledgeCitation]) -> str:
    """Present exact retrieved excerpts and IDs to the report-generation model."""
    if not citations:
        return "本次检索没有返回可核验来源。不得声称引用了知识库或外部资料，也不得编造来源。"

    lines = [
        "以下是本次检索实际返回的来源和原文摘录。只能使用这些引用编号，不得编造编号或来源。",
        "可提供knowledge_evidence：claim_path（如key_findings.0）、citation_id、quote（原文完整句）。不填写核对状态或坐标。",
        "原文核对只证明抽取一致；意译、患者适用性与医学判断仍需专业核对。不要为匹配摘录而添加与患者无关的陈述。",
    ]
    for citation in citations:
        origin = "内部知识库" if citation.source_type == "internal" else "外部资料"
        lines.append(f"[{citation.citation_id}] {origin}｜{citation.title}")
        if citation.source_type == "internal":
            lines.append(
                f"文档ID：{citation.document_id}；片段序号："
                f"{citation.chunk_index + 1 if citation.chunk_index is not None else '未提供'}；"
                f"片段ID：{citation.chunk_id}"
            )
        elif citation.url:
            lines.append(f"链接：{citation.url}")
        lines.append(f"原文摘录：{citation.excerpt}")

    return "\n".join(lines)


def attach_knowledge_citations(
    report: dict[str, Any],
    citations: list[KnowledgeCitation],
    retrieval_status: Literal["retrieved_not_cited", "no_sources", "failed"] = "no_sources",
) -> dict[str, Any]:
    """保留实际检索资料；正文引用另行标记，不因模型漏写编号而隐藏来源。"""
    allowed_ids = {citation.citation_id for citation in citations}

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return _CITATION_MARKER.sub(
                lambda match: match.group(0) if match.group(1) in allowed_ids else "",
                value,
            )
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value

    result = clean(report)
    claim_fields = {
        key: value for key, value in result.items()
        if key not in _SOURCE_FIELDS
    }
    used_ids = {
        match.group(1)
        for value in _walk_strings(claim_fields)
        for match in _CITATION_MARKER.finditer(value)
    }
    used_citations = [citation for citation in citations if citation.citation_id in used_ids]
    result["knowledge_citations"] = [citation.model_copy(update={"used_in_report": citation.citation_id in used_ids}).model_dump()
                                    for citation in citations]
    result["knowledge_sources"] = list(dict.fromkeys(citation.title for citation in citations))
    result["knowledge_retrieval_status"] = (
        "used" if used_citations else "retrieved_not_cited" if citations else retrieval_status
    )
    result["knowledge_retrieval_count"] = len(citations)
    result["knowledge_evidence"] = check_claim_evidence(result, used_citations)
    return result


def apply_report_citation_bindings(report: dict[str, Any], citations: list[KnowledgeCitation], bindings: Any) -> dict[str, Any]:
    """只给既有医学陈述补编号；路径、来源及完整摘录可核验，不改正文。"""
    result = deepcopy(report)
    if not isinstance(bindings, list):
        return result
    sources = {item.citation_id: item for item in citations}
    claims = dict(_claim_strings(report))
    evidence = list(result.get("knowledge_evidence") or [])
    allowed_path = re.compile(r"(?:primary_diagnosis|follow_up_timeline|(?:recommended_actions|recommended_tests|contraindications)\.\d+|differential_diagnoses\.\d+\.(?:diagnosis|reasoning))")
    for binding in bindings[:30]:
        if not isinstance(binding, dict):
            continue
        path, cid, quote = binding.get("claim_path"), binding.get("citation_id"), binding.get("quote")
        if not isinstance(path, str) or not isinstance(cid, str) or not allowed_path.fullmatch(path) or path not in claims or cid not in sources:
            continue
        if not isinstance(quote, str) or not quote.strip():
            continue
        checked = check_claim_evidence({"recommended_actions": [f"{quote}[{cid}]"]}, [sources[cid]])
        if not checked or checked[0]["status"] != "excerpt_matched":
            continue
        parts = path.split(".")
        parent = result
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        leaf = int(parts[-1]) if isinstance(parent, list) else parts[-1]
        if f"[{cid}]" not in parent[leaf]:
            parent[leaf] += f"[{cid}]"
        evidence.append({"claim_path": path, "citation_id": cid, "quote": quote})
    result["knowledge_evidence"] = evidence
    return result


def restore_report_sources(report: dict | None, tool_calls: list | None) -> dict | None:
    """只读恢复旧报告实际保存的检索来源，原编号不变，不改数据库或正文。"""
    if not report or report.get("knowledge_citations") or not report.get("knowledge_retrieval_count"):
        return report
    for call in reversed(tool_calls or []):
        if not isinstance(call, dict) or call.get("tool") != "search_medical_knowledge":
            continue
        result = call.get("result")
        if not isinstance(result, dict):
            continue
        result = result.get("result", result)
        if not isinstance(result, dict) or not isinstance(result.get("sources"), list):
            continue
        citations = []
        seen = set()
        for source in result["sources"][:MAX_CITATIONS]:
            if not isinstance(source, dict):
                continue
            cid = source.get("citation_id")
            if not isinstance(cid, str) or not re.fullmatch(r"S[1-9]\d*", cid) or cid in seen:
                continue
            normalized = build_knowledge_citations([source], max_citations=1)
            if normalized:
                seen.add(cid)
                citations.append(normalized[0].model_copy(update={"citation_id": cid}))
        if citations:
            return attach_knowledge_citations(report, citations, "retrieved_not_cited")
    return report


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
