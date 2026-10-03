"""Deterministic preparation snapshots built only from one patient's case data."""

import hashlib
import json
from typing import Any

from app.models.patient_answer import (
    assertion_status,
    distinct_patient_answers,
    is_unknown_answer,
)
from app.services.department_guidance import (
    FOCUS_FACT_ID, PREPARATION_POLICY_VERSION, build_department_guidance,
)
from app.services.clinical_context import CONTEXT_POLICY_VERSION, add_context
from app.services.patient_profile import profile_records, profile_fact_value, SOURCE_LABELS

_FACT_LABELS = {
    "hpi_onset": "起病时间",
    "hpi_quality": "症状特点",
    "hpi_associated": "伴随症状",
    "pmh_allergy": "过敏史",
    "med_current": "当前用药",
}


def _answer_history(source: dict[str, Any], key: str, fallback: Any = None) -> list[str]:
    histories = source.get("raw_answer_history") or {}
    raw_answers = source.get("raw_answers") or {}
    recorded = histories.get(key, []) if isinstance(histories, dict) else []
    answers = [item for item in recorded if isinstance(item, str) and item.strip()] if isinstance(recorded, list) else []
    latest = raw_answers.get(key) if isinstance(raw_answers, dict) else None
    if isinstance(latest, str) and latest.strip() and (not answers or answers[-1] != latest):
        answers.append(latest)
    if not answers and fallback not in (None, "", [], {}):
        if isinstance(fallback, list) and all(isinstance(item, str) for item in fallback):
            answers.extend(item for item in fallback if item.strip())
        elif isinstance(fallback, str):
            answers.append(fallback)
        else:
            answers.append(json.dumps(fallback, ensure_ascii=False, default=str))
    return answers


def _answer_source_ids(source: dict[str, Any], key: str, answers: list[str]) -> list[str]:
    histories = source.get("raw_answer_history") or {}
    raw_answers = source.get("raw_answers") or {}
    recorded = histories.get(key, []) if isinstance(histories, dict) else []
    valid_history = [item for item in recorded if isinstance(item, str) and item.strip()] if isinstance(recorded, list) else []
    source_ids = [
        f"source_session.interview.raw_answer_history.{key}.{index}"
        for index in range(1, min(len(valid_history), len(answers)) + 1)
    ]
    latest = raw_answers.get(key) if isinstance(raw_answers, dict) else None
    if isinstance(latest, str) and latest.strip() and (not valid_history or valid_history[-1] != latest):
        source_ids.append(f"source_session.interview.raw_answers.{key}")
    return source_ids


def _unknown_fact_id(key: str) -> str:
    normalized = key.casefold()
    if "allerg" in normalized or "过敏" in key:
        return "unknown.allergies"
    if any(term in normalized for term in ("medication", "med_")) or any(
        term in key for term in ("用药", "药物")
    ):
        return "unknown.medications"
    return f"unknown.{key}"


def _fact_label(source: dict[str, Any], key: str) -> str:
    question_texts = source.get("question_texts") or {}
    question_text = question_texts.get(key) if isinstance(question_texts, dict) else None
    return str(question_text or _FACT_LABELS.get(key) or key)


def _make_unknown_fact(
    source: dict[str, Any],
    *,
    fact_id: str,
    key: str,
    fallback: Any = None,
    source_type: str = "patient_reported",
    source_id: str | None = None,
) -> dict[str, Any]:
    answers = _answer_history(source, key, fallback)
    return {
        "id": fact_id,
        "label": _fact_label(source, key),
        "status": "unknown",
        "answer_status": "unknown",
        "source_type": source_type,
        "source_id": source_id or f"source_session.interview.collected_info.{key}",
        "patient_response": answers[-1] if answers else None,
        "patient_response_history": answers,
        "patient_response_source_ids": _answer_source_ids(source, key, answers),
    }


def _build_unresolved_facts(source: dict[str, Any]) -> list[dict[str, Any]]:
    histories = source.get("raw_answer_history") or {}
    if not isinstance(histories, dict):
        return []
    unresolved = []
    for key, history in sorted(histories.items(), key=lambda pair: str(pair[0])):
        answers = _answer_history(source, str(key))
        if len(distinct_patient_answers(answers)) < 2:
            continue
        answer_source_ids = _answer_source_ids(source, str(key), answers)
        statements = []
        for index, answer in enumerate(answers, start=1):
            source_id = (
                answer_source_ids[index - 1]
                if index <= len(answer_source_ids)
                else f"source_session.interview.raw_answer_history.{key}.{index}"
            )
            statements.append({
                "value": answer,
                "source_type": "patient_reported",
                "source_id": source_id,
            })
        unresolved.append({
            "id": f"unresolved.{key}",
            "label": _fact_label(source, str(key)),
            "status": "needs_reconciliation",
            "source_type": "patient_reported",
            "source_id": f"source_session.interview.raw_answer_history.{key}",
            "statements": statements,
        })
    return unresolved


def canonical_fingerprint(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def preparation_fingerprint(source: dict[str, Any], corrections: list[dict[str, Any]]) -> str:
    # 规则更新也产生新快照，旧包不得继续伪装为当前建议。
    return canonical_fingerprint({
        "source": source, "patient_corrections": corrections,
        "preparation_policy_version": PREPARATION_POLICY_VERSION,
        "clinical_context_policy_version": CONTEXT_POLICY_VERSION,
    })


def source_fact_fingerprint(source: dict[str, Any], fact_id: str) -> str:
    package = build_package(source, [])
    fact = next((item for item in package["known_facts"] if item["id"] == fact_id), None)
    if fact is not None:
        return canonical_fingerprint({"source_id": fact["source_id"], "value": fact["value"]})
    unknown = next((item for item in package["unknown_facts"] if item["id"] == fact_id), None)
    if unknown is not None:
        return canonical_fingerprint({
            "fact_id": fact_id,
            "status": "unknown",
            "source_id": unknown.get("source_id"),
            "patient_response_history": unknown.get("patient_response_history", []),
        })
    unresolved = next(
        (item for item in package["unresolved_facts"] if item["id"] == fact_id), None
    )
    if unresolved is not None:
        return canonical_fingerprint({"fact_id": fact_id, "statements": unresolved["statements"]})
    return canonical_fingerprint({"fact_id": fact_id, "status": "provided"})


def build_source_snapshot(case, source_session, materials, patient_profile=None) -> dict[str, Any]:
    context = source_session.context or {} if source_session else {}
    interview = context.get("interview") or {}
    collected = interview.get("collected_info") or context.get("collected_info") or {}
    report = source_session.structured_output if source_session else None
    records = profile_records(patient_profile)
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
        "raw_answers": interview.get("raw_answers", {}) if isinstance(interview, dict) else {},
        "raw_answer_history": interview.get("raw_answer_history", {}) if isinstance(interview, dict) else {},
        "question_texts": interview.get("question_texts", {}) if isinstance(interview, dict) else {},
        "patient_profile": {
            "allergies": records["allergies"],
            "chronic_diseases": records["chronic_diseases"],
            "current_medications": [item for item in records["medications"] if item.get("status") != "stopped"],
            "stopped_medications": [item for item in records["medications"] if item.get("status") == "stopped"],
            "section_states": records["section_states"],
            "section_metadata": records["section_metadata"],
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
        and not is_unknown_answer(value)
        for key, value in facts.items()
    )


def build_package(source: dict[str, Any], corrections: list[dict[str, Any]]) -> dict[str, Any]:
    case = source["case"]
    patient_facts = source["patient_facts"]
    report = source["report"] or {}
    corrections_by_fact = {item["fact_id"]: item["value"] for item in corrections}
    unresolved_facts = _build_unresolved_facts(source)
    unresolved_keys = {item["id"].removeprefix("unresolved.") for item in unresolved_facts}
    known_facts: list[dict[str, Any]] = []
    unknown_by_id: dict[str, dict[str, Any]] = {}
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
        key = str(key)
        if key.startswith("__"):
            continue
        if key in unresolved_keys:
            continue
        answers = _answer_history(source, key, value)
        if is_unknown_answer(value):
            fact_id = _unknown_fact_id(key)
            unknown_by_id.setdefault(
                fact_id,
                _make_unknown_fact(
                    source,
                    fact_id=fact_id,
                    key=key,
                    fallback=value,
                ),
            )
            continue
        known_facts.append({
            "id": f"patient.reported.{key}",
            "label": _fact_label(source, key),
            "value": value,
            "source_type": "patient_reported",
            "source_id": f"source_session.interview.collected_info.{key}",
            "assertion_status": assertion_status(value),
            "patient_response": answers[-1] if answers else None,
            "patient_response_history": answers,
            "patient_response_source_ids": _answer_source_ids(source, key, answers),
            "confirmed": False,
        })
    profile = source.get("patient_profile") or {}
    profile_facts = (
        ("allergies", "过敏史", profile.get("allergies")),
        ("chronic_diseases", "慢性病／特殊疾病", profile.get("chronic_diseases")),
        ("current_medications", "当前用药", profile.get("current_medications")),
        ("stopped_medications", "已停用药物（历史记录）", profile.get("stopped_medications")),
    )
    resolved_profile_facts = []
    profile_sections = {"allergies": "allergies", "chronic_diseases": "conditions", "current_medications": "medications", "stopped_medications": "medications"}
    for key, label, value in profile_facts:
        section = profile_sections[key]
        meta = (profile.get("section_metadata") or {}).get(section) or {}
        if key != "stopped_medications" and (profile.get("section_states") or {}).get(section) == "none":
            value = "患者明确自报无"
        resolved_profile_facts.append((key, label, value))
        if value in (None, "", [], {}):
            continue
        if is_unknown_answer(value):
            fact_id = _unknown_fact_id(f"patient_profile.{key}")
            unknown_by_id.setdefault(
                fact_id,
                _make_unknown_fact(
                    source,
                    fact_id=fact_id,
                    key=f"patient_profile.{key}",
                    fallback=value,
                    source_id=f"patient_profile.{key}",
                ),
            )
            continue
        known_facts.append({
            "id": f"patient.profile.{key}",
            "label": label,
            "value": value,
            "display_value": profile_fact_value(key, value),
            "record_state": (profile.get("section_states") or {}).get(section),
            "source_type": meta.get("source", "legacy_record"),
            "updated_at": meta.get("updated_at"),
            "source_id": f"patient_profile.{key}",
            "assertion_status": "denied" if key != "stopped_medications" and (profile.get("section_states") or {}).get(section) == "none" else assertion_status(value),
            "confirmed": False,
        })
    for fact in known_facts:
        fact["active"] = fact["id"] not in corrections_by_fact
        if not fact["active"]:
            fact["corrected_by"] = f"correction.{fact['id']}"
    fact_labels = {fact["id"]: fact["label"] for fact in [*known_facts, *unknown_by_id.values(), *unresolved_facts]}
    fact_labels[FOCUS_FACT_ID] = "主要咨询问题"
    for correction in corrections:
        known_facts.append({
            "id": f"correction.{correction['fact_id']}",
            "label": fact_labels.get(correction["fact_id"], "患者补充"),
            "value": correction["value"],
            "source_type": "patient_correction",
            "source_id": correction["fact_id"],
            "confirmed": True,
            "active": True,
            "replaces_fact_id": correction["fact_id"],
        })

    profile_has_allergies = profile.get("allergies") not in (None, "", [], {}) or (profile.get("section_states") or {}).get("allergies") == "none"
    profile_has_medications = profile.get("current_medications") not in (None, "", [], {}) or (profile.get("section_states") or {}).get("medications") == "none"
    if (
        not _has_fact(patient_facts, "allerg", "过敏")
        and (not profile_has_allergies or is_unknown_answer(profile.get("allergies")))
        and "unknown.allergies" not in corrections_by_fact
    ):
        if "unknown.allergies" not in unknown_by_id:
            unknown_by_id["unknown.allergies"] = {
                **_make_unknown_fact(source, fact_id="unknown.allergies", key="pmh_allergy", source_id="patient_profile.allergies"),
                "record_state": (profile.get("section_states") or {}).get("allergies", "not_recorded"),
            }
    if (
        not _has_fact(patient_facts, "medication", "用药", "药物")
        and (not profile_has_medications or is_unknown_answer(profile.get("current_medications")))
        and "unknown.medications" not in corrections_by_fact
    ):
        if "unknown.medications" not in unknown_by_id:
            unknown_by_id["unknown.medications"] = {
                **_make_unknown_fact(source, fact_id="unknown.medications", key="med_current", source_id="patient_profile.current_medications"),
                "record_state": (profile.get("section_states") or {}).get("medications", "not_recorded"),
            }
    condition_state = (profile.get("section_states") or {}).get("conditions")
    if condition_state in {"unknown", "not_recorded"} and "unknown.conditions" not in corrections_by_fact:
        unknown_by_id["unknown.conditions"] = {
            **_make_unknown_fact(source, fact_id="unknown.conditions", key="patient_profile.chronic_diseases", source_id="patient_profile.chronic_diseases"),
            "label": "慢性病／特殊疾病", "record_state": condition_state,
        }
    unknown_facts = list(unknown_by_id.values())
    department = build_department_guidance(source, corrections, unresolved_facts)
    if department["focus_question"] and department["status"] in {"general_consultation", "needs_clarification"} and FOCUS_FACT_ID not in corrections_by_fact:
        unknown_facts.append({
            "id": FOCUS_FACT_ID, "label": "这次主要想咨询哪类问题？",
            "status": "unknown", "answer_status": "unknown",
            "source_type": "patient_reported", "source_id": FOCUS_FACT_ID,
        })

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
    for key, label, value in resolved_profile_facts:
        if value not in (None, "", [], {}) and not is_unknown_answer(value):
            meta = (profile.get("section_metadata") or {}).get(profile_sections[key]) or {}
            source_index.append({
                "id": f"patient_profile.{key}",
                "source_type": meta.get("source", "legacy_record"),
                "name": f"患者资料：{label}",
                "verified_citation": False,
                "note": f"来源：{SOURCE_LABELS.get(meta.get('source'), '来源未记录')}；更新时间：{meta.get('updated_at') or '未记录'}。各条记录保留自身来源，尚未由医生核验。",
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

    for fact in known_facts:
        add_context(fact)
    for fact in unknown_facts:
        add_context(fact, withheld="unknown")
    for fact in unresolved_facts:
        for statement in fact["statements"]:
            add_context(statement, withheld="needs_review")

    return {
        "profile_record_states": profile.get("section_states") or {},
        "preparation_policy_version": PREPARATION_POLICY_VERSION,
        "clinical_context_policy_version": CONTEXT_POLICY_VERSION,
        "known_facts": known_facts,
        "unknown_facts": unknown_facts,
        "unresolved_facts": unresolved_facts,
        "department": department,
        "preparation_items": preparation_items,
        "source_index": source_index,
        "unverified_knowledge_sources": unverified_knowledge_sources,
        "patient_questions": [],
        "summary": {
            "case_title": case["title"],
            "patient_facts": known_facts,
            "unknown_facts": unknown_facts,
            "unresolved_facts": unresolved_facts,
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
