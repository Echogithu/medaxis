"""
Independent Track Agents + Orchestrator for Plan B architecture.

Track1Agent: History collection (standard clinical interview questions).
Track2Agent: Search-driven refinement (generates questions AFTER search results).
InterviewOrchestrator: Coordinates tracks, merges results, manages state.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any

from app.models.interview import (
    InterviewState,
    QuestionTemplate,
    InterviewDecision,
    DifferentialHypothesis,
    PHASE_ORDER,
    _extract_json,
    _fingerprint,
    _extract_phase_key,
)
from app.services.llm import LLMService

logger = logging.getLogger("orchestrator")


class InterviewGenerationError(ValueError):
    """Generation failed; an empty result must not imply sufficient clinical evidence."""


def is_initial_interview(state: InterviewState) -> bool:
    return not (
        state.asked_questions or state.question_texts or state.collected_info
        or state.raw_answers or state.lab_reports or state.regeneration_count
    ) and state.phase == "interviewing"


_NEGATED_RED_FLAG_PREFIX = re.compile(
    r"^(?:无|没有|未见|未发现|未出现|否认|不伴(?:有|随)?|no\b|denies\b|without\b)\s*",
    re.IGNORECASE,
)
_POSITIVE_ABSENCE_OF_FUNCTION = {
    "无呼吸", "无自主呼吸", "无脉", "无脉搏", "无意识", "无反应", "无生命体征",
    "没有呼吸", "没有脉搏", "没有意识", "没有反应",
}


def _filter_negated_red_flags(red_flags: list[str]) -> list[str]:
    """只剔除明确写成否定句的危险信号，保留失去生命功能类阳性信号。"""
    result: list[str] = []
    for red_flag in red_flags:
        text = " ".join(red_flag.split())
        text = re.sub(r"^(?:患者目前|目前患者|患者|目前|当前)\s*", "", text)
        if _NEGATED_RED_FLAG_PREFIX.match(text):
            # 这些是危险状态本身的常见表达，不是对症状的否认。
            if text in _POSITIVE_ABSENCE_OF_FUNCTION or text.startswith(("无法", "无力", "没有力气")):
                result.append(red_flag)
            continue
        result.append(red_flag)
    return result


# ---------------------------------------------------------------------------
# Track 1 Agent: History Collection
# ---------------------------------------------------------------------------

TRACK1_SYSTEM_PROMPT = """你是病史采集专家。根据患者主诉和已收集信息，基于中国执业医师标准生成问诊问题。

职责：
- 只补问会影响本次主诉的信息缺口，不机械遍历现病史、既往史、个人史、家族史及用药史
- 先复用主诉、档案、已答和检查资料。已知/明确否认不再问；已回答未知不换说法再问。前后冲突可用clarification核对一次
- 特殊人群：儿童(喂养/发育/接种)、女性(月经/婚育)——仅匹配时触发
- 问题口语化，用"您"开头。一律使用 choice 或 multi_choice，选项后附加 "以上都没有" 供患者否定（如慢性病史、过敏史等筛查题）
- 提出0-2个必要候选；每题填写information_key、priority(essential/clarification/optional)、reason，说明答案影响哪项判断。非必要背景题标optional
- 只在本次主诉需要的关键信息已经问过、回答或明确表示未知时返回action:synthesize。能写摘要不代表可以结束问诊
- needs_more_info中的未问必要项必须生成对应问题；病史中不同疾病/药物是互补资料，不能仅因两段原话不同就声称冲突。未知/跳过不等于正常或否认
- needs_more_info使用稳定的information_key字符串或包含information_key和reason的对象，不输出无标识的自由文字清单
- known_information只抽取提供材料的完整原文quote和source(chief_complaint/patient_history/lab_report/collected_info/answer)，不能补造患者事实；已有模型采集值仍标collected_info，不升级为患者确认；引用外部医学资料不是患者事实

只返回JSON（```json```包裹）。"""

TRACK1_DECISION_SCHEMA = """返回JSON（示例，请生成真实临床选项）：
{
  "action": "ask",
  "basic_module": [
    {"question_id":"hpi_quality","information_key":"hpi_quality","priority":"essential","question":"您颈肩部的疼痛是什么样的感觉？","type":"multi_choice","options":["酸痛","刺痛","胀痛","麻木","僵硬"],"hint":"可多选","allow_skip":true,"phase":"现病史-症状特点","reason":"疼痛性质会影响下一步评估"},
    {"question_id":"hpi_severity","question":"疼痛程度如何？","type":"choice","options":["轻微，不影响活动","中等，转头受限","剧烈，完全无法活动"],"hint":"","allow_skip":false,"phase":"现病史-严重程度","reason":"评估严重程度"}
  ],
  "differential_diagnoses": [{"diagnosis":"颈肩筋膜炎","confidence":"medium","key_features":["晨起加重","活动后缓解"],"reason":"与主诉匹配"}],
  "red_flags": [],
  "covered_dimensions": ["hpi_quality"],
  "known_information": [{"information_key":"hpi_onset","quote":"昨天开始","source":"chief_complaint"}],
  "needs_more_info": [],
  "reasoning": "基于症状特点推断"
}
重要：multi_choice 的 options 必须是该问题的具体答案选项（≥2个），不允许使用占位符。red_flags 是字符串数组（如["频繁呕吐无法进食"]），不是对象数组。"""

FIRST_TURN_SCHEMA = """首次问诊，只生成1-2个最必要的问题，危险信号筛查优先。
只返回紧凑JSON，顶层包含basic_module、red_flags和known_information。
basic_module每项包含question_id、information_key、question、type、options、phase、reason；必要时加allow_skip:false。
known_information包含information_key、quote、source；quote必须逐字来自主诉、档案或上传资料，source为chief_complaint/patient_history/lab_report。
type只能为choice或multi_choice，options一次给齐3-5个简短具体选项。
question_id和phase使用上述维度的英文标识。
保留安全筛查：red_flags只列患者明确肯定存在的危险信号。明确否认的症状（如“无发热”“无外伤”“无肢体无力”）不得写入；未提及或未知的症状也不得声称已发生。
暂不输出鉴别诊断、病因解释、reasoning、covered_dimensions或诊疗建议；后续问诊再分析。
不添加Markdown围栏或JSON以外的文字。"""


# ---------------------------------------------------------------------------
# Track 2 Agent: Search-Driven Refinement
# ---------------------------------------------------------------------------

TRACK2_SYSTEM_PROMPT = """你是搜索增强问诊专家。基于SearXNG+RAG搜索结果，生成靶向进阶问题。

职责：
- 分析搜索结果中的关键临床线索
- 针对鉴别诊断的confirmed/missing特征设计确认问题
- 仅当证据缺口会影响当前评估时才提出新问题；检索发现的背景知识不能自动转成患者任务
- 复用全部已知信息；每题填写information_key、priority和reason。已回答未知不重问，无必要问题返回空数组
- 问题量0-1个
- choice 和 multi_choice 类型必须包含至少2个具体选项，筛查类问题附加 "以上都没有"
- 禁止返回空 options 数组

只返回JSON（```json```包裹）。"""

TRACK2_DECISION_SCHEMA = """返回JSON（示例，请生成真实临床选项）：
{
  "advanced_module": [
    {"question_id":"adv_dehydration","question":"有无以下脱水表现？","type":"multi_choice","options":["哭时无泪","尿量减少","眼窝凹陷","口唇干燥","精神萎靡","以上都没有"],"hint":"可多选","allow_skip":true,"reason":"评估脱水程度"},
    {"question_id":"adv_diet","question":"最近饮食有无变化？","type":"choice","options":["正常进食","食量减少","拒食","仅喝水"],"hint":"","allow_skip":true,"reason":"判断进食情况"}
  ]
}
重要：choice 类型必须提供 options（≥2个具体选项），禁止空数组。multi_choice 的 options 最后一项应为 "以上都没有"。"""


def _information_context(state: InterviewState) -> str:
    """模型需要原话与出处；审计时间及重复行留在持久化账本，避免重复消耗上下文。"""
    state.refresh_known_information()
    compact = {}
    for key, rows in state.known_information.items():
        quotes = list(dict.fromkeys((row["source"], row["quote"]) for row in rows))
        compact[key] = {"status": state.information_status(key),
                        "quotes": [{"source": source, "quote": quote} for source, quote in quotes]}
        if key in state.resolved_information:
            compact[key]["current_clarification"] = state.resolved_information[key]["quote"]
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Track1Agent:

    def __init__(self, llm: LLMService):
        self.llm = llm

    async def generate(
        self,
        state: InterviewState,
        patient_history: str | None = None,
        required_gaps: list[str] | None = None,
    ) -> tuple[list[QuestionTemplate], list[DifferentialHypothesis], list[str], str]:
        first_turn = is_initial_interview(state)
        # A clipped/invalid compact response gets one full-budget recovery attempt.
        for compact in ([True, False] if first_turn else [False]):
            started = time.perf_counter()
            prompt = self._build_prompt(state, patient_history, compact=compact)
            if required_gaps:
                prompt += ("\n## 必须继续询问的缺口\n" + "\n".join(required_gaps)
                           + "\n上一轮漏发了必要问题。必须返回对应的essential题；确有矛盾时用clarification题，"
                             "填写具体矛盾及询问目的，不能直接结束。只问未回答的必要信息。")
            try:
                response = await self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=TRACK1_SYSTEM_PROMPT,
                    max_tokens=768 if compact else 2048,
                )
                if response.finish_reason == "length":
                    raise ValueError("Truncated interview JSON")
                raw = _extract_json(response.content)
                if not raw or not isinstance(raw, dict):
                    raise ValueError("Invalid interview JSON")
                decision = InterviewDecision.model_validate(raw)
                if first_turn:
                    if not 1 <= len(decision.basic_module) <= 2:
                        raise ValueError("First interview requires one or two questions")
                    for question in decision.basic_module:
                        if (
                            not question.question.strip()
                            or question.type not in {"choice", "multi_choice"}
                            or len({o.strip() for o in question.options if o.strip()}) < 2
                        ):
                            raise ValueError("Incomplete first interview question")
                material = {
                    "chief_complaint": state.chief_complaint,
                    "patient_history": patient_history or "",
                    "lab_report": json.dumps(state.lab_reports, ensure_ascii=False),
                    "collected_info": "\n".join(str(value) for key, value in state.collected_info.items() if not key.startswith("__")),
                    "answer": "\n".join(answer for answers in state.raw_answer_history.values() for answer in answers)
                              + "\n" + "\n".join(state.raw_answers.values()),
                }
                for fact in decision.known_information:
                    if fact.quote in material[fact.source]:
                        from app.services.clinical_context import annotate_patient_text
                        text = material[fact.source]
                        start = text.index(fact.quote)
                        clauses = [c for c in annotate_patient_text(text)
                                   if c["start"] < start + len(fact.quote) and c["end"] > start]
                        # 复用完整上下文，避免模型只抽到“发热”而丢掉“无”或疾病主体。
                        if any(c["status"] in {"hypothetical", "uncertain", "needs_review"}
                               or (c["experiencer"] == "family" and not fact.information_key.startswith("fh_"))
                               or (c["temporality"] == "historical" and fact.information_key.startswith("hpi_"))
                               for c in clauses):
                            continue
                        quote = text[min(c["start"] for c in clauses):max(c["end"] for c in clauses)] if clauses else fact.quote
                        state.remember_information(fact.information_key, quote, fact.source)
                state.generation_action = decision.action
                state.refresh_information_gaps(decision.needs_more_info)
                questions = self._to_templates(decision.basic_module, state)
                logger.info(
                    "[TRACK1] compact=%s questions=%d red_flags=%d output_tokens=%d elapsed_ms=%.1f",
                    compact, len(questions), len(decision.red_flags or []),
                    response.usage_completion_tokens, (time.perf_counter() - started) * 1000,
                )
                diffs = [
                    DifferentialHypothesis(
                        diagnosis=d.diagnosis, confidence=d.confidence,
                        key_features=d.key_features, reason=d.reason,
                    )
                    for d in (decision.differential_diagnoses or [])
                ]
                return questions, diffs, _filter_negated_red_flags(decision.red_flags or []), decision.reasoning or ""
            except Exception as exc:
                logger.warning("[TRACK1] compact=%s failed=%s", compact, type(exc).__name__)
        if first_turn:
            raise InterviewGenerationError("首轮问诊问题生成失败，请重试。")
        raise InterviewGenerationError("补问生成失败，请重试；本次未判断为信息充分。")

    def _build_prompt(
        self, state: InterviewState, patient_history: str | None, *, compact: bool = False,
    ) -> str:
        lines = [f"## 患者主诉\n{state.chief_complaint or '未知'}"]
        if patient_history:
            # 请求病史和结构化档案已在入口限长；不能再截掉过敏/停用等语义。
            lines.append(f"\n## 既往史\n{patient_history}")
        lines.append("\n## 已有信息及原文出处\n" + _information_context(state))
        if state.question_texts:
            # 未知也已经回答；保留题意与稳定标识，避免模型换 key 后误判为未问。
            asked = [{"question_id": qid, "information_key": state.question_phase_keys.get(qid) or _extract_phase_key(qid),
                      "question": state.question_texts[qid], "answer": state.raw_answers.get(qid),
                      "status": state.information_status(state.question_phase_keys.get(qid) or qid)}
                     for qid in state.asked_questions if qid in state.question_texts]
            lines.append("\n## 已问问题与原始回答（未知不能换标识重问）\n"
                         + json.dumps(asked, ensure_ascii=False, separators=(",", ":")))
        lines.append("\n## 采集边界\n只确认本次主诉需要的信息，不按病史维度清单补齐。未记录不等于必须询问；未知不等于否认。")
        lines.append("\n## 信息标识\n复用以下固定 information_key，不因改写问题而换标识（不是必问清单）："
                     + ", ".join(p.value for p in PHASE_ORDER)
                     + "。列表外的主诉专属缺口可以用adv_开头的稳定标识。")
        if state.lab_reports:
            lines.append("\n## 已上传资料（保留解析可信度）\n" + json.dumps(state.lab_reports, ensure_ascii=False))
        if compact:
            lines.append("\n" + FIRST_TURN_SCHEMA)
        else:
            lines.append('\n## 指令\n生成0-2个必要候选，每题说明询问目的。未问必要缺口必须继续问；只有没有未问必要项才action=synthesize。')
            lines.append("\n" + TRACK1_DECISION_SCHEMA)
        return "\n".join(lines)

    @staticmethod
    def _to_templates(module: list, state: InterviewState) -> list[QuestionTemplate]:
        result = []
        for m in module:
            qid = m.question_id
            if qid in state.asked_questions:
                qid = f"{qid}_{len(state.asked_questions)}"
            result.append(QuestionTemplate(
                question_id=qid,
                question=m.question,
                type=m.type,
                options=m.options if m.type in ("choice", "multi_choice") else [],
                hint=m.hint,
                allow_skip=m.allow_skip,
                phase=m.phase,
                colloquial_phase=m.phase,
                information_key=m.information_key or _extract_phase_key(m.question_id),
                priority=m.priority,
                reason=m.reason,
            ))
        return result


class Track2Agent:

    def __init__(self, llm: LLMService):
        self.llm = llm

    async def generate(
        self,
        state: InterviewState,
        search_results: str,
        diffs: list[DifferentialHypothesis],
    ) -> list[QuestionTemplate]:
        if not search_results or len(search_results.strip()) < 20:
            return []
        prompt = self._build_prompt(state, search_results, diffs)
        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=TRACK2_SYSTEM_PROMPT,
                max_tokens=1024,
            )
            raw = _extract_json(response.content)
            questions = self._to_templates(raw.get("advanced_module", []), state)
            logger.info("[TRACK2] questions=%d from search", len(questions))
            return questions
        except Exception as e:
            logger.error(f"[TRACK2] FAILED: {e}")
            return []

    def _build_prompt(self, state: InterviewState, search_results: str, diffs: list[DifferentialHypothesis]) -> str:
        lines = [f"## 患者主诉\n{state.chief_complaint}"]
        lines.append(f"\n## 搜索结果\n{search_results[:1500]}")
        if diffs:
            lines.append("\n## 当前鉴别诊断")
            for d in diffs[:5]:
                lines.append(f"- {d.diagnosis} (置信度:{d.confidence}) {d.key_features}")
        lines.append("\n## 已有信息及原文出处\n" + _information_context(state))
        lines.append("\n## 指令\n只生成advanced_module，0-1个必要候选。每题reason说明影响的判断，填写information_key及priority；没有必要的新问题则返回空数组。")
        lines.append("\n" + TRACK2_DECISION_SCHEMA)
        return "\n".join(lines)

    @staticmethod
    def _to_templates(module: list, state: InterviewState) -> list[QuestionTemplate]:
        result = []
        for m in module:
            qid = m.get("question_id", "adv_001")
            if qid in state.asked_questions:
                qid = f"{qid}_{len(state.asked_questions)}"
            result.append(QuestionTemplate(
                question_id=qid,
                question=m.get("question", ""),
                type=m.get("type", "text"),
                options=m.get("options") if isinstance(m.get("options"), list) else [],
                hint=m.get("hint", ""),
                allow_skip=m.get("allow_skip", True),
                phase=m.get("phase", "搜索补充"),
                colloquial_phase=m.get("phase", "搜索补充"),
                information_key=m.get("information_key") or _extract_phase_key(m.get("question_id", "adv_001")),
                priority=m.get("priority", "essential"),
                reason=m.get("reason", ""),
            ))
        return result


class InterviewOrchestrator:

    def __init__(self, llm: LLMService, search_executor: Any = None):
        self.track1 = Track1Agent(llm)
        self.track2 = Track2Agent(llm)
        self.search = search_executor
        self.logger = logging.getLogger("orchestrator")

    async def decide_next(
        self,
        state: InterviewState,
        patient_history: str | None = None,
        knowledge_context: str = "",
    ) -> tuple[list[QuestionTemplate], InterviewState, list[str], str, str]:
        self.logger.info("[DEBUG-DIAG] decide_next: phase=%s regeneration=%d", state.phase, state.regeneration_count or 0)
        if state.phase == "completed":
            if (state.regeneration_count or 0) >= 1:
                self.logger.info("[DEBUG-DIAG] decide_next: regeneration exhausted → action=completed")
                return [], state, [], "completed", ""
            state.phase = "interviewing"
            state.regeneration_count += 1
            self.logger.info("[DEBUG-DIAG] phase=completed, allowing 1 regeneration (#%d)", state.regeneration_count)
            regeneration = True
        else:
            regeneration = False
        pending = state.unanswered_question_ids()
        if pending and not regeneration:
            state.pending_question_ids = pending
            return [], state, [], "ask", "仍有待回答的问题，请先完成或跳过当前问题。"
        state.refresh_known_information()
        chief = state.chief_complaint
        self.logger.info(
            "[ORCH] asked=%d pending=%d",
            len(state.asked_questions),
            len([p for p in PHASE_ORDER if p.value not in state.collected_info]),
        )

        # Generate first, then search. Do not create an unawaited search coroutine
        # if question generation fails; parallel search is a separate optimization.
        track1_questions, diffs, red_flags, reasoning = await self.track1.generate(state, patient_history)
        track1_questions = self._deduplicate(track1_questions, state)
        # 两种去重均在补生成判断前执行；语义重复被删除也需要一次有界恢复机会。
        track1_questions = await self._semantic_dedup(track1_questions, state)
        required_gaps = self._unasked_gaps(state)
        if not track1_questions and required_gaps:
            # 最多补生成一次；失败不能转成带缺口的成功报告。
            recovered, recovered_diffs, recovered_flags, recovered_reason = await self.track1.generate(
                state, patient_history, required_gaps=required_gaps)
            track1_questions = self._deduplicate(recovered, state)
            track1_questions = await self._semantic_dedup(track1_questions, state)
            if not track1_questions:
                raise InterviewGenerationError("仍有必要信息未询问，补问生成失败，请重试。")
            diffs, red_flags, reasoning = recovered_diffs or diffs, recovered_flags or red_flags, recovered_reason or reasoning
        # 已有必要候选时先让患者作答；首轮不额外搜索扩展背景问题。
        search_needed = bool(self.search and not is_initial_interview(state)
                             and not track1_questions and diffs and state.generation_action != "synthesize")
        search_results = await self._run_search(chief, state) if search_needed else ""

        # Mark Track1 covered dimensions so Track2 sees them
        for q in track1_questions:
            if q.phase and q.phase not in state.collected_info:
                state.collected_info[q.phase] = "asked_by_track1"

        # Process red flags from Track1
        if red_flags:
            for rf in red_flags:
                if rf not in state.red_flags_detected:
                    state.red_flags_detected.append(rf)
            self.logger.warning("[ORCH] RED_FLAGS from Track1: %s", red_flags)

        # Update differential diagnoses from Track1
        if diffs:
            state.set_differential_diagnoses(diffs)

        # Phase 2: Track2 generates with Track1 dimensions visible
        track2_questions = await self.track2.generate(state, search_results, diffs) if search_results else []
        track2_questions = [q for q in track2_questions if q.reason.strip()]
        track2_questions = await self._semantic_dedup(self._deduplicate(track2_questions, state), state)

        for k in list(state.collected_info.keys()):
            if state.collected_info[k] == "asked_by_track1":
                del state.collected_info[k]

        all_questions = track1_questions + track2_questions
        deduped = self._deduplicate(all_questions, state)

        filtered_out: set[str] = set()
        for q in deduped:
            # Force text-type questions to become multi_choice via LLM option generation
            if q.type == "text":
                opts = await self._complete_options(q)
                if opts and len(opts) >= 2:
                    q.options = opts
                    q.type = "multi_choice"
                else:
                    self.logger.warning("[ORCH] filtering text question — LLM could not generate options: %s", q.question_id)
                    filtered_out.add(q.question_id)
                    continue

            if q.type in ("multi_choice", "choice") and (not q.options or len(q.options) < 2):
                opts = await self._complete_options(q)
                if opts:
                    q.options = opts
                    q.type = "multi_choice"
                elif q.type == "choice" and not q.options:
                    self.logger.warning("[ORCH] filtering choice question with empty options: %s", q.question_id)
                    filtered_out.add(q.question_id)
                    continue
                elif q.type == "choice" and len(q.options) < 2:
                    self.logger.warning("[ORCH] filtering choice question with insufficient options (%d): %s", len(q.options), q.question_id)
                    filtered_out.add(q.question_id)
                    continue
                elif q.type == "multi_choice" and len(q.options) < 2:
                    self.logger.warning("[ORCH] filtering multi_choice question with insufficient options (%d): %s", len(q.options), q.question_id)
                    filtered_out.add(q.question_id)
                    continue
            if q.type == "multi_choice" and q.options and "以上都没有" not in q.options:
                q.options = list(q.options) + ["以上都没有"]
        if filtered_out:
            deduped = [q for q in deduped if q.question_id not in filtered_out]

        # Safety net: strip empty/whitespace-only options
        for q in deduped:
            if q.type in ("choice", "multi_choice") and q.options:
                cleaned = [o for o in q.options if o and str(o).strip()]
                if cleaned != q.options:
                    q.options = cleaned
            if q.type in ("choice", "multi_choice") and len(q.options) < 2:
                self.logger.warning("[ORCH] filtering %s question with insufficient options after cleaning: %s", q.type, q.question_id)
                filtered_out.add(q.question_id)
        if filtered_out:
            deduped = [q for q in deduped if q.question_id not in filtered_out]

        # 两轨候选已分别完成语义去重；不对同一批题重复发起模型调用。

        meaningful = {key: [row["quote"] for row in rows]
                      for key, rows in state.known_information.items()
                      if state.information_status(key) not in {"unknown", "needs_review"}}
        signature = _fingerprint(json.dumps(meaningful, ensure_ascii=False, sort_keys=True))
        if state.interview_rounds:
            state.stagnation_counter = (state.stagnation_counter + 1
                                        if signature == state.last_information_fingerprint else 0)
        max_rounds = state.interview_policy.get("max_rounds", 6)
        # 体验预算不丢弃必要题；未知造成的停滞也不能阻止询问其他未问项。
        required_gaps = self._unasked_gaps(state)
        stopped = ("budget_reached" if not deduped and not required_gaps and state.interview_rounds >= max_rounds else
                   "no_progress" if not deduped and not required_gaps and state.stagnation_counter >= 2 else "")
        if stopped:
            state.refresh_information_gaps([
                *state.information_gaps,
                *(f"{q.information_key or q.question_id}：尚未采集" for q in deduped),
            ])
            deduped = []
            state.stop_reason = stopped

        if regeneration and not deduped and not required_gaps:
            action = "synthesize"
            state.is_sufficient = False
            state.phase = "completed"
            deduped = []
            self.logger.info("[ORCH] FORCING SYNTHESIZE for regeneration")
            return deduped, state, [], action, reasoning

        if not deduped:
            pending_unanswered = state.unanswered_question_ids()
            if pending_unanswered:
                self.logger.info("[DEBUG-DIAG] deferred synthesize — %d unanswered cards remain", len(pending_unanswered))
                action = "ask"
                return [], state, [], action, reasoning

            if required_gaps:
                raise InterviewGenerationError("必要补问未能生成有效题目，本次不能结束问诊，请重试。")

            # 上传资料在入口从会话 context 载入；不存在的进程内 bridge 不能作为发题旁路。
            state.refresh_information_gaps(state.information_gaps)
            state.stop_reason = state.stop_reason or ("model_ready" if state.generation_action == "synthesize" else "no_new_questions")
            state.is_sufficient = (state.stop_reason == "model_ready" and not state.information_gaps)
            state.phase = "completed"
            state.regeneration_count = 1
            action = "synthesize"
            self.logger.info("[DEBUG-DIAG] natural endpoint — dedup empty + no pending → synthesize")
            return [], state, [], action, reasoning

        action = "ask"
        deduped = sorted(deduped, key=lambda q: (q.allow_skip, q.priority != "clarification"))[
            :state.interview_policy.get("questions_per_round", 1)]
        state.interview_rounds += 1
        state.last_information_fingerprint = signature

        for q in deduped:
            fp = _fingerprint(q.question)
            if fp not in state.asked_question_fingerprints:
                state.asked_question_fingerprints.append(fp)
            pk = _extract_phase_key(q.information_key or q.question_id)
            state.question_phase_keys[q.question_id] = pk
            state.question_texts[q.question_id] = q.question
            if q.priority == "clarification":
                state.clarification_keys.append(pk)
                state.clarification_question_ids[q.question_id] = pk

        for q in deduped:
            if q.question_id not in state.asked_questions:
                state.asked_questions.append(q.question_id)
            state.current_question_id = q.question_id
        state.pending_question_ids = [q.question_id for q in deduped]

        return deduped, state, [], action, reasoning

    async def _complete_options(self, q: QuestionTemplate) -> list[str]:
        try:
            r = await self.track1.llm.chat(
                messages=[{"role": "user", "content": f'问题：{q.question}\n针对此问题，列出3-6个具体选项。如果患者可能\"都没有\"，最后加一个\"以上都没有\"选项。只返回JSON数组'}],
                system_prompt="你是临床选项生成助手。只返回JSON数组。", max_tokens=256)
            data = _extract_json(r.content)
            if isinstance(data, list):
                return [str(x) for x in data if x][:6]
            if isinstance(data, dict):
                opts = data.get("options") or data.get("choices") or []
                if isinstance(opts, list):
                    return [str(x) for x in opts if x][:6]
        except Exception:
            pass
        return []

    async def _run_search(self, chief_complaint: str, state: InterviewState) -> str:
        try:
            results = await asyncio.wait_for(
                self.search(chief_complaint, state),
                timeout=30.0,
            )
            if isinstance(results, str):
                return results[:2000]
            if isinstance(results, list):
                return "\n".join(
                    f"- {getattr(r, 'title', '')}: {getattr(r, 'snippet', '')[:200]}"
                    for r in results[:5]
                )
            if isinstance(results, dict):
                data = results.get("result", results)
                if isinstance(data, dict):
                    lines = []
                    answer = data.get("answer", "") or ""
                    if answer:
                        lines.append(answer[:1500])
                    sources = data.get("sources", []) or []
                    ext = data.get("external_sources", []) or []
                    all_src = (sources if isinstance(sources, list) else []) + (ext if isinstance(ext, list) else [])
                    for s in all_src[:3]:
                        if isinstance(s, dict):
                            t = s.get("title", "") or ""
                            lines.append(f"- {t}")
                    return "\n".join(lines)[:2000] if lines else ""
                return str(data)[:2000]
            return str(results)[:2000] if results else ""
        except asyncio.TimeoutError:
            self.logger.warning("[ORCH] Search timed out")
            return ""
        except Exception as e:
            self.logger.error(f"[ORCH] Search failed: {e}")
            return ""

    async def _semantic_dedup(
        self, candidates: list[QuestionTemplate], state: InterviewState
    ) -> list[QuestionTemplate]:
        if not candidates or not state.question_texts:
            return candidates
        asked_list = [
            state.question_texts[qid]
            for qid in state.asked_questions
            if qid in state.question_texts
        ]
        if not asked_list:
            return candidates
        candidate_texts = [q.question for q in candidates]
        prompt = (
            "判断每个候选问题是否与下面任何一个已问过的问题语义重复"
            "（问的是同一件事，只是换了一种说法）。\n\n"
            f"已问过的问题：\n"
            + "\n".join(f"{i+1}. {t}" for i, t in enumerate(asked_list))
            + f"\n\n候选问题：\n"
            + "\n".join(f"{j+1}. {t}" for j, t in enumerate(candidate_texts))
            + "\n\n返回JSON: {\"keep\": [索引], \"drop\": [索引], \"reasons\": {\"索引\": \"为什么重复或为什么保留\"}}"
            + "\n索引从1开始。keep 是应该保留的全新问题索引，drop 是语义重复应丢弃的索引。"
        )
        try:
            response = await self.track1.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="你是医疗AI去重助手。只返回JSON，不做其他输出。",
                max_tokens=256,
            )
            data = _extract_json(response.content)
            if not isinstance(data, dict):
                return candidates
            drop_indices = {
                int(i) - 1
                for i in (data.get("drop") or [])
                if isinstance(i, (int, float))
            }
            result = [
                q for idx, q in enumerate(candidates) if idx not in drop_indices or q.priority == "clarification"
            ]
            if len(result) < len(candidates):
                self.logger.info(
                    "[ORCH] semantic_dedup filtered %d/%d questions",
                    len(candidates) - len(result),
                    len(candidates),
                )
            return result
        except Exception as e:
            self.logger.warning("[ORCH] semantic_dedup failed, passing all: %s", e)
            return candidates

    async def _is_diagnosis_active(self) -> bool:
        """Check if a diagnosis is in progress (Redis lock exists)."""
        try:
            from app.db.redis_client import get_redis
            redis_client = get_redis()
            return await redis_client.exists(f"diag_lock:{id(self)}") > 0
        except Exception:
            return False

    @staticmethod
    def _unasked_gaps(state: InterviewState) -> list[str]:
        """未知已答不重问；模型声明的未问缺口不能只列在摘要里。"""
        result = []
        for gap in state.information_gaps:
            match = re.match(r"^([a-z][a-z0-9_]+)(?:\s*[:：]|$)", gap)
            if match:
                key = _extract_phase_key(match[1])
                status = state.information_status(key)
                if status == "not_recorded" or (status == "needs_review" and key not in state.clarification_keys):
                    result.append(gap)
            elif gap.strip():
                result.append(gap)
        return result

    @staticmethod
    def _deduplicate(questions: list[QuestionTemplate], state: InterviewState) -> list[QuestionTemplate]:
        seen_phase_keys: set[str] = set(state.question_phase_keys.values())
        seen_fingerprints = set(state.asked_question_fingerprints)
        result = []
        for q in questions:
            pk = _extract_phase_key(q.information_key or q.question_id)
            status = state.information_status(pk)
            clarification = (q.priority == "clarification" and status == "needs_review"
                             and pk not in state.clarification_keys and bool(q.reason.strip()))
            fp = _fingerprint(q.question)
            if q.priority == "optional" or not q.question.strip():
                continue
            if not clarification and (pk in seen_phase_keys or status != "not_recorded" or fp in seen_fingerprints):
                continue
            seen_phase_keys.add(pk)
            seen_fingerprints.add(fp)
            result.append(q)
        return result
