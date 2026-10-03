"""仅供合成文本实验的规则候选；不是 OpenMed SDK、NER 模型或生产脱敏器。"""

from __future__ import annotations

import re
from typing import Any

VERSION = "zh-rules-experiment-1"
STATUSES = {
    "present", "refuted", "historical", "hypothetical", "uncertain",
    "non_patient", "unknown", "needs_review",
}
# 姓名仅识别显式字段，故意不宣称能召回自由叙述中的所有人名。
PII_PATTERNS = (
    ("NAME", re.compile(r"(?:姓名|患者姓名)\s*[:：]\s*(?P<value>[\u4e00-\u9fff]{2,4})(?=[，,。；;\s]|$)")),
    ("PHONE", re.compile(r"(?<!\d)(?P<value>1[3-9]\d{9})(?!\d)")),
    ("ID", re.compile(r"(?<![0-9A-Za-z])(?P<value>\d{17}[0-9Xx])(?![0-9A-Za-z])")),
    ("EMAIL", re.compile(r"(?P<value>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")),
    ("RECORD_ID", re.compile(r"(?:病历号|住院号)\s*[:：]\s*(?P<value>[A-Za-z0-9-]+)")),
)
UNKNOWN = re.compile(r"不清楚|不记得|不知道|记不清|无法回忆|想不起来|未知|不确定是否")
FAMILY = re.compile(r"父亲|母亲|爸爸|妈妈|家族史|哥哥|姐姐|丈夫|妻子|朋友")
HISTORY = re.compile(r"去年|前年|曾经|以前|既往|幼年|已痊愈|已经好了")
HYPOTHETICAL = re.compile(r"如果|假如|若出现|一旦")
UNCERTAIN = re.compile(r"可能|怀疑|疑似|考虑|不能排除|待查")
DENIAL = re.compile(r"否认|没有|未出现|无|不伴|未见|排除")
CURRENT = re.compile(r"目前|现在|今日|今天|这次|近[一二三四五六七八九十\d]+天|[一二三四五六七八九十\d]+天")


def redact(text: str) -> tuple[str, list[dict[str, Any]]]:
    """等长遮蔽保留原始字符偏移；只返回位置与类型，不返回原敏感值。"""
    detections = []
    occupied: set[int] = set()
    for label, pattern in PII_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span("value")
            if occupied.intersection(range(start, end)):
                continue
            occupied.update(range(start, end))
            detections.append({"start": start, "end": end, "label": label})
    result = list(text)
    for span in detections:
        result[span["start"]:span["end"]] = "*" * (span["end"] - span["start"])
    return "".join(result), sorted(detections, key=lambda item: item["start"])


def classify(text: str, mention: dict[str, Any], *, unknown: bool, conflict: bool) -> dict:
    """给定提及位置时做语境分类；提及检测本身不在本实验内。"""
    start, end = mention["start"], mention["end"]
    clause = next(
        (m for m in re.finditer(r"[^，,。；;\n！？!?]+", text)
         if m.start() <= start and end <= m.end()), None,
    )
    status, reason = "needs_review", "未命中足够明确的语境规则"
    axes = {"polarity": "unknown", "temporality": "unknown",
            "certainty": "unknown", "experiencer": "unknown"}
    if conflict:
        reason = "回答历史待核对，不选择其中一条作为定论"
    elif clause and UNKNOWN.search(text[clause.start():clause.end()]):
        status, reason = "unknown", "保留未知回答"
    elif not clause and unknown:
        status, reason = "unknown", "无法定位分句且输入未知，转保守处理"
    elif clause:
        prefix = text[clause.start():start]
        suffix = text[end:clause.end()]
        context = text[clause.start():clause.end()]
        axes = {"polarity": "affirmed", "temporality": "current",
                "certainty": "certain", "experiencer": "patient"}
        if FAMILY.search(prefix):
            status, reason = "non_patient", "当前分句有家属或他人线索"
            axes["experiencer"] = "other"
        elif HYPOTHETICAL.search(prefix):
            status, reason = "hypothetical", "当前分句有条件线索"
            axes["temporality"] = "hypothetical"
        elif UNCERTAIN.search(prefix + suffix):
            status, reason = "uncertain", "当前分句有不确定线索"
            axes["certainty"] = "uncertain"
        elif DENIAL.search(prefix):
            status, reason = "refuted", "提及前有否认线索"
            axes["polarity"] = "negated"
        elif HISTORY.search(context):
            status, reason = "historical", "当前分句有既往线索"
            axes["temporality"] = "historical"
        elif CURRENT.search(context):
            status, reason = "present", "当前或持续时间线索"
        else:
            axes = {key: "unknown" for key in axes}
    return {"start": start, "end": end, "status": status, "axes": axes, "reason": reason}


def claim_verdict(claim: dict, citations: list[dict]) -> dict:
    """仅接纳带完整句子边界的原文引用；正确改写也会转人工复核。"""
    citation = next((c for c in citations if c["citation_id"] == claim["citation_id"]), None)
    verdict, reason = "review", "原文精确支持不足，不作语义蕴含判断"
    if citation is None:
        verdict, reason = "rejected", "引用 ID 不在检索结果中"
    else:
        excerpt = citation["excerpt"]
        start, end = claim["evidence_start"], claim["evidence_end"]
        if not (0 <= start < end <= len(excerpt)):
            verdict, reason = "rejected", "证据范围无效"
        elif excerpt[start:end] == claim["text"]:
            delimiters = "。；;\n！？!?"
            left_ok = start == 0 or excerpt[start - 1] in delimiters
            right_ok = end == len(excerpt) or excerpt[end] in delimiters
            if left_ok and right_ok:
                verdict, reason = "accepted", "完整原文陈述精确匹配"
    return {"id": claim["id"], "verdict": verdict, "reason": reason}


def process(case_input: dict, baseline: dict) -> dict:
    """输入不含 gold；复用现有准备包的未知/冲突判断，附加实验注解。"""
    text = case_input["text"]
    key = case_input["field"]
    package = baseline["package"]
    conflict = any(item["id"] == f"unresolved.{key}" for item in package["unresolved_facts"])
    unknown = not conflict and UNKNOWN.search(text) is not None
    redacted, detections = redact(text)
    return {
        "package": package,
        "redacted_text": redacted,
        "redactions": detections,
        "assertions": [classify(text, mention, unknown=unknown, conflict=conflict)
                       for mention in case_input["mentions"]],
        "claims": [claim_verdict(claim, baseline["citations"])
                   for claim in case_input["claims"]],
        "citations": baseline["citations"],
    }
