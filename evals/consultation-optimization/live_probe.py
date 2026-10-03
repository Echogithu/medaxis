"""容器内使用现有 web 模型配置；数据库事务只读，无患者表查询或持久化。"""
import asyncio
import json
import logging
import time


async def run_live(fixtures):
    from sqlalchemy import text
    from app.db.session import async_session_maker
    from app.models.interview import InterviewState, InterviewDecision, _extract_json, _extract_phase_key
    from app.services.llm import LLMService
    from app.services.orchestrator import InterviewOrchestrator

    logging.disable(logging.CRITICAL)
    rows = []
    for case in fixtures["cases"]:
        calls = []
        async with async_session_maker() as db:
            await db.execute(text("SET TRANSACTION READ ONLY"))
            delegate = LLMService(platform="web", db=db, timeout=35, max_retries=0)

            class ObservedLLM:
                async def chat(self, **kwargs):
                    if len(calls) >= 3:
                        raise RuntimeError("合成探测模型调用预算耗尽")
                    record = {"max_tokens": kwargs.get("max_tokens")}
                    calls.append(record)
                    started = time.perf_counter()
                    try:
                        response = await delegate.chat(**kwargs)
                        record.update(model=response.model, provider=response.provider,
                                      prompt_tokens=response.usage_prompt_tokens or None,
                                      completion_tokens=response.usage_completion_tokens or None,
                                      finish_reason=response.finish_reason)
                        record["response"] = response.content
                        try:
                            InterviewDecision.model_validate(_extract_json(response.content))
                        except Exception as exc:
                            record["decision_validation_errors"] = (exc.errors(include_input=False, include_url=False)
                                                                     if hasattr(exc, "errors") else type(exc).__name__)
                        return response
                    except Exception as exc:
                        record["error_type"] = type(exc).__name__
                        raise
                    finally:
                        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)

            state = InterviewState.from_dict(case["state"])
            started = time.perf_counter()
            try:
                cards, state, _, action, _ = await asyncio.wait_for(InterviewOrchestrator(ObservedLLM()).decide_next(state), timeout=115)
                keys = [_extract_phase_key(getattr(q, "information_key", "") or q.question_id) for q in cards]
                row = {"id": case["id"], "error": False, "action": action, "question_keys": keys,
                       "questions": [q.question for q in cards], "question_count": len(cards),
                       "recorded_dimension_reasks": len([key for key in keys if key in case["recorded_keys"]])}
            except Exception as exc:
                row = {"id": case["id"], "error": True, "error_type": type(exc).__name__}
            row.update(calls=calls, sufficient=state.is_sufficient, elapsed_ms=round((time.perf_counter() - started) * 1000, 1))
            rows.append(row)
            await db.rollback()
    return {"cases": rows, "scope": "single_run_synthetic_live_model_probe", "model_call_budget_per_case": 3}
