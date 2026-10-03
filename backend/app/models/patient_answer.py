"""确定性患者回答语义，避免把未知、否认和肯定混为一类。"""

from typing import Any

UNKNOWN_ANSWER_MARKERS = {
    "不清楚", "不记得", "未知", "不知道", "不确定", "记不清", "不太清楚",
    "无法确定", "跳过", "skipped", "unknown", "notsure", "dontknow", "na",
}
UNKNOWN_ANSWER_PHRASES = {
    "不清楚", "不记得", "未知", "不知道", "不确定", "记不清", "不太清楚",
    "不太确定", "无法确定", "无法回忆", "想不起来", "记不起来", "说不清",
}
DENIAL_ANSWER_MARKERS = {
    "无", "没有", "否认", "明确无", "明确否认", "从未", "不曾", "否",
    "无已知过敏", "无已知过敏史", "没有已知过敏史", "否认过敏史",
}
AFFIRMATIVE_ANSWER_MARKERS = {"有", "是", "存在", "明确有", "明确是"}


def normalize_answer_marker(value: str) -> str:
    return "".join(value.casefold().strip(" \t\r\n，。,.!！?？;；:：").split())


def is_unknown_answer(value: Any) -> bool:
    if isinstance(value, str):
        normalized = normalize_answer_marker(value)
        return normalized in UNKNOWN_ANSWER_MARKERS or any(
            phrase in normalized for phrase in UNKNOWN_ANSWER_PHRASES
        )
    if isinstance(value, list) and value:
        return all(is_unknown_answer(item) for item in value)
    return False


def assertion_status(value: Any) -> str:
    values = value if isinstance(value, list) else [value]
    normalized = [normalize_answer_marker(item) for item in values if isinstance(item, str)]
    if normalized and all(item in DENIAL_ANSWER_MARKERS for item in normalized):
        return "denied"
    if normalized and all(item in AFFIRMATIVE_ANSWER_MARKERS for item in normalized):
        return "affirmed"
    return "reported"


def distinct_patient_answers(answers: list[str]) -> list[str]:
    distinct: list[str] = []
    seen: set[str] = set()
    for answer in answers:
        normalized = answer.strip()
        if normalized and normalized not in seen:
            distinct.append(answer)
            seen.add(normalized)
    return distinct
