"""Medical tools for Agent use.

These tools wrap existing backend services so Agents can:
- Search the medical knowledge base
- Query patient history
- Check drug interactions
- Generate structured reports

All tools are registered to GLOBAL_REGISTRY on import.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.tools.base import SimpleTool, Tool
from app.tools.registry import register_tool


# ---------------------------------------------------------------------------
# Parameter schemas (Pydantic → JSON Schema for LLM)
# ---------------------------------------------------------------------------

class SearchKnowledgeParams(BaseModel):
    """Parameters for search_medical_knowledge tool."""

    query: str = Field(..., description="The medical question or keywords to search", min_length=1)
    doc_type: str | None = Field(
        None,
        description="Filter by document type: platform_guideline, case_report, drug_reference",
    )
    top_k: int = Field(10, description="Number of top results to retrieve", ge=1, le=20)


class QueryPatientHistoryParams(BaseModel):
    """Parameters for query_patient_history tool."""

    patient_id: str = Field(..., description="UUID of the patient")
    limit: int = Field(5, description="Max number of recent cases to return", ge=1, le=50)
    include_documents: bool = Field(
        False, description="Whether to include attached medical documents"
    )


class CheckDrugInteractionsParams(BaseModel):
    """Parameters for check_drug_interactions tool."""

    drugs: list[str] = Field(..., description="List of drug names to check", min_length=1)
    patient_allergies: list[str] | None = Field(
        None, description="Known patient allergies or contraindications"
    )


class GenerateStructuredDiagnosisParams(BaseModel):
    """Parameters for generate_structured_diagnosis tool."""

    symptoms: str = Field(..., description="Patient-reported symptoms")
    patient_history: str | None = Field(None, description="Relevant medical history")
    test_results: str | None = Field(None, description="Lab or imaging results if available")
    knowledge_context: str | None = Field(
        None, description="Retrieved knowledge base context to cite"
    )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

class SearchMedicalKnowledgeTool(Tool):
    """Search the medical knowledge base for relevant guidelines and literature."""

    name = "search_medical_knowledge"
    description = (
        "Search the institutional medical knowledge base for clinical guidelines, "
        "research papers, drug information, or case reports relevant to a query. "
        "Use this when you need evidence-based information to support a diagnosis or treatment plan."
    )
    parameters = SearchKnowledgeParams

    async def execute(self, query: str, doc_type: str | None = None, top_k: int = 10) -> dict[str, Any]:
        # Deferred import to avoid circular deps at module load time
        from app.services.rag import RAGService
        from app.services.external_search import ExternalSearchAgent
        from app.services.config import DynamicConfigService
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.db.session import async_session_maker
        import logging

        logger = logging.getLogger(__name__)

        async with async_session_maker() as db:
            source_policy = await DynamicConfigService.knowledge_source_policy(db)
            internal_limit = source_policy["internal_candidates"]
            external_limit = min(source_policy["external_candidates"],
                                 max(0, await DynamicConfigService.external_search_max_results(db)))
            # 1. Search internal knowledge base
            rag = RAGService(db)
            from app.models.rag import DocType
            dt = DocType(doc_type) if doc_type else None
            try:
                chunks = await rag.search(query=query, doc_type=dt, top_k=internal_limit)
                # 报告稍后统一生成；这里只取原文，避免生成随后被丢弃的内部摘要。
                rag_result = {"sources": [{
                    "source_type": "internal", "title": c["document_title"],
                    "document_type": c["document_type"], "document_id": c["document_id"],
                    "chunk_id": c["chunk_id"], "chunk_index": c["chunk_index"],
                    "source_url": c.get("source_url"), "excerpt": c["content"], "relevance": c["rank"],
                } for c in chunks], "retrieved_chunks": len(chunks)}
                logger.info(f"[SEARXNG_DEBUG] RAG returned {len(rag_result.get('sources', []))} sources")
            except Exception as exc:
                logger.warning(f"[SEARXNG_DEBUG] RAG query failed: {type(exc).__name__}: {str(exc)[:200]}")
                rag_result = {"answer": "", "sources": [], "retrieved_chunks": 0}

            # 2. Search external SearXNG for real-time medical knowledge
            external_results, general_results = [], []
            if external_limit and await DynamicConfigService.external_search_enabled(db):
                external = await ExternalSearchAgent.from_config(db)
                external_results = await external.search_guidelines(query, lang="zh-CN")
                general_raw = await external._searxng_search(query, lang="zh-CN")
                general_results = external._filter_trusted(general_raw)
            logger.info(f"[SEARXNG_DEBUG] After filter: {len(general_results)} results")
            if await DynamicConfigService.external_search_trusted_only(db):
                external_results = [result for result in external_results if result.is_trusted]
                general_results = [result for result in general_results if result.is_trusted]
                logger.info(
                    "[SEARXNG_DEBUG] Trusted-only setting retained %d guideline and %d general results",
                    len(external_results), len(general_results),
                )
            if general_results:
                for i, r in enumerate(general_results[:3]):
                    logger.info(f"[SEARXNG_DEBUG]   Result {i+1}: score={r.trust_score}, title={r.title[:50]}")

            # Combine external results
            all_external = external_results + general_results
            # Deduplicate by URL
            seen_urls = set()
            unique_external = []
            for r in all_external:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    unique_external.append(r)

            # Format external results for LLM consumption
            external_chunks = [
                {
                    "source_type": "external",
                    "document_title": r.title or "External Source",
                    "content": f"{r.snippet}\nURL: {r.url}",
                    "document_type": "external_search",
                    "url": r.url,
                    "excerpt": r.snippet,
                    "source_engine": r.source_engine,
                    "trust_score": r.trust_score,
                    "relevance": None,
                    "is_trusted": r.is_trusted,
                }
                for r in unique_external[:external_limit]
            ]
            logger.info(f"[SEARXNG_DEBUG] Formatted {len(external_chunks)} external chunks")

            # Merge internal + external sources
            combined_sources = rag_result.get("sources", []) + [
                {
                    "source_type": c["source_type"],
                    "title": c["document_title"],
                    "type": c["document_type"],
                    "document_type": c["document_type"],
                    "url": c["url"],
                    "excerpt": c["excerpt"],
                    "source_engine": c["source_engine"],
                    "trust_score": c["trust_score"],
                    "is_trusted": c["is_trusted"],
                    "relevance": None,
                }
                for c in external_chunks
            ]

            # 两类来源按同一主题排序；被筛掉的资料也不能通过旧摘要绕过筛选。
            from app.services.knowledge_citations import build_knowledge_citations, rank_knowledge_citations
            candidates = build_knowledge_citations(combined_sources, max_citations=internal_limit + external_limit)
            ranked = (await rank_knowledge_citations(query, candidates, db, min_relevance=source_policy["min_relevance"]))[:top_k]
            combined_sources = [citation.model_dump() for citation in ranked]
            combined_answer = "\n\n".join(f"[来源: {citation.title}]\n{citation.excerpt}" for citation in ranked)

            logger.info(f"[SEARXNG_DEBUG] Final answer length: {len(combined_answer)} chars")

            return {
                "answer": combined_answer,
                "sources": combined_sources,
                "retrieved_chunks": rag_result.get("retrieved_chunks", 0) + len(external_chunks),
                "internal_sources": len(rag_result.get("sources", [])),
                "external_sources": len(external_chunks),
                "candidate_count": len(candidates),
                "selected_count": len(ranked),
            }


class QueryPatientHistoryTool(Tool):
    """Query a patient's medical case history."""

    name = "query_patient_history"
    description = (
        "Retrieve a patient's recent medical cases, diagnoses, and attached documents. "
        "Use this to understand the patient's baseline health status, chronic conditions, "
        "previous diagnoses, and ongoing treatments before making new recommendations."
    )
    parameters = QueryPatientHistoryParams

    async def execute(
        self, patient_id: str, limit: int = 5, include_documents: bool = False
    ) -> dict[str, Any]:
        import uuid
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.db.session import async_session_maker
        from app.models.medical_case import MedicalCase, MedicalDocument

        async with async_session_maker() as db:
            stmt = (
                select(MedicalCase)
                .where(MedicalCase.patient_id == uuid.UUID(patient_id))
                .order_by(MedicalCase.created_at.desc())
                .limit(limit)
            )
            result = await db.execute(stmt)
            cases = result.scalars().all()

            case_list = []
            for case in cases:
                case_data = {
                    "id": str(case.id),
                    "title": case.title,
                    "chief_complaint": case.chief_complaint,
                    "ai_diagnosis_summary": case.ai_diagnosis_summary,
                    "severity": case.severity,
                    "diagnosis_doctor": case.doctor_diagnosis,
                    "status": case.status.value,
                    "created_at": case.created_at.isoformat() if case.created_at else None,
                    "updated_at": case.updated_at.isoformat() if case.updated_at else None,
                }
                if include_documents:
                    doc_stmt = select(MedicalDocument).where(
                        MedicalDocument.case_id == case.id
                    )
                    doc_result = await db.execute(doc_stmt)
                    docs = doc_result.scalars().all()
                    case_data["documents"] = [
                        {
                            "id": str(d.id),
                            "doc_type": d.doc_type.value,
                            "title": d.title,
                            "description": d.description,
                        }
                        for d in docs
                    ]
                case_list.append(case_data)

            return {
                "patient_id": patient_id,
                "case_count": len(case_list),
                "cases": case_list,
            }


class CheckDrugInteractionsTool(Tool):
    """Check for drug-drug and drug-allergy interactions."""

    name = "check_drug_interactions"
    description = (
        "Check for potential interactions between multiple drugs and known patient allergies. "
        "Use this before recommending medications, especially when the patient is on multiple drugs "
        "or has known allergies. Returns a safety assessment with warnings."
    )
    parameters = CheckDrugInteractionsParams

    async def execute(
        self, drugs: list[str], patient_allergies: list[str] | None = None
    ) -> dict[str, Any]:
        # MVP: simplified rule-based check + LLM-powered analysis placeholder
        # Future: integrate with DrugBank or similar API
        warnings: list[str] = []
        allergies = patient_allergies or []

        # Simple heuristic checks
        drug_set = {d.lower().strip() for d in drugs}

        # Known common interaction pairs (simplified MVP rules)
        interaction_pairs = [
            ({"aspirin", "warfarin"}, "Increased bleeding risk when combining aspirin with warfarin."),
            ({"metformin", "contrast"}, "Risk of lactic acidosis with contrast media in metformin patients."),
            ({"ace inhibitor", "spironolactone"}, "Risk of hyperkalemia."),
            ({"nsaid", "ace inhibitor"}, "Reduced antihypertensive effect and renal risk."),
        ]

        for pair, warning in interaction_pairs:
            if len(pair & drug_set) >= 2:
                warnings.append(warning)

        # Allergy check
        for allergy in allergies:
            for drug in drugs:
                if allergy.lower() in drug.lower():
                    warnings.append(
                        f"CRITICAL: Patient is allergic to '{allergy}' which may be related to '{drug}'."
                    )

        return {
            "drugs_checked": drugs,
            "allergies_considered": allergies,
            "interaction_warnings": warnings,
            "safety_status": "caution" if warnings else "safe",
            "disclaimer": (
                "This is an automated preliminary check. Always verify with a pharmacist "
                "or clinical drug reference before prescribing."
            ),
        }


class GenerateStructuredDiagnosisTool(Tool):
    """Generate a structured, validated diagnosis report."""

    name = "generate_structured_diagnosis"
    description = (
        "Generate a formal structured diagnosis report based on collected symptoms, "
        "patient history, test results, and retrieved medical knowledge. "
        "Use this as the final step after gathering all necessary information."
    )
    parameters = GenerateStructuredDiagnosisParams

    async def execute(
        self,
        symptoms: str,
        patient_history: str | None = None,
        test_results: str | None = None,
        knowledge_context: str | None = None,
    ) -> dict[str, Any]:
        # This tool acts as a wrapper around the LLM with a strict structured-output prompt
        from app.services.llm import LLMService
        from app.db.session import async_session_maker

        system_prompt = """You are a medical diagnostic AI. Based on the provided information,
generate a structured diagnosis report in the exact JSON format below.

REQUIRED JSON STRUCTURE:
{
  "primary_diagnosis": "string (most likely diagnosis)",
  "differential_diagnoses": [
    {"diagnosis": "string", "icd11_code": "string", "reasoning": "string"}
  ],
  "confidence": "high|medium|low",
  "severity": "mild|moderate|severe|emergency",
  "key_findings": ["string"],
  "recommended_tests": ["string"],
  "recommended_actions": ["string"],
  "contraindications": ["string"],
  "follow_up_required": true|false,
  "follow_up_timeline": "string (e.g., '3 days')",
  "red_flags": ["string (symptoms requiring immediate care)"],
  "knowledge_sources": ["string"],
  "knowledge_evidence": [{"claim_path":"key_findings.0","citation_id":"S1","quote":"原文完整句"}]
}

RULES:
- Be specific and evidence-based.
- 引用仅可使用提供的[S1]等编号。knowledge_evidence只提供对应字段路径和完整原文句，不填核对状态或坐标；意译允许保留但须专业核对。不要为匹配摘录增加与本患者无关的内容。
- Always include the disclaimer that this is AI-assisted, not definitive.
- If information is insufficient, state so explicitly in key_findings.
- When onset or duration is unknown, do not classify symptoms as acute, subacute, or chronic from an assumed time span; use an uncertain symptom-based label and note the missing timing.
- For differential_diagnoses, always provide at least 2-5 alternatives with reasoning.
- For each diagnosis in primary_diagnosis and differential_diagnoses, provide the correct
  ICD-11 code in icd11_code (e.g., "J05.0" for acute laryngitis, "J00" for acute nasopharyngitis).
  Look up the standard ICD-11 code from your medical knowledge; do NOT leave icd11_code empty.
- Output ONLY valid JSON, no markdown formatting."""

        user_msg = f"症状: {symptoms}"
        if patient_history:
            user_msg += f"\n病史: {patient_history}"
        if test_results:
            user_msg += f"\n检查结果: {test_results}"
        if knowledge_context:
            user_msg += f"\n参考知识: {knowledge_context}"

        async with async_session_maker() as db:
            llm = LLMService(db=db)
            resp = await llm.chat(
                messages=[{"role": "user", "content": user_msg}],
                system_prompt=system_prompt,
                max_tokens=2048,
            )

            # Parse the JSON response
            import json
            try:
                report = json.loads(resp.content)
            except json.JSONDecodeError:
                # Fallback: wrap raw content
                report = {
                    "primary_diagnosis": "Parse error",
                    "raw_content": resp.content,
                    "confidence": "low",
                    "severity": "unknown",
                }

            return {
                "report": report,
                "model_used": resp.model,
                "disclaimer": (
                    "This report is generated by AI for reference only and does not "
                    "replace professional medical diagnosis."
                ),
            }


# ---------------------------------------------------------------------------
# Register all tools
# ---------------------------------------------------------------------------

search_medical_knowledge = register_tool(SearchMedicalKnowledgeTool())
query_patient_history = register_tool(QueryPatientHistoryTool())
check_drug_interactions = register_tool(CheckDrugInteractionsTool())
generate_structured_diagnosis = register_tool(GenerateStructuredDiagnosisTool())
