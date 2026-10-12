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
SOURCE_POLICY_VERSION = "source_gate_v3_query_coverage"
# 本地开发集校准值，仅用于已核对同模型/维度的命中锚点，不套用到词覆盖率。
CALIBRATED_EMBEDDING_GATES = {("text-embedding-3-small", 1536): 0.42}
# 人群、操作类别及提问套话不能单独证明具体主题命中；用于弱语义分的复核，非分词医学实体表。
_BROAD_MATCH_TERMS = {"成人", "患儿", "手术", "治疗", "药物", "时间", "依据", "选择", "标准",
                      "需要", "是否", "如何", "哪些", "怎么", "什么", "方案", "文档", "这些", "哪里",
                      "对应", "基础", "调节", "记录", "观察", "情况", "不同", "注意", "考虑", "严重", "专题",
                      "only", "text", "guidance", "guideline", "treatment", "need", "which", "what"}
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
    relevance_method: Literal["reranker", "keyword", "query_requirements", "unassessed"] = "unassessed"
    relevance_level: Literal["matched", "unassessed"] = "unassessed"
    relevance_reason: str = "未使用统一相关性评估"
    relevance_query_fingerprint: str = ""
    relevance_policy_version: str = ""
    retrieval_method: str | None = None
    retrieval_model: str | None = None
    retrieval_dimension: int | None = None
    retrieval_score: float | None = None
    retrieval_query_fingerprint: str = ""
    retrieval_anchor_excerpt: str = ""
    context_metadata: dict[str, Any] | None = None
    query_coverage: dict[str, Any] | None = None


def _checked_context_metadata(source: dict, raw: str, excerpt: str) -> dict | None:
    """校验保存结构及截取坐标；原文真实性由只读文档定位端核对。"""
    meta = source.get("context_metadata")
    if not isinstance(meta, dict) or source.get("source_type") != "internal":
        return None
    start, end, ids = meta.get("start"), meta.get("end"), meta.get("chunk_ids")
    if (type(start) is not int or type(end) is not int or start < 0 or end - start != len(raw)
        or meta.get("document_id") != source.get("document_id")
        or meta.get("anchor_chunk_id") != source.get("chunk_id")
        or not isinstance(ids, list) or not 1 <= len(ids) <= 3
        or any(not isinstance(cid, str) or not cid for cid in ids) or len(set(ids)) != len(ids)
        or source.get("chunk_id") not in ids or meta.get("method") != "anchor_neighbors"
        or not isinstance(meta.get("source_text_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", meta["source_text_sha256"])):
        return None
    start += len(raw) - len(raw.lstrip())
    return {"document_id":meta["document_id"], "anchor_chunk_id":meta["anchor_chunk_id"],
            "chunk_ids":list(ids), "source_text_sha256":meta["source_text_sha256"],
            "method":"anchor_neighbors", "start":start, "end":start+len(excerpt), "max_chars":1600}


def _safe_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


def build_knowledge_citations(
    sources: Any, max_citations: int = MAX_CITATIONS, *, max_excerpt_chars: int = MAX_EXCERPT_CHARS
) -> list[KnowledgeCitation]:
    """Normalize only traceable records returned by internal/external search."""
    if not isinstance(sources, list) or max_citations <= 0 or max_excerpt_chars <= 0:
        return []
    # 上下文实验可显式扩大内部摘录；默认和外部摘录仍保持800，硬上限1600。
    max_excerpt_chars = min(max_excerpt_chars, 1600)

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

        budget = min(max_excerpt_chars, MAX_EXCERPT_CHARS) if source_type == "external" else max_excerpt_chars
        # 已核对的上下文在后续Agent归一化/历史恢复中保留，不能再悄悄截回800。
        checked = _checked_context_metadata(source, excerpt, excerpt.strip()[:1600])
        if checked:
            budget = 1600
        normalized_excerpt = excerpt.strip()[:budget]
        score = source.get("retrieval_score")
        score = float(score) if type(score) in (int, float) and math.isfinite(score) and -1 <= score <= 1 else None

        citations.append(KnowledgeCitation(
            citation_id=f"S{len(citations) + 1}",
            source_type=source_type,
            title=title.strip(),
            excerpt=normalized_excerpt,
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
            relevance_method=source.get("relevance_method") if source.get("relevance_method") in {"reranker", "keyword", "query_requirements"} else "unassessed",
            relevance_level="matched" if source.get("relevance_level") == "matched" else "unassessed",
            relevance_reason=source.get("relevance_reason") if isinstance(source.get("relevance_reason"), str) else "未使用统一相关性评估",
            relevance_query_fingerprint=source.get("relevance_query_fingerprint") if isinstance(source.get("relevance_query_fingerprint"), str) else "",
            relevance_policy_version=source.get("relevance_policy_version") if isinstance(source.get("relevance_policy_version"), str) else "",
            query_coverage=deepcopy(source.get("query_coverage")) if isinstance(source.get("query_coverage"), dict)
                and source['query_coverage'].get('excerpt_sha256') == hashlib.sha256(normalized_excerpt.encode()).hexdigest() else None,
            retrieval_method=source.get("retrieval_method") if source_type == "internal" and source.get("retrieval_method") in {"embedding_cosine", "keyword", "reranker"} else None,
            retrieval_model=source.get("retrieval_model") if source_type == "internal" and isinstance(source.get("retrieval_model"), str) else None,
            retrieval_dimension=source.get("retrieval_dimension") if source_type == "internal" and type(source.get("retrieval_dimension")) is int else None,
            retrieval_score=score if source_type == "internal" else None,
            retrieval_query_fingerprint=source.get("retrieval_query_fingerprint") if source_type == "internal" and isinstance(source.get("retrieval_query_fingerprint"), str) else "",
            retrieval_anchor_excerpt=source.get("retrieval_anchor_excerpt", "")[:800] if source_type == "internal" and isinstance(source.get("retrieval_anchor_excerpt", ""), str) else "",
            context_metadata=_checked_context_metadata(source, excerpt, normalized_excerpt),
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


def _specific_query_terms(query: str) -> set[str]:
    # 先切开套话再生成bigram，避免“治疗时间”被当成具体主题词“疗时”。
    generic = sorted(_GENERIC_QUERY_TERMS | _BROAD_MATCH_TERMS, key=len, reverse=True)
    cleaned = query.casefold()
    chinese = [term for term in generic if re.search(r"[\u4e00-\u9fff]", term)]
    cleaned = re.sub("|".join(map(re.escape, chinese)), " ", cleaned)
    return _query_terms(cleaned) - _BROAD_MATCH_TERMS


def _passes_anchor_gate(query: str, citation: KnowledgeCitation, fingerprint: str) -> bool:
    """只在无统一重排时复核已校准的弱锚点；具体词匹配不是支持证明。"""
    threshold = CALIBRATED_EMBEDDING_GATES.get((citation.retrieval_model, citation.retrieval_dimension))
    if (citation.source_type != "internal" or citation.retrieval_method != "embedding_cosine"
        or citation.retrieval_query_fingerprint != fingerprint or threshold is None
        or citation.retrieval_score is None or not math.isfinite(citation.retrieval_score)
        or not -1 <= citation.retrieval_score <= 1 or citation.retrieval_score >= threshold):
        return True
    anchor = citation.retrieval_anchor_excerpt or (citation.excerpt[:800] if not citation.context_metadata else "")
    text = f"{citation.title}\n{anchor}".casefold()
    return any(term in text for term in _specific_query_terms(query))


def _valid_query_coverage(citation: KnowledgeCitation) -> bool:
    meta = citation.query_coverage
    if not isinstance(meta, dict) or meta.get('excerpt_sha256') != hashlib.sha256(citation.excerpt.encode()).hexdigest():
        return False
    fields = [meta.get(k) for k in ('requirements', 'covered_requirements', 'missing_requirements', 'uncertain_requirements')]
    if not all(isinstance(v, list) and all(isinstance(r, str) and r.strip() for r in v) and len(set(v)) == len(v) for v in fields):
        return False
    requirements, covered, missing, uncertain = fields
    if not 1 <= len(requirements) <= 8 or len(covered + missing + uncertain) != len(requirements) or set(covered + missing + uncertain) != set(requirements):
        return False
    status = 'unknown' if uncertain else 'answers' if len(covered) == len(requirements) else 'partial_answer' if covered else 'does_not_answer'
    fraction = None if uncertain else len(covered) / len(requirements)
    return meta.get('status') == status and citation.relevance == fraction


async def _assess_query_coverage(query, citations, db):
    if db is None:
        return {'status': 'assessment_error'}
    from app.services.llm import LLMService
    from app.services.query_requirements import assess_query
    # 每组只调用一次；超时回退既有来源策略，不改变供应商/演示控制。
    return await asyncio.wait_for(assess_query(query, [
        {'id': c.citation_id, 'title': c.title, 'excerpt': c.excerpt} for c in citations],
        LLMService(db=db, platform='web', model_type='diagnosis', timeout=10, max_retries=0)), timeout=12)


async def rank_knowledge_citations(
    query: str, citations: list[KnowledgeCitation], db: Any, *, min_relevance: float = 0.25,
) -> list[KnowledgeCitation]:
    """先核对问题要点覆盖；失败回退既有重排/词匹配，保留真实出处。"""
    if not citations:
        return []
    original_query = query.strip()
    query = original_query[:512]
    fingerprint = hashlib.sha256(query.encode("utf-8")).hexdigest()
    requested_years = set(re.findall(r"((?:19|20)\d{2})\s*(?:年\s*)?(?=版|(?:新|最新)?发布|更新|edition|guideline|update)", query, re.I))
    retained = []
    for citation in citations:
        # 只匹配显式版本请求，不把出生年份或疗程数字视为资料版本。
        if requested_years and not all(re.search(rf"(?<!\d){year}(?!\d)", citation.title)
            or re.search(rf"(?<!\d){year}\s*年?\s*(?:版|edition)", citation.excerpt, re.I) for year in requested_years):
            continue
        retained.append(citation)
    citations = retained
    if not citations:
        return []
    if all(c.relevance_method == 'query_requirements' and c.relevance_query_fingerprint == fingerprint
           and c.relevance_policy_version == SOURCE_POLICY_VERSION and _valid_query_coverage(c) for c in citations):
        return sorted([c for c in citations if c.query_coverage['status'] != 'does_not_answer'],
                      key=lambda c: -(c.relevance if c.relevance is not None else -1))
    if (len({c.relevance_method for c in citations if c.relevance_method != "unassessed"}) <= 1
        and all(c.relevance_query_fingerprint == fingerprint and c.relevance_policy_version == SOURCE_POLICY_VERSION for c in citations)) and all(
        (c.relevance_method in {"reranker", "keyword"} and c.relevance is not None
         and math.isfinite(c.relevance) and 0 <= c.relevance <= 1)
        or (c.relevance_method == "unassessed" and c.relevance is None) for c in citations
    ):
        retained = [c for c in citations if (c.relevance_method == "reranker" or _passes_anchor_gate(query,c,fingerprint))
            and (c.relevance is None or (c.relevance > 0 and (c.relevance_method == "keyword" or c.relevance >= min_relevance)))]
        return sorted(retained, key=lambda c: c.relevance if c.relevance is not None else -1, reverse=True)
    try:
        if len(original_query) > 512:
            raise ValueError('问题超出完整覆盖判断预算，回退而不宣称截断后的完整性')
        coverage = await _assess_query_coverage(query, citations, db)
        if coverage['status'] == 'assessed':
            rows = {r['id']: r for r in coverage['candidates']}
            if set(rows) != {c.citation_id for c in citations}:
                raise ValueError('覆盖判断候选数量不完整')
            ranked = []
            for citation in citations:
                row = rows[citation.citation_id]
                if not row['retain']:
                    continue
                status = row['label']
                missing = row['missing_requirements']
                reason = {'answers': '模型判断：本资料覆盖所提问题的全部要点',
                          'partial_answer': '模型判断：本资料覆盖部分要点；未覆盖：' + '、'.join(missing),
                          'unknown': '模型未能确定本资料的覆盖情况，保留待核对'}[status]
                ranked.append(citation.model_copy(update={
                    'relevance': row['coverage_fraction'], 'relevance_method': 'query_requirements',
                    'relevance_level': 'unassessed' if status == 'unknown' else 'matched',
                    'relevance_reason': reason + '；不代表原文支持报告结论或适用于患者',
                    'relevance_query_fingerprint': fingerprint, 'relevance_policy_version': SOURCE_POLICY_VERSION,
                    'query_coverage': {k: deepcopy(row[k]) for k in ('covered_requirements', 'missing_requirements', 'uncertain_requirements')}
                        | {'requirements': coverage['requirements'], 'status': status,
                           'excerpt_sha256': hashlib.sha256(citation.excerpt.encode()).hexdigest()},
                }))
            return sorted(ranked, key=lambda c: -(c.relevance if c.relevance is not None else -1))
        raise ValueError('覆盖判断未完成')
    except Exception as exc:
        logging.getLogger(__name__).info('问题覆盖判断未完成，回退来源策略：%s', type(exc).__name__)
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
            if not _passes_anchor_gate(query,citation,fingerprint):
                continue
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
            "relevance_policy_version": SOURCE_POLICY_VERSION,
            # 回退口径不能携带已失效的模型覆盖结果。
            "query_coverage": None,
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
            if citation.context_metadata:
                meta=citation.context_metadata
                lines.append(f"此摘录包含同文档相邻内容；原文字符范围[{meta['start']}, {meta['end']})，命中片段为锚点。")
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
