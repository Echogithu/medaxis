"""有限的通用科室咨询参考；官方导诊资料不等于临床分诊审核。"""

import re
from typing import Any

PREPARATION_POLICY_VERSION = "2026-09-30.1"
FOCUS_FACT_ID = "unknown.department_focus"
_GUIDE = {
    "id": "sysu6.outpatient.2017",
    "title": "中山大学附属第六医院 · 常见疾病导诊指引",
    "url": "https://www.sysu6h.cn/guide/outpatient/502",
    "published_at": "2017-02-09",
    "checked_at": "2026-09-30",
}
_GENERAL = {
    "id": "ycph.general",
    "title": "阳春市人民医院 · 全科医学科介绍",
    "url": "https://www.ycph.com.cn/Category_327/Index.aspx",
    "checked_at": "2026-09-30",
}
_DENTAL = {
    "id": "pku.dental.2018",
    "title": "北京大学医院 · 口腔中心就诊说明",
    "url": "https://hospital.pku.edu.cn/info/1013/1232.htm",
    "published_at": "2018-09-05",
    "checked_at": "2026-09-30",
}
# 只取来源明确列出的有限主诉；高风险、跨科或语义含糊时不排序猜选。
_DIRECTIONS = (
    ("respiratory", "呼吸内科", "咳嗽、咳痰等呼吸相关问题", ("咳嗽", "干咳", "咳痰", "咯痰"), _GUIDE),
    ("digestive", "消化内科", "腹泻、便秘、反酸等消化相关问题", ("腹泻", "便秘", "反酸", "腹胀", "嗳气"), _GUIDE),
    ("skin", "皮肤科", "皮肤瘙痒、痤疮、脱发等问题", ("皮肤瘙痒", "痤疮", "脱发"), _GUIDE),
    ("eye", "眼科", "眼部红肿、流泪等问题", ("眼睛红肿", "眼部红肿", "眼睛流泪"), _GUIDE),
    ("ent", "耳鼻喉科", "耳鸣、鼻塞、声嘶等问题", ("耳鸣", "鼻塞", "声嘶"), _GUIDE),
    ("dental", "口腔科", "牙痛、牙齿松动等牙齿问题", ("牙痛", "牙疼", "牙齿松动"), _DENTAL),
    ("orthopedics", "骨科", "关节痛、腰痛等骨关节问题", ("关节痛", "腰痛", "肩背痛", "脚跟痛"), _GUIDE),
    ("urinary", "泌尿专科", "尿频、尿急、尿痛等问题", ("尿频", "尿急", "尿痛"), _GUIDE),
    ("gynecology", "妇产科", "月经失调、白带异常等问题", ("月经失调", "白带异常", "痛经"), _GUIDE),
)
_SCOPE = "通用咨询参考，依据医院公开资料整理，未经临床审核；不判断病情轻重。具体科室名称和接诊范围请向就诊医院确认。"
_AMBIGUOUS = re.compile(r"无|没|不|否认|排除|未|如果|若|是否|可能|怀疑|以前|曾经|好了|家人|父亲|母亲|朋友")
_TRIAGE = re.compile(r"胸痛|胸闷|呼吸困难|喘不过气|咯血|呕血|便血|黑便|晕厥|意识|抽搐|突然|突发|剧烈|严重|加重|外伤|骨折|看不见|视力下降")


def build_department_guidance(
    source: dict[str, Any], corrections: list[dict[str, Any]], unresolved: list[dict[str, Any]],
) -> dict[str, Any]:
    case = source["case"]
    report = source.get("report") or {}
    corrected = {entry["fact_id"]: entry["value"] for entry in corrections}
    complaint = str(corrected.get("patient.chief_complaint", case.get("chief_complaint") or ""))
    result = {
        "guidance_version": PREPARATION_POLICY_VERSION,
        "status": "general_consultation", "recommendation": None,
        "reason": "现有信息还不能明确专科方向。可先向医院导诊咨询；医院设有全科门诊时，也可咨询全科医生。",
        "evidence_ids": [], "references": [_GENERAL], "scope_note": _SCOPE,
        "focus_question": "这次主要想咨询哪类问题？",
        "options": [
            {"id": key, "label": description, "department": name, "reference": reference}
            for key, name, description, _, reference in _DIRECTIONS
        ] + [{"id": "general", "label": "其他、多个问题或不确定", "department": "全科医学科", "reference": _GENERAL}],
        "risk_notes": [str(flag) for flag in report.get("red_flags", []) if flag]
        if isinstance(report.get("red_flags"), list) else [],
    }
    if case.get("is_emergency") or case.get("severity") == "emergency" or report.get("severity") == "emergency":
        return {**result, "status": "urgent", "focus_question": None, "reason": "已有报告标记需紧急就医。请立即联系当地急救机构或就近急诊，不要等待整理完资料。", "references": []}
    if (result["risk_notes"] or _TRIAGE.search(complaint)
            or case.get("severity") in {"high", "severe", "critical"}
            or report.get("severity") in {"high", "severe", "critical"}):
        return {**result, "status": "risk_review", "focus_question": None, "reason": "请先核对风险提示，并由医护人员确认就医紧急程度；如正出现危险信号或症状快速恶化，请立即联系当地急救机构或就近急诊。", "references": []}
    if re.search(r"宝宝|儿童|孩子|婴儿|孕期|怀孕", complaint):
        return {**result, "focus_question": None, "reason": "儿童或孕期问题需要结合年龄、孕期等情况确认接诊范围，请先向医院导诊咨询。"}
    if unresolved:
        return {**result, "status": "needs_clarification", "focus_question": None, "reason": "前后回答还有待核对，暂不自动选定专科。可先补充当前情况，或向医院导诊咨询。"}
    # 患者明确选择咨询主题优先；不读取 AI 诊断、报告发现或病历标题。
    focus = corrected.get(FOCUS_FACT_ID)
    if focus in {"general", "其他、多个问题或不确定"}:
        return result
    selected = next((direction for direction in _DIRECTIONS if focus in (direction[0], direction[2])), None)
    from_choice = selected is not None
    evidence_id = f"correction.{FOCUS_FACT_ID}"
    if selected is None:
        clauses = re.split(r"[，。；、,;\n]|但是|不过|但", complaint)
        positive = [clause for clause in clauses if not _AMBIGUOUS.search(clause)]
        matches = [direction for direction in _DIRECTIONS if any(
            keyword in clause for clause in positive for keyword in direction[3]
        )]
        if len(matches) > 1:
            return {**result, "status": "needs_clarification", "reason": "你描述了多个方向的问题。请选择这次主要想咨询的问题；无法区分时可先向医院导诊或全科门诊咨询。"}
        if len(matches) != 1:
            return result
        selected = matches[0]
        evidence_id = "correction.patient.chief_complaint" if "patient.chief_complaint" in corrected else "patient.chief_complaint"
    _, name, _, _, reference = selected
    return {
        **result, "status": "consultation_reference", "recommendation": name,
        "reason": f"根据{'你选择的咨询主题' if from_choice else '你描述的主要问题'}，可考虑咨询{name}；这个方向不代表病因已确定。",
        "evidence_ids": [evidence_id], "references": [reference],
    }
