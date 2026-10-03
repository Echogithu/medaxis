"""中文原话语境提示；参考 OpenMed 多轴设计，不执行诊断或实体识别。"""
import re
from typing import Any

CONTEXT_POLICY_VERSION = "2026-10-01.1"
_CLAUSE = re.compile(r"[^，,；;。！？!?\n]+")
_FAMILY = re.compile(r"母亲|父亲|妈妈|爸爸|家人|家属|丈夫|妻子|儿子|女儿|祖母|祖父|奶奶|爷爷")
_UNKNOWN = re.compile(r"不清楚|不知道|不记得|记不清|说不清|无法说清|尚未确认|未知|不确定|跳过")
_UNCERTAIN = re.compile(r"可能|疑似|考虑|待排|不能排除|无法排除|尚不能排除|没有否认|未否认")
_NEGATED = re.compile(r"否认|没有|未见|未发现|阴性|并非|无|不曾|没发过")
_HISTORICAL = re.compile(r"既往|曾经|曾有|患过|去年|已缓解|已痊愈|过去")
_HYPOTHETICAL = re.compile(r"如果|假如|若|万一|一旦")
_CURRENT = re.compile(r"目前|当前|现在|今天|近日|正在|持续")


def annotate_patient_text(text: str, *, withheld: str | None = None) -> list[dict[str, Any]]:
    """按原文字符位置分句，规则提示一律 advisory；未识别不等于医学确认。"""
    result = []
    for match in _CLAUSE.finditer(text):
        clause = match.group().strip()
        if not clause:
            continue
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        family = bool(_FAMILY.search(clause))
        # 同句含其他人及患者时不猜疾病归属，等待核对。
        mixed = family and bool(re.search(r"患者|本人|我(?:目前|现在|有|无|没有|也)", clause))
        mixed_time = bool(_HISTORICAL.search(clause) and _CURRENT.search(clause))
        unknown = bool(_UNKNOWN.search(clause))
        uncertain = unknown or bool(_UNCERTAIN.search(clause))
        negated = bool(_NEGATED.search(clause)) and not uncertain
        time = ("hypothetical" if _HYPOTHETICAL.search(clause) else
                "historical" if _HISTORICAL.search(clause) else
                "current" if _CURRENT.search(clause) else "unspecified")
        status = (withheld or ("needs_review" if mixed or mixed_time else "unknown" if unknown else
                  "non_patient" if family else "uncertain" if uncertain else
                  "hypothetical" if time == "hypothetical" else "refuted" if negated else
                  "historical" if time == "historical" else "present" if time == "current" else "reported"))
        result.append({"start": start, "end": start + len(clause), "text": clause,
                       "experiencer": "unspecified" if mixed else "family" if family else "patient",
                       "temporality": time, "negation": "negated" if negated else "not_detected",
                       "certainty": "unknown" if unknown or withheld == "unknown" else
                                    "uncertain" if uncertain or withheld == "needs_review" or mixed or mixed_time else "reported",
                       "status": status, "advisory": True})
    return result


def add_context(fact: dict[str, Any], *, withheld: str | None = None) -> None:
    """原话优先，结构化值保持不动；坐标相对 clinical_context_text 而非JSON字节。"""
    text = fact.get("patient_response") or fact.get("value")
    if not isinstance(text, str):
        return
    fact["clinical_context_text"] = text
    source_ids = fact.get("patient_response_source_ids") or []
    fact["clinical_context_source_id"] = source_ids[-1] if source_ids else fact.get("source_id")
    fact["clinical_context"] = annotate_patient_text(text, withheld=withheld)
