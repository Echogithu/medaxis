"""真实 OpenMed SDK 适配；只转换协议，不补中文规则或读取 gold。"""
from __future__ import annotations


def mask_spans(text: str, spans: list[dict]) -> str:
    """用原文位置统一成评分器要求的等长星号；重叠位置只遮蔽一次。"""
    result = list(text)
    for span in spans:
        start, end = span.get("start"), span.get("end")
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text)):
            raise ValueError("SDK 返回无效原文偏移")
        if text[start:end] != span.get("text"):
            raise ValueError("SDK 实体文本与原文偏移不一致")
        result[start:end] = "*" * (end - start)
    return "".join(result)


def context_assertions(inp: dict) -> tuple[list[dict], list[dict]]:
    from openmed.clinical.context import ClinicalAssertion, assert_context
    from openmed.clinical.grounding.assertion_grounding import assertion_grounding_status

    raw = list(assert_context(inp["text"], inp["mentions"], language="zh"))
    mapped = []
    for item in raw:
        axes = ClinicalAssertion(
            temporality=item["temporality"], certainty=item["uncertainty"],
            negation=item["negation"], experiencer=item["experiencer"],
        )
        mapped.append({"start": item["start"], "end": item["end"],
                       "status": assertion_grounding_status(axes).status})
    return mapped, raw


def extract_and_mask(text: str, model_path: str, config, loader) -> dict:
    from openmed import extract_pii

    prediction = extract_pii(
        text, model_name=model_path, confidence_threshold=0.5, lang="zh",
        config=config, loader=loader, preserve_whitespace=True,
        use_smart_merging=True, cache_results=False,
    )
    spans = [{"start": e.start, "end": e.end, "text": e.text,
              "label": e.label, "confidence": float(e.confidence)}
             for e in prediction.entities]
    return {"redacted_text": mask_spans(text, spans), "redactions": spans}
