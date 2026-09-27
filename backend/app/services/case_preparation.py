"""Deterministic preparation snapshots built only from one patient's case data."""

import hashlib
import json
from typing import Any


def canonical_fingerprint(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def source_fact_fingerprint(source: dict[str, Any], fact_id: str) -> str:
    package = build_package(source, [])
    fact = next((item for item in package["known_facts"] if item["id"] == fact_id), None)
    if fact is not None:
        return canonical_fingerprint({"source_id": fact["source_id"], "value": fact["value"]})
    unknown = next((item for item in package["unknown_facts"] if item["id"] == fact_id), None)
    return canonical_fingerprint({"fact_id": fact_id, "status": "unknown" if unknown else "provided"})


def build_source_snapshot(case, source_session, materials, patient_profile=None) -> dict[str, Any]:
    context = source_session.context or {} if source_session else {}
    interview = context.get("interview") or {}
    collected = interview.get("collected_info") or context.get("collected_info") or {}
    report = source_session.structured_output if source_session else None
    return {
        "case": {
            "id": str(case.id),
            "title": case.title,
            "chief_complaint": case.chief_complaint,
            "ai_diagnosis_summary": case.ai_diagnosis_summary,
            "severity": case.severity,
            "is_emergency": case.is_emergency,
        },
        "source_session_id": str(source_session.id) if source_session else None,
        "patient_facts": collected if isinstance(collected, dict) else {},
        "patient_profile": {
            "allergies": patient_profile.allergies if patient_profile else None,
            "current_medications": patient_profile.current_medications if patient_profile else None,
        },
        "report": report if isinstance(report, dict) else None,
        "materials": [
            {
                "file_id": item.file_id,
                "filename": item.filename,
                "status": item.status,
                "result": item.result if item.status == "completed" else None,
            }
            for item in sorted(materials, key=lambda item: item.file_id)
        ],
    }


def _has_fact(facts: dict[str, Any], *terms: str) -> bool:
    return any(
        any(term in str(key).casefold() for term in terms)
        and value not in (None, "", [], {})
        for key, value in facts.items()
    )


def build_package(source: dict[str, Any], corrections: list[dict[str, Any]]) -> dict[str, Any]:
    case = source["case"]
    patient_facts = source["patient_facts"]
    report = source["report"] or {}
    known_facts: list[dict[str, Any]] = []
    if case.get("chief_complaint"):
        known_facts.append({
            "id": "patient.chief_complaint",
            "label": "本次主要诉求",
            "value": case["chief_complaint"],
            "source_type": "patient_reported",
            "source_id": "case.chief_complaint",
            "confirmed": False,
        })
    for key, value in sorted(patient_facts.items(), key=lambda pair: str(pair[0])):
        if value in (None, "", [], {}):
            continue
        known_facts.append({
            "id": f"patient.reported.{key}",
            "label": str(key),
            "value": value,
            "source_type": "patient_reported",
            "source_id": f"source_session.interview.collected_info.{key}",
            "confirmed": False,
        })
    profile = source.get("patient_profile") or {}
    profile_facts = (
        ("allergies", "过敏史", profile.get("allergies")),
        ("current_medications", "当前用药", profile.get("current_medications")),
    )
    for key, label, value in profile_facts:
        if value in (None, "", [], {}):
            continue
        known_facts.append({
            "id": f"patient.profile.{key}",
            "label": label,
            "value": value,
            "source_type": "patient_reported",
            "source_id": f"patient_profile.{key}",
            "confirmed": False,
        })
    correction_by_fact = {item["fact_id"]: item["value"] for item in corrections}
    for fact in known_facts:
        fact["active"] = fact["id"] not in correction_by_fact
        if not fact["active"]:
            fact["corrected_by"] = f"correction.{fact['id']}"
    for correction in corrections:
        known_facts.append({
            "id": f"correction.{correction['fact_id']}",
            "label": f"更正：{correction['fact_id']}",
            "value": correction["value"],
            "source_type": "patient_correction",
            "source_id": correction["fact_id"],
            "confirmed": True,
            "active": True,
            "replaces_fact_id": correction["fact_id"],
        })

    profile_has_allergies = profile.get("allergies") not in (None, "", [], {})
    profile_has_medications = profile.get("current_medications") not in (None, "", [], {})
    unknown_facts = []
    if not _has_fact(patient_facts, "allerg", "过敏") and not profile_has_allergies and "unknown.allergies" not in correction_by_fact:
        unknown_facts.append({"id": "unknown.allergies", "label": "过敏史", "status": "unknown"})
    if not _has_fact(patient_facts, "medication", "用药", "药物") and not profile_has_medications and "unknown.medications" not in correction_by_fact:
        unknown_facts.append({"id": "unknown.medications", "label": "当前用药", "status": "unknown"})

    materials = source["materials"]
    preparation_items = [
        {
            "id": f"material.{item['file_id']}",
            "title": f"携带已有资料：{item['filename']}",
            "reason": "这是本病例已关联的上传资料；解析状态不代表医生已核对。",
            "source_file_ids": [item["file_id"]],
            "status": "pending",
        }
        for item in materials
    ]
    preparation_items.extend([
        {
            "id": "organize.current_medications",
            "title": "核对当前用药情况",
            "reason": "供患者自行补充或向医生核对；本项不是停药或调整用药指示。",
            "source_file_ids": [],
            "status": "pending",
        },
        {
            "id": "prepare.questions",
            "title": "记录希望向医生询问的问题",
            "reason": "由患者自行填写；系统不生成诊疗指令。",
            "source_file_ids": [],
            "status": "pending",
        },
    ])

    primary = report.get("primary_diagnosis")
    findings = report.get("key_findings")
    ai_findings = []
    if primary:
        ai_findings.append(str(primary))
    if isinstance(findings, list):
        ai_findings.extend(str(item) for item in findings if item)

    source_index = []
    if source.get("source_session_id") and report:
        source_index.append({
            "id": "source_session.report",
            "source_type": "ai_inference",
            "name": "AI 结构化报告",
            "source_session_id": source["source_session_id"],
            "verified_citation": False,
            "note": "报告内容为 AI 分析，未经医生确认。",
        })
    for key, label, value in profile_facts:
        if value not in (None, "", [], {}):
            source_index.append({
                "id": f"patient_profile.{key}",
                "source_type": "patient_reported",
                "name": f"患者资料：{label}",
                "verified_citation": False,
                "note": "来自患者本人维护的资料，尚未由医生核验。",
            })
    for item in materials:
        source_index.append({
            "id": f"material.{item['file_id']}",
            "source_type": "uploaded_material",
            "file_id": item["file_id"],
            "name": item["filename"],
            "parse_status": item["status"],
            "verified_citation": False,
            "note": "患者上传的原始资料；解析结果不代表医生已核对。",
        })
    unverified_knowledge_sources = [
        {"name": str(name), "verified_citation": False,
         "note": "当前报告仅保存来源名称，缺少发布机构、版本和原文定位。"}
        for name in report.get("knowledge_sources", [])
        if name
    ] if isinstance(report.get("knowledge_sources"), list) else []

    return {
        "known_facts": known_facts,
        "unknown_facts": unknown_facts,
        "department": {
            "status": "insufficient_evidence",
            "recommendation": None,
            "reason": "当前报告没有结构化且可核查的科室依据；不能只凭 AI 诊断名称推导科室。",
            "evidence_ids": [],
        },
        "preparation_items": preparation_items,
        "source_index": source_index,
        "unverified_knowledge_sources": unverified_knowledge_sources,
        "patient_questions": [],
        "summary": {
            "case_title": case["title"],
            "patient_facts": known_facts,
            "unknown_facts": unknown_facts,
            "ai_inference": ai_findings,
            "materials": [
                {"file_id": item["file_id"], "filename": item["filename"], "status": item["status"]}
                for item in materials
            ],
            "source_index": source_index,
            "unverified_knowledge_sources": unverified_knowledge_sources,
            "disclaimer": "患者自述、资料解析与 AI 推断分开展示；患者核对不等于医生确认。",
        },
        "patient_corrections": corrections,
    }
