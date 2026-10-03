"""出站文本最小化：原文偏移遮蔽与临床数值保持，不宣称完全去标识。"""
import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PrivacySpan:
    start: int
    end: int
    text: str
    label: str


@dataclass(frozen=True)
class RedactedText:
    text: str
    spans: tuple[PrivacySpan, ...]


_PATTERNS = (
    ("phone", re.compile(r"(?<!\d)(?:\+?86[- ]?)?(1[3-9]\d[- ]?\d{4}[- ]?\d{4})(?!\d)")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("identity", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("record", re.compile(r'(?:病历号|住院号|门诊号|就诊号)["\s]*[:：]["\s]*([A-Za-z0-9][A-Za-z0-9-]{2,39})')),
    ("name", re.compile(r'(?:姓名|患者姓名|患者名|病人姓名|patient_name)["\s]*[:：]["\s]*([\u4e00-\u9fff·]{2,6})(?=[，,；;。\s"\}]|$)')),
    ("address", re.compile(r'(?:住址|家庭地址|联系地址|地址)["\s]*[:：]["\s]*([^，,；;。\n"\}]{3,80})')),
    ("name", re.compile(r"(?:欧阳|司马|上官|诸葛|[李王张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文])[\u4e00-\u9fff]{1,2}(?=今天|目前|今年|最近|近日)")),
)
_IDENTIFIER_KEYS = {"patient_name", "real_name", "full_name", "姓名", "患者姓名"}


def redact_text(text: str) -> RedactedText:
    """只遮蔽有边界的标识；不使用 AGE 泛化或删除数值/单位的兜底规则。"""
    spans = []
    for label, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span(1 if match.lastindex else 0)
            value = text[start:end]
            if label == "address" and not re.search(r"省|市|区|县|路|街|号|室", value):
                continue
            spans.append(PrivacySpan(start, end, value, label))
    spans.sort(key=lambda span: (span.start, span.end, span.label))
    result = list(text)
    for span in spans:
        result[span.start:span.end] = "*" * (span.end - span.start)
    return RedactedText("".join(result), tuple(spans))


def redact_for_provider(value: Any, *, _key: str = "") -> Any:
    """复制请求树，保留协议键/图片数据；JSON工具消息按值遮蔽，不破坏结构。"""
    if isinstance(value, str):
        if value.startswith("data:image/"):
            return value
        if _key in _IDENTIFIER_KEYS:
            return "*" * len(value)
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                return json.dumps(redact_for_provider(parsed), ensure_ascii=False)
        return redact_text(value).text
    if isinstance(value, list):
        return [redact_for_provider(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_for_provider(item, _key=str(key)) for key, item in value.items()}
    return value


def redact_messages_for_provider(messages: list[dict]) -> list[dict]:
    """消息内容遮蔽，调用编号与工具名保持协议身份；参数仍按JSON值遮蔽。"""
    result = redact_for_provider(messages)
    for original, sent in zip(messages, result):
        for key in ("role", "tool_call_id", "name"):
            if key in original:
                sent[key] = original[key]
        for original_call, sent_call in zip(original.get("tool_calls") or [], sent.get("tool_calls") or []):
            for key in ("id", "type"):
                if key in original_call:
                    sent_call[key] = original_call[key]
            original_function = original_call.get("function") or {}
            if "name" in original_function:
                sent_call["function"]["name"] = original_function["name"]
    return result
