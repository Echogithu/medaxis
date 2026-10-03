"""Medical Interview — Mesh-Architecture Clinical Engine.

DESIGN PRINCIPLES:
1. Non-linear, network-structured clinical reasoning
2. Agent simultaneously manages: questioning, knowledge search, differential diagnosis
3. Questioning + searching are interleaved — search can trigger new questions
4. Follows Chinese Medical History Taking (病史采集) standard as reference framework
5. No hardcoded question scripts — LLM drives all decisions via prompt engineering
6. Two integrated modules: 基本问诊 (Basic) → 精细化问诊 (Advanced)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum as PyEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.patient_answer import assertion_status, is_unknown_answer


# ---------------------------------------------------------------------------
# Interview Phase Definitions (information categories only — NOT sequential)
# ---------------------------------------------------------------------------

class InterviewPhase(str, PyEnum):
    """Clinical information categories. These are NOT a fixed sequence."""

    # Present Illness
    HPI_ONSET = "hpi_onset"
    HPI_QUALITY = "hpi_quality"
    HPI_LOCATION = "hpi_location"
    HPI_SEVERITY = "hpi_severity"
    HPI_TIMING = "hpi_timing"
    HPI_AGGRAVATE = "hpi_aggravate"
    HPI_ASSOCIATED = "hpi_associated"
    HPI_TREATMENT = "hpi_treatment"

    # Past Medical History
    PMH_CHRONIC = "pmh_chronic"
    PMH_SURGERY = "pmh_surgery"
    PMH_INFECTION = "pmh_infection"
    PMH_ALLERGY = "pmh_allergy"

    # Personal History
    PS_LIFESTYLE = "ps_lifestyle"
    PS_OCCUPATION = "ps_occupation"
    PS_TRAVEL = "ps_travel"
    PS_GENERAL = "ps_general"

    # Special Populations
    PS_CHILD = "ps_child"
    PS_FEMALE = "ps_female"

    # Family History
    FH_GENETIC = "fh_genetic"
    FH_SIMILAR = "fh_similar"

    # Medication History
    MED_CURRENT = "med_current"
    MED_RECENT = "med_recent"

    # Terminal
    COMPLETE = "complete"


# Phase metadata: medical ID → { category, colloquial_category }
PHASE_META: dict[InterviewPhase, dict[str, str]] = {
    InterviewPhase.HPI_ONSET:     {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_QUALITY:   {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_LOCATION:  {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_SEVERITY:  {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_TIMING:    {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_AGGRAVATE: {"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_ASSOCIATED:{"cat": "现病史", "colloquial": "症状情况"},
    InterviewPhase.HPI_TREATMENT: {"cat": "现病史", "colloquial": "就诊情况"},
    InterviewPhase.PMH_CHRONIC:   {"cat": "既往史", "colloquial": "健康状况"},
    InterviewPhase.PMH_SURGERY:   {"cat": "既往史", "colloquial": "健康状况"},
    InterviewPhase.PMH_INFECTION: {"cat": "既往史", "colloquial": "健康状况"},
    InterviewPhase.PMH_ALLERGY:   {"cat": "既往史", "colloquial": "过敏情况"},
    InterviewPhase.PS_LIFESTYLE:  {"cat": "个人史", "colloquial": "生活习惯"},
    InterviewPhase.PS_OCCUPATION: {"cat": "个人史", "colloquial": "工作生活"},
    InterviewPhase.PS_TRAVEL:     {"cat": "个人史", "colloquial": "出行情况"},
    InterviewPhase.PS_GENERAL:    {"cat": "个人史", "colloquial": "一般情况"},
    InterviewPhase.PS_CHILD:      {"cat": "个人史", "colloquial": "儿童发育"},
    InterviewPhase.PS_FEMALE:     {"cat": "个人史", "colloquial": "女性健康"},
    InterviewPhase.FH_GENETIC:    {"cat": "家族史", "colloquial": "家人健康"},
    InterviewPhase.FH_SIMILAR:    {"cat": "家族史", "colloquial": "家人健康"},
    InterviewPhase.MED_CURRENT:   {"cat": "用药史", "colloquial": "用药情况"},
    InterviewPhase.MED_RECENT:    {"cat": "用药史", "colloquial": "用药情况"},
}


# Optional reference order for completeness checking (NOT a strict sequence)
PHASE_ORDER: list[InterviewPhase] = [
    InterviewPhase.HPI_ONSET,
    InterviewPhase.HPI_QUALITY,
    InterviewPhase.HPI_LOCATION,
    InterviewPhase.HPI_SEVERITY,
    InterviewPhase.HPI_TIMING,
    InterviewPhase.HPI_AGGRAVATE,
    InterviewPhase.HPI_ASSOCIATED,
    InterviewPhase.HPI_TREATMENT,
    InterviewPhase.PMH_CHRONIC,
    InterviewPhase.PMH_SURGERY,
    InterviewPhase.PMH_INFECTION,
    InterviewPhase.PMH_ALLERGY,
    InterviewPhase.PS_LIFESTYLE,
    InterviewPhase.PS_OCCUPATION,
    InterviewPhase.PS_TRAVEL,
    InterviewPhase.PS_GENERAL,
    InterviewPhase.PS_CHILD,
    InterviewPhase.PS_FEMALE,
    InterviewPhase.FH_GENETIC,
    InterviewPhase.FH_SIMILAR,
    InterviewPhase.MED_CURRENT,
    InterviewPhase.MED_RECENT,
]


# ---------------------------------------------------------------------------
# Content Fingerprint for Dedup
# ---------------------------------------------------------------------------

def _fingerprint(text: str) -> str:
    """Normalized content fingerprint for duplicate question detection.

    Strips punctuation, collapses whitespace, lowercases, then SHA256 hashes.
    Two questions with the same normalized text produce the same fingerprint.
    """
    clean = re.sub(r'[^\u4e00-\u9fff\w]', '', text.lower())
    clean = re.sub(r'\s+', '', clean)
    return hashlib.sha256(clean.encode('utf-8')).hexdigest()[:12]


def _extract_phase_key(question_id: str) -> str:
    """Extract a stable clinical phase key from a question_id.

    Maps question_id prefixes to clinical dimensions.  Examples:
      hpi_onset_001 → hpi_onset    pmh_allergy → pmh_allergy
      adv_dehydration_001 → adv_dehydration    cq_5 → cq_5
    """
    known_prefixes = ("hpi_", "pmh_", "ps_", "fh_", "med_")
    for prefix in known_prefixes:
        if question_id.startswith(prefix):
            parts = question_id.split("_")
            if len(parts) >= 2:
                return f"{parts[0]}_{parts[1]}"
            return question_id
    if question_id.startswith("adv_"):
        # 仅去除发题序号；stool_pattern 与 stool_frequency 是不同的信息。
        return re.sub(r"_\d+$", "", question_id)
    return question_id


# ---------------------------------------------------------------------------
# Differential Diagnosis Models
# ---------------------------------------------------------------------------

@dataclass
class DifferentialHypothesis:
    """A single differential diagnosis hypothesis maintained by the Agent."""

    diagnosis: str
    confidence: str = "low"  # high | medium | low
    key_features: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    refuting_evidence: list[str] = field(default_factory=list)
    reason: str = ""  # Why this diagnosis is considered

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis": self.diagnosis,
            "confidence": self.confidence,
            "key_features": self.key_features,
            "supporting_evidence": self.supporting_evidence,
            "refuting_evidence": self.refuting_evidence,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DifferentialHypothesis":
        return cls(
            diagnosis=data.get("diagnosis", ""),
            confidence=data.get("confidence", "low"),
            key_features=data.get("key_features", []),
            supporting_evidence=data.get("supporting_evidence", []),
            refuting_evidence=data.get("refuting_evidence", []),
            reason=data.get("reason", ""),
        )


@dataclass
class QuestionTemplate:
    """A single interview question."""

    question_id: str
    question: str
    type: str  # "choice", "multi_choice", or "text"
    options: list[str] = field(default_factory=list)
    hint: str = ""
    allow_skip: bool = True
    phase: str = ""
    colloquial_phase: str = ""
    information_key: str = ""
    priority: str = "essential"
    reason: str = ""


@dataclass
class InterviewState:
    """Snapshot of an ongoing interview stored in AgentSession.context."""

    chief_complaint: str = ""
    # Structured collected info keyed by phase ID
    collected_info: dict[str, Any] = field(default_factory=dict)
    # Natural language answers keyed by phase ID
    raw_answers: dict[str, str] = field(default_factory=dict)
    # Ordered patient statements are retained so later answers do not erase earlier ones.
    raw_answer_history: dict[str, list[str]] = field(default_factory=dict)
    asked_questions: list[str] = field(default_factory=list)
    current_question_id: str | None = None
    is_sufficient: bool = False
    current_phase_index: int = 0     # Kept for backward compat; not used as sequence constraint
    red_flags_detected: list[str] = field(default_factory=list)
    # Tool calls made during interview
    interview_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # Anti-loop: stagnation detection
    stagnation_counter: int = 0      # Consecutive rounds without new info
    last_collected_count: int = 0    # Info dimension count in last round
    pending_question_ids: list[str] = field(default_factory=list)  # Unanswered from current round
    # User explicitly ended interview
    user_ended: bool = False
    # Interview phase tracking
    phase: str = "interviewing"      # interviewing | diagnosing | followup | completed
    # Content fingerprint dedup: short hashes of normalized question texts
    asked_question_fingerprints: list[str] = field(default_factory=list)
    # Phase-level dedup: maps question_id → clinical phase key (e.g. hpi_onset)
    question_phase_keys: dict[str, str] = field(default_factory=dict)
    # LLM-level dedup: maps question_id → original question text for semantic comparison
    question_texts: dict[str, str] = field(default_factory=dict)
    # Regeneration control: max 1 regeneration after initial diagnosis
    regeneration_count: int = 0
    # Lab reports from multimodal parsing (Track 3)
    lab_reports: list[dict[str, Any]] = field(default_factory=list)
    # Frontend session ID for bridge lookups (not persisted, set at interview creation)
    _frontend_sid: str = ""
    # 保留原文出处；与模型推断及发题历史分开，旧会话缺字段时按现有数据恢复。
    known_information: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    interview_policy: dict[str, int] = field(default_factory=dict)
    interview_rounds: int = 0
    stop_reason: str = ""
    information_gaps: list[str] = field(default_factory=list)
    generation_action: str = "ask"
    last_information_fingerprint: str = ""
    clarification_keys: list[str] = field(default_factory=list)
    clarification_question_ids: dict[str, str] = field(default_factory=dict)
    resolved_information: dict[str, dict[str, str]] = field(default_factory=dict)

    # Internal keys for storing differential diagnosis info in collected_info (DB compatibility)
    _DIFF_KEY = "__differential_diagnoses__"
    _FEATURES_KEY = "__confirmed_features__"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chief_complaint": self.chief_complaint,
            "collected_info": self.collected_info,
            "raw_answers": self.raw_answers,
            "raw_answer_history": self.raw_answer_history,
            "asked_questions": self.asked_questions,
            "current_question_id": self.current_question_id,
            "is_sufficient": self.is_sufficient,
            "current_phase_index": self.current_phase_index,
            "red_flags_detected": self.red_flags_detected,
            "interview_tool_calls": self.interview_tool_calls,
            "stagnation_counter": self.stagnation_counter,
            "last_collected_count": self.last_collected_count,
            "pending_question_ids": self.pending_question_ids,
            "user_ended": self.user_ended,
            "phase": self.phase,
            "asked_question_fingerprints": self.asked_question_fingerprints,
            "question_phase_keys": self.question_phase_keys,
            "question_texts": self.question_texts,
            "regeneration_count": self.regeneration_count,
            "lab_reports": self.lab_reports,
            "known_information": self.known_information,
            "interview_policy": self.interview_policy,
            "interview_rounds": self.interview_rounds,
            "stop_reason": self.stop_reason,
            "information_gaps": self.information_gaps,
            "generation_action": self.generation_action,
            "last_information_fingerprint": self.last_information_fingerprint,
            "clarification_keys": self.clarification_keys,
            "clarification_question_ids": self.clarification_question_ids,
            "resolved_information": self.resolved_information,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterviewState":
        return cls(
            chief_complaint=data.get("chief_complaint", ""),
            collected_info=data.get("collected_info", {}),
            raw_answers=data.get("raw_answers", {}),
            raw_answer_history=data.get("raw_answer_history", {}),
            asked_questions=data.get("asked_questions", []),
            current_question_id=data.get("current_question_id"),
            is_sufficient=data.get("is_sufficient", False),
            current_phase_index=data.get("current_phase_index", 0),
            red_flags_detected=data.get("red_flags_detected", []),
            interview_tool_calls=data.get("interview_tool_calls", []),
            stagnation_counter=data.get("stagnation_counter", 0),
            last_collected_count=data.get("last_collected_count", 0),
            pending_question_ids=data.get("pending_question_ids", []),
            user_ended=data.get("user_ended", False),
            phase=data.get("phase", "interviewing"),
            asked_question_fingerprints=data.get("asked_question_fingerprints", []),
            question_phase_keys=data.get("question_phase_keys", {}),
            question_texts=data.get("question_texts", {}),
            regeneration_count=(data.get("regeneration_count") or 0),
            lab_reports=data.get("lab_reports", []),
            known_information=data.get("known_information", {}),
            interview_policy=data.get("interview_policy", {}),
            interview_rounds=data.get("interview_rounds", 0),
            stop_reason=data.get("stop_reason", ""),
            information_gaps=data.get("information_gaps", []),
            generation_action=data.get("generation_action", "ask"),
            last_information_fingerprint=data.get("last_information_fingerprint", ""),
            clarification_keys=data.get("clarification_keys", []),
            clarification_question_ids=data.get("clarification_question_ids", {}),
            resolved_information=data.get("resolved_information", {}),
        )

    # ---- Differential diagnosis helpers (store in collected_info for compatibility) ----

    def get_differential_diagnoses(self) -> list[DifferentialHypothesis]:
        raw = self.collected_info.get(self._DIFF_KEY, [])
        if isinstance(raw, list):
            return [DifferentialHypothesis.from_dict(d) for d in raw]
        return []

    def set_differential_diagnoses(self, diffs: list[DifferentialHypothesis]) -> None:
        self.collected_info[self._DIFF_KEY] = [d.to_dict() for d in diffs]

    def get_confirmed_features(self) -> dict[str, Any]:
        return self.collected_info.get(self._FEATURES_KEY, {})

    def set_confirmed_features(self, features: dict[str, Any]) -> None:
        self.collected_info[self._FEATURES_KEY] = features

    def record_patient_answer(self, question_id: str, answer: str) -> None:
        """Keep each distinct patient statement while retaining the latest raw-answer field."""
        history = self.raw_answer_history.setdefault(question_id, [])
        previous = self.raw_answers.get(question_id)
        if previous and (not history or history[-1] != previous):
            history.append(previous)
        if not history or history[-1] != answer:
            history.append(answer)
        self.raw_answers[question_id] = answer
        self.pending_question_ids = [qid for qid in self.pending_question_ids if qid != question_id]
        key = _extract_phase_key(self.question_phase_keys.get(question_id) or question_id)
        self.remember_information(key, answer, "answer", question_id)
        current = self.resolved_information.get(key)
        if current and current["quote"].strip() != answer.strip():
            self.resolved_information.pop(key, None)
        if self.clarification_question_ids.get(question_id) == key:
            from app.services.clinical_context import annotate_patient_text
            uncertain = is_unknown_answer(answer) or any(
                clause["status"] in {"unknown", "uncertain", "hypothetical", "non_patient", "needs_review"}
                for clause in annotate_patient_text(answer))
            if not uncertain:
                self.resolved_information[key] = {"quote": answer, "question_id": question_id,
                                                  "status": assertion_status(answer)}
                self.information_gaps = [gap for gap in self.information_gaps
                                         if gap not in {f"{key}：先后资料不一致，待核对", f"{key}：患者尚未确认"}]

    def unanswered_question_ids(self) -> list[str]:
        """发题历史不是回答记录；旧会话也按已有原话/采集值恢复待答集合。"""
        issued = dict.fromkeys([*self.pending_question_ids, *self.question_texts])
        return [qid for qid in issued if qid not in self.raw_answers and qid not in self.collected_info]

    def remember_information(self, key: str, quote: str, source: str, source_id: str = "") -> None:
        """存原话而非模型改写；重复出处不累加，未知保持未知。"""
        from datetime import datetime, timezone
        if not quote.strip():
            return
        row = {"quote": quote, "source": source, "source_id": source_id,
               "status": "unknown" if is_unknown_answer(quote) else assertion_status(quote)}
        rows = self.known_information.setdefault(_extract_phase_key(key), [])
        if not any(all(old.get(k) == v for k, v in row.items()) for old in rows):
            rows.append({**row, "recorded_at": datetime.now(timezone.utc).isoformat()})

    def refresh_known_information(self) -> None:
        """恢复旧会话；优先患者原话，不把旧模型的抽取值升级为患者确认。"""
        for key, value in self.collected_info.items():
            dimension = self.question_phase_keys.get(key) or _extract_phase_key(key)
            if key.startswith("__") or any((self.question_phase_keys.get(qid) or _extract_phase_key(qid)) == dimension
                                            for qid in self.raw_answers):
                continue
            if value is not None and value != "asked_by_track1":
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                self.remember_information(dimension, text, "collected_info", key)
        for key, answer in self.raw_answers.items():
            for text in self.raw_answer_history.get(key) or [answer]:
                self.remember_information(self.question_phase_keys.get(key) or key, text, "answer", key)

    def information_status(self, key: str) -> str:
        key = _extract_phase_key(key)
        resolved = self.resolved_information.get(key)
        if resolved:
            return resolved["status"]
        rows = self.known_information.get(key, [])
        if not rows:
            return "not_recorded"
        # 同一病史维度可以包含多种疾病/药物；原话不同本身不是矛盾。
        if self._has_information_conflict(key, rows):
            return "needs_review"
        confirmed = [row for row in rows if row.get("status") != "unknown"]
        return (confirmed or rows)[-1].get("status", "reported")

    @staticmethod
    def _has_information_conflict(key: str, rows: list[dict]) -> bool:
        confirmed = [row for row in rows if row.get("status") != "unknown" and row.get("quote")]
        statements = {re.sub(r"\s+", "", row["quote"]).strip("。；， ") for row in confirmed}
        if len(statements) < 2 or any(all(text in larger for text in statements) for larger in statements):
            return False
        # 同一道题的修订回答仍需核对，不能静默覆盖历史。
        by_answer: dict[str, set[str]] = {}
        for row in confirmed:
            if row.get("source") == "answer" and row.get("source_id"):
                by_answer.setdefault(row["source_id"], set()).add(row["quote"].strip())
        if any(len(values) > 1 for values in by_answer.values()):
            return True
        if any(row.get("status") == "denied" for row in confirmed) and any(
                row.get("status") not in {"denied", "unknown"} for row in confirmed):
            return True
        if key == "med_current" and any(re.search(r"正在(?:服|用)|目前(?:服|用)", text) for text in statements) and any(
                re.search(r"(?:已经|已|目前)?停(?:药|用|服)", text) for text in statements):
            return True
        # 明确否认同一事实与肯定原话才算冲突；不同疾病名称继续累积。
        for text in statements:
            match = re.match(r"^(?:没有|否认|未患|无)(.+)$", text)
            if match and any(match[1] == other or other.endswith(match[1]) for other in statements - {text}):
                return True
        return key in {"hpi_onset", "hpi_severity", "ps_age"}

    def refresh_information_gaps(self, model_gaps: list[str] | None = None) -> None:
        gaps = list(model_gaps or [])
        for key in self.known_information:
            status = self.information_status(key)
            if status in {"unknown", "needs_review"}:
                gaps.append(f"{key}：{'患者尚未确认' if status == 'unknown' else '先后资料不一致，待核对'}")
        self.information_gaps = list(dict.fromkeys(gaps))

    def get_summary(self) -> str:
        """Generate a concise medical summary from all collected info.

        Iterates ALL keys in collected_info and raw_answers — not just
        PHASE_ORDER keys — so Track2 (adv_*) and continuity (cq_*) data
        is not silently dropped from the diagnosis input.
        """
        lines = [f"主诉: {self.chief_complaint}"]
        unresolved_answer_keys = {
            key
            for key, answers in self.raw_answer_history.items()
            if len({answer.strip() for answer in answers if answer.strip()}) > 1
        }
        unknown_answer_keys = {
            key for key, value in self.collected_info.items()
            if not key.startswith("__") and is_unknown_answer(value)
            and _extract_phase_key(self.question_phase_keys.get(key) or key) not in self.resolved_information
        } - unresolved_answer_keys
        # Collected structured info (exclude internal keys)
        for key, val in self.collected_info.items():
            if key.startswith("__"):
                continue
            if _extract_phase_key(self.question_phase_keys.get(key) or key) in self.resolved_information:
                continue
            if key in unresolved_answer_keys:
                continue
            if key in unknown_answer_keys:
                continue
            if val and val not in ("无", "没有", "不清楚", "不记得", "asked_by_track1", "跳过"):
                meta = {}
                try:
                    ep = InterviewPhase(key)
                    meta = PHASE_META.get(ep, {})
                except ValueError:
                    pass
                cat = meta.get("cat", "")
                prefix = f"  {cat} " if cat else "  "
                lines.append(f"{prefix}[{key}]: {val}")
        # Raw patient answers (supplemental context)
        for key, val in self.raw_answers.items():
            if key.startswith("__"):
                continue
            if _extract_phase_key(self.question_phase_keys.get(key) or key) in self.resolved_information:
                continue
            if key in unresolved_answer_keys:
                continue
            if key in unknown_answer_keys:
                continue
            if val and val not in ("无", "没有", "不清楚", "不记得", "跳过"):
                # Skip if already covered by collected_info
                if key not in self.collected_info or not self.collected_info.get(key):
                    lines.append(f"  患者回答 [{key}]: {val}")
        for key in sorted(unknown_answer_keys):
            history = self.raw_answer_history.get(key) or []
            original = history[-1] if history else self.raw_answers.get(key)
            response = original or self.collected_info.get(key) or "未提供"
            lines.append(f"  患者尚未确认 [{key}]（仍为未知）: {response}")
        for key in sorted(unresolved_answer_keys):
            resolved = self.resolved_information.get(_extract_phase_key(self.question_phase_keys.get(key) or key))
            status = "均保留，已补充核对回答" if resolved else "均保留，待核对"
            lines.append(f"  患者先后回答 [{key}]（{status}）:")
            for answer in self.raw_answer_history[key]:
                if answer.strip():
                    lines.append(f"    - 患者原话: {answer}")
        # Differential diagnoses summary
        diffs = self.get_differential_diagnoses()
        if diffs:
            lines.append("  鉴别诊断:")
            for d in diffs[:5]:
                flag = "✓" if d.confidence == "high" else "?" if d.confidence == "medium" else "×"
                lines.append(f"    {flag} {d.diagnosis} ({d.confidence})")
        if self.red_flags_detected:
            lines.append(f"  ⚠️ 危险信号: {', '.join(self.red_flags_detected)}")
        if self.known_information:
            lines.append("  已有资料原文及出处（未知和待核对不等于阴性）:")
            for key, rows in self.known_information.items():
                lines.append(f"    [{key}] {self.information_status(key)}")
                if key in self.resolved_information:
                    lines.append(f"      患者本次核对回答（仍为自报）: {self.resolved_information[key]['quote']}；下面保留历史原话")
                for row in rows:
                    lines.append(f"      {row['source']}: {row['quote']}")
        if self.stop_reason:
            lines.append(f"  采集停止原因: {self.stop_reason}；信息充分: {self.is_sufficient}")
        if self.information_gaps:
            lines.append("  仍需核对的信息: " + "；".join(self.information_gaps))
        # Lab reports with abnormal indicators
        import logging
        _log = logging.getLogger("debug.t3")
        _log.info("[DEBUG-T3] get_summary: lab_reports count=%d", len(self.lab_reports))
        for report in self.lab_reports:
            if report.get("overall_confidence", 0) >= 0.7:
                indicators = report.get("indicators", [])
                if indicators:
                    lines.append("  实验室检查:")
                    for ind in indicators:
                        abnormal_mark = " [异常]" if ind.get("abnormal") else ""
                        lines.append(
                            f"    - {ind.get('indicator_name', '?')}: "
                            f"{ind.get('value', '?')} {ind.get('unit', '')}"
                            f"{abnormal_mark}"
                        )
        _log.info("[DEBUG-T3] get_summary: summary length=%d chars", len("\n".join(lines)))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM Output Schemas
# ---------------------------------------------------------------------------

class DifferentialDiagnosisEntry(BaseModel):
    """A single differential diagnosis entry in LLM output."""

    diagnosis: str = Field(..., description="疾病名称")
    confidence: str = Field(..., pattern="^(high|medium|low)$", description="当前置信度")
    key_features: list[str] = Field(default_factory=list, description="该诊断的关键鉴别特征")
    confirmed_features: list[str] = Field(default_factory=list, description="已确认的支持特征")
    missing_features: list[str] = Field(default_factory=list, description="尚未确认的关键特征")
    reason: str = Field(default="", description="为什么考虑这个诊断")


class NextQuestionSchema(BaseModel):
    """Schema for the next question generated by LLM."""

    question_id: str = Field(..., description="标准医学标识符，如 hpi_onset, pmh_chronic 等")
    question: str = Field(..., description="呈现给患者的口语化问题文本，通俗易懂")
    type: str = Field(..., pattern="^(choice|multi_choice|text)$", description="问题类型")
    options: list[str] = Field(default_factory=list, description="选择题选项（type=choice 时必填，至少2个）")
    hint: str = Field(default="", description="给患者的友好提示")
    allow_skip: bool = Field(default=True, description="是否允许跳过")
    reason: str = Field(default="", description="为什么问这个问题（内部reasoning）")


class BasicQuestion(BaseModel):
    question_id: str = Field(..., description="标识符如 hpi_onset")
    question: str = Field(..., description="口语化问题")
    type: str = Field(default="text", pattern="^(choice|multi_choice|text)$")
    options: list[str] = Field(default_factory=list)
    hint: str = Field(default="")
    allow_skip: bool = Field(default=True)
    phase: str = Field(default="", description="所属病史维度")
    reason: str = Field(default="")
    information_key: str = Field(default="", description="对应已知信息的维度标识，改写问题也必须使用同一标识")
    priority: str = Field(default="essential", pattern="^(essential|clarification|optional)$")


class KnownInformation(BaseModel):
    information_key: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=800)
    source: str = Field(pattern="^(chief_complaint|patient_history|lab_report|collected_info|answer)$")

class DifferentialEntry(BaseModel):
    diagnosis: str = Field(...)
    confidence: str = Field(default="low", pattern="^(high|medium|low)$")
    key_features: list[str] = Field(default_factory=list)
    reason: str = Field(default="")


class InterviewDecision(BaseModel):
    action: str = Field(default="ask", pattern="^(ask|search_only|synthesize)$")
    basic_module: list[BasicQuestion] = Field(default_factory=list, description="基本问诊问题(每轮1-2个)")
    advanced_module: list[BasicQuestion] = Field(default_factory=list, description="精细化问诊问题(按需0-1个)")
    differential_diagnoses: list[DifferentialEntry] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list, description="需要搜索的医学术语")
    primary_diagnosis: str = Field(default="", description="synthesize时的主要诊断")
    differential: list[str] = Field(default_factory=list)
    confidence: str = Field(default="medium")
    evidence: list[str] = Field(default_factory=list)
    needs_more_info: list[str] = Field(default_factory=list, description="缺失信息/建议检查")
    preliminary_hypotheses: list[DifferentialEntry] = Field(default_factory=list)
    reasoning: str = Field(default="")
    red_flags: list[str] = Field(default_factory=list)
    covered_dimensions: list[str] = Field(default_factory=list)
    known_information: list[KnownInformation] = Field(default_factory=list)

    @field_validator("needs_more_info", mode="before")
    @classmethod
    def normalize_information_gaps(cls, value):
        """兼容真实模型的带理由缺口对象，持久化仍使用旧字符串协议，不丢失缺口。"""
        if not isinstance(value, list):
            return value
        normalized = []
        for item in value:
            if isinstance(item, dict):
                key, reason = item.get("information_key"), item.get("reason")
                if not isinstance(key, str) or not key.strip() or not isinstance(reason, str) or not reason.strip():
                    raise ValueError("缺口对象必须包含非空 information_key 与 reason")
                normalized.append(f"{key.strip()}：{reason.strip()}")
            else:
                normalized.append(item)
        return normalized


INTERVIEW_SYSTEM_PROMPT = """你是医枢 MedAxis 诊疗系统的路由Agent（Route Agent），负责编排多轨并行诊疗流程。

## 你的工作模式：三轨并行 → 整合中心 → 循环决策

### 轨道一：文本主诉 → 基本问诊
患者输入口语化主诉 → 你按照中国执业医师"病史采集"标准设计基本问诊问题：
  1.主诉 2.现病史(起病/症状特点/伴随/演变/诊疗经过) 3.既往史(慢性病/手术/传染病/过敏)
  4.个人史(生活习惯/职业/出行/一般情况-睡眠饮食二便体重精神)
  5.家族史 6.用药史
  7.特殊人群：儿童(喂养/发育/接种)、女性(月经/婚育)——仅当患者特征匹配时触发

### 轨道二：搜索增强 → 精细化问诊
对主诉进行SearXNG+RAG医学知识搜索 → 根据搜索结果设计靶向进阶问题：
  - 确认/排除鉴别诊断的关键特征
  - 量化症状细节
  - 关联性提问
  - 搜索发现的证据缺口 → 设计新问题填补

### 轨道三：多模态报告（未来）
患者上传检查报告 → OCR/视觉解析 → 提取结构化指标 → 并入整合中心

### 整合中心与循环
三条轨道数据汇入你的整合判断：
  1. 生成动态问诊卡片(选择题/文本题，数量不限)
  2. 患者作答 → 答案回到整合中心
  3. 评估信息完整性 → 不完整就继续追问/补充搜索 → 完整就进入诊断

## 每轮输出JSON

**action="ask"** — 需要问诊:
```json
{
  "action": "ask",
  "basic_module": [{"question_id":"hpi_xxx|pmh_xxx|ps_xxx|fh_xxx|med_xxx|ps_child_xxx|ps_female_xxx","question":"口语化问题","type":"choice|text","options":["选项"],"hint":"提示","allow_skip":true,"phase":"临床维度","reason":"为何问"}],
  "advanced_module": [{"question_id":"adv_xxx","question":"基于搜索的靶向问题","type":"choice|text","options":["选项"],"hint":"提示","allow_skip":true,"reason":"搜索发现XX需确认"}],
  "differential_diagnoses": [{"diagnosis":"疑似疾病","confidence":"high|medium|low","key_features":["特征"],"reason":"理由"}],
  "search_queries": ["可选：本轮需搜索的术语"],
  "reasoning": "完整临床推理",
  "red_flags": [],
  "covered_dimensions": ["已覆盖的病史维度"]
}
```

**action="synthesize"** — 可以诊断:
```json
{
  "action": "synthesize",
  "primary_diagnosis": "主要诊断",
  "differential": ["鉴别诊断"],
  "confidence": "high|medium|low",
  "evidence": ["支持证据"],
  "needs_more_info": ["缺失信息","建议做的检查"],
  "reasoning": "诊断推理过程",
  "covered_dimensions": ["已覆盖维度"]
}
```

## 关键规则
- 返回JSON(```json```)，无额外文字
- 问题口语化，用"您"开头，优先选择题
- 胸痛大汗/呼吸困难/意识模糊/剧烈腹痛→red_flags
- 已问ID不重复，已收集信息对应的维度不要再问
- 检查collected_info中已有内容，只问未覆盖维度，问题随信息增多自然减少
- 信息不全也可synthesize，在needs_more_info说明缺什么
- basic_module每轮1-2个，advanced_module每轮0个（临床信息不足时2个、足够时1个，灵活调整）
"""


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def _build_interview_prompt(
    state: InterviewState,
    patient_history: str | None = None,
    knowledge_context: str = "",
) -> str:
    lines = [f"## 患者主诉\n{state.chief_complaint or '未知'}", ""]
    diffs = state.get_differential_diagnoses()
    if diffs:
        lines.append("## 当前鉴别诊断")
        for d in diffs:
            flag = "✓" if d.confidence == "high" else "?" if d.confidence == "medium" else "×"
            lines.append(f"  {flag} {d.diagnosis} ({d.confidence}) - {d.reason}")
        lines.append("")
    if state.collected_info:
        lines.append("## 已收集信息(最近)")
        recent = list(state.collected_info.items())
        for k, v in recent[-12:]:
            if not k.startswith("__") and v and v not in ("无","没有","不清楚","不记得","跳过","skipped",""):
                raw = state.raw_answers.get(k, "")
                lines.append(f"  {k}: {v}" + (f" ({raw})" if raw and raw != str(v) else ""))
        lines.append("")
    if knowledge_context:
        lines.append(f"## 搜索结果\n{knowledge_context[:1000]}")
        lines.append("")
    if patient_history:
        lines.append(f"## 既往史\n{patient_history}")
        lines.append("")
    pending = [p.value for p in PHASE_ORDER if p.value not in state.collected_info and not p.value.startswith("__")]
    lines.append(f"## 状态\n已问{len(state.asked_questions)}个问题")
    if pending:
        lines.append(f"未覆盖维度: {', '.join(pending[:6])}")
    if state.asked_questions:
        lines.append(f"已问ID: {', '.join(state.asked_questions[-8:])}")
    lines.append("")
    lines.append("请返回action=ask(提问)/search_only(搜索)/synthesize(诊断)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON Extraction Helper
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if "```json" in text:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    elif "```" in text:
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    if not text:
        raise ValueError("empty LLM response after extraction")
    return json.loads(text)


# ---------------------------------------------------------------------------
# Dynamic Interview Engine — Differential-Diagnosis-Driven
# ---------------------------------------------------------------------------

class DynamicInterviewEngine:

    def __init__(self, llm_service: Any, search_executor: Any = None) -> None:
        self.llm = llm_service
        self.search = search_executor
        self.logger = logging.getLogger("interview.engine")
        self._orchestrator = None

    def _get_orchestrator(self):
        if self._orchestrator is None:
            from app.services.orchestrator import InterviewOrchestrator
            self._orchestrator = InterviewOrchestrator(self.llm, self.llm, self.search)
        return self._orchestrator

    async def decide_next(
        self,
        state: InterviewState,
        patient_history: str | None = None,
        knowledge_context: str = "",
    ) -> tuple[list[QuestionTemplate], InterviewState, list[str], str, str]:
        self.logger.info(f"[DECIDE] asked={len(state.asked_questions)} pending_dims={len([p for p in PHASE_ORDER if p.value not in state.collected_info])}")

        try:
            from app.services.orchestrator import InterviewOrchestrator
            orch = InterviewOrchestrator(self.llm, self.search)
            return await orch.decide_next(state, patient_history)
        except Exception as e:
            self.logger.error(f"[DECIDE] orchestrator failed: {e}", exc_info=True)
            raise

    async def process_answer(
        self,
        state: InterviewState,
        question_id: str,
        answer: str,
    ) -> InterviewState:
        """Process a patient's answer and extract structured info + update differential diagnoses.

        Uses LLM to:
        1. Extract structured medical information from natural language
        2. Update the differential diagnosis list based on new information
        """
        state.record_patient_answer(question_id, answer)
        if question_id not in state.asked_questions:
            state.asked_questions.append(question_id)

        if is_unknown_answer(answer):
            state.collected_info[question_id] = answer
            return state

        # Use LLM to extract structured info AND update differential diagnoses
        diffs = state.get_differential_diagnoses()
        diffs_json = json.dumps([d.to_dict() for d in diffs], ensure_ascii=False) if diffs else "[]"

        extract_prompt = f"""患者对问题"{question_id}"的回答是："{answer}"

当前鉴别诊断列表：{diffs_json}

请完成以下任务，返回 JSON：

1. 从患者回答中提取结构化的医学信息
2. 根据新信息，更新每个鉴别诊断的 confirmed_features 和 missing_features
3. 如果有新的鉴别诊断需要加入，或某个诊断可以被排除，请说明

返回格式：
{{
  "extracted": "提取的关键医学信息（简洁准确）",
  "category": "所属的临床维度",
  "differential_updates": [
    {{
      "diagnosis": "疾病名称",
      "action": "confirm|refute|add|remove",
      "feature": "被确认或排除的特征",
      "reason": "为什么"
    }}
  ],
  "new_differential_diagnoses": [
    {{
      "diagnosis": "新诊断名称",
      "confidence": "high|medium|low",
      "key_features": ["特征1", "特征2"],
      "reason": "为什么新考虑这个诊断"
    }}
  ]
}}

如果患者回答"没有""无"等，extracted 填"无"，differential_updates 为空。
如果信息不明确，extracted 填患者原话。"""

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": extract_prompt}],
                system_prompt="你是医学信息提取助手。从患者回答中提取关键信息。只返回JSON。",
                max_tokens=1024,
            )
            raw = _extract_json(response.content)
            extracted = raw.get("extracted", answer)
            state.collected_info[question_id] = extracted

            # Update confirmed features
            features = state.get_confirmed_features()
            features[question_id] = extracted
            state.set_confirmed_features(features)

            # Update differential diagnoses based on differential_updates
            diff_updates = raw.get("differential_updates", [])
            new_diagnoses = raw.get("new_differential_diagnoses", [])

            existing_diagnoses = {d.diagnosis: d for d in diffs}

            for update in diff_updates:
                diag_name = update.get("diagnosis", "")
                action = update.get("action", "")
                feature = update.get("feature", "")

                if diag_name not in existing_diagnoses:
                    continue

                d = existing_diagnoses[diag_name]
                if action == "confirm" and feature:
                    if feature not in d.supporting_evidence:
                        d.supporting_evidence.append(feature)
                elif action == "refute" and feature:
                    if feature not in d.refuting_evidence:
                        d.refuting_evidence.append(feature)

            # Add new diagnoses
            for new in new_diagnoses:
                diag_name = new.get("diagnosis", "")
                if diag_name and diag_name not in existing_diagnoses:
                    diffs.append(DifferentialHypothesis(
                        diagnosis=diag_name,
                        confidence=new.get("confidence", "low"),
                        key_features=new.get("key_features", []),
                        supporting_evidence=[],
                        refuting_evidence=[],
                        reason=new.get("reason", ""),
                    ))

            state.set_differential_diagnoses(diffs)

        except Exception:
            # Fallback: store raw answer
            state.collected_info[question_id] = answer
            features = state.get_confirmed_features()
            features[question_id] = answer
            state.set_confirmed_features(features)

        return state
