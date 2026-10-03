"""在独立进程导入指定工作区源码，调用真实入口；仅替换模型、检索和持久化依赖。"""
import argparse
import asyncio
import json
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


async def probe(catalog, source_root):
    from app.models.interview import InterviewState
    from app.services.llm import LLMResponse
    from app.services.orchestrator import InterviewOrchestrator
    from app.services import orchestrator, agents
    from app.services.agents import AgentResult, DiagnosisAgent, DiagnosisReport
    from app.services.reranker import RerankerService
    from app.db.session import async_engine
    from sqlalchemy import event

    @event.listens_for(async_engine.sync_engine, "do_connect")
    def refuse_database_connection(*_args):
        raise AssertionError("合成评测禁止实际数据库连接")

    assert Path(orchestrator.__file__).resolve().is_relative_to(source_root), "源码路径混用"
    rows = []
    for case in catalog["cases"]:
        if case["kind"] == "interview":
            state = InterviewState.from_dict(case["state"])
            candidates = [{"question_id": q[0], "information_key": q[0], "question": q[1],
                           "type": "choice", "phase": q[0], "options": ["有", "没有", "不清楚"],
                           "priority": q[2] if len(q) > 2 else "essential", "reason": "合成必要性说明"}
                          for q in case["questions"]]
            response = LLMResponse(content=json.dumps({"basic_module": candidates, "known_information": case.get("facts", []),
                                                       "needs_more_info": case.get("needs_more_info", []),
                                                       "action": case.get("model_action", "ask")}, ensure_ascii=False),
                                   model="fixed-fixture", provider="fixed-fixture", finish_reason="stop",
                                   usage_prompt_tokens=0, usage_completion_tokens=0)
            llm = SimpleNamespace(chat=AsyncMock(return_value=response))
            if case.get("repair_questions"):
                repaired = [{"question_id": q[0], "information_key": q[0], "question": q[1], "type": "choice",
                             "phase": q[0], "options": ["有", "没有", "不清楚"], "priority": "essential", "reason": "补问必要缺口"}
                            for q in case["repair_questions"]]
                llm.chat.side_effect = [response, LLMResponse(content=json.dumps({"action": "ask", "basic_module": repaired}, ensure_ascii=False),
                    model="fixed-fixture", provider="fixed-fixture", finish_reason="stop", usage_prompt_tokens=0, usage_completion_tokens=0)]
            if case.get("model_failure"):
                llm.chat.side_effect = RuntimeError("synthetic model failure")
            try:
                cards, state, _, action, _ = await InterviewOrchestrator(llm).decide_next(state)
                row = {"id": case["id"], "error": False, "question_ids": [q.question_id for q in cards], "action": action}
            except Exception as exc:
                row = {"id": case["id"], "error": True, "error_type": type(exc).__name__}
            row.update(sufficient=state.is_sufficient, summary=state.get_summary(), model_calls=llm.chat.await_count,
                       stop_reason=getattr(state, "stop_reason", ""), gaps=getattr(state, "information_gaps", []))
        else:
            @asynccontextmanager
            async def fake_db():
                yield SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
            agent = DiagnosisAgent()
            agent._generate_search_query = AsyncMock(return_value=case["query"])
            agent._update_session = AsyncMock()
            agent.analyze = AsyncMock(return_value=AgentResult(
                agent_type="diagnosis", content={}, confidence="low", tool_calls_used=[],
                structured_output=DiagnosisReport(primary_diagnosis="合成摘要[S1]", confidence="low")))
            rerank = AsyncMock(return_value=[tuple(r) for r in case.get("rerank_scores", [])])
            if not case.get("rerank_scores"):
                rerank.side_effect = ValueError("synthetic missing provider")
            with patch.object(agents, "async_session_maker", fake_db), \
                 patch.object(agents.DynamicConfigService, "diagnosis_report_source_limit", AsyncMock(return_value=case["limit"])), \
                 patch.object(agents.GLOBAL_REGISTRY, "execute", AsyncMock(return_value={"success": True, "result": {"sources": case["sources"]}})), \
                 patch.object(RerankerService, "rerank", rerank):
                result = await agent.run_full_diagnosis_workflow(str(uuid.uuid4()))
            if result.structured_output is None:
                row = {"id": case["id"], "error": True}
            else:
                citations = result.structured_output.knowledge_citations
                selected = result.tool_calls_used[0]["result"]["sources"]
                row = {"id": case["id"], "error": False,
                       "source_keys": [c["chunk_id"] if c["source_type"] == "internal" else c["url"] for c in selected],
                       "cited_source_keys": [c.chunk_id if c.source_type == "internal" else c.url for c in citations if getattr(c, "used_in_report", None) is not False],
                       "citation_ids": [c.citation_id for c in citations]}
        rows.append(row)
    return {"source_root": str(source_root), "orchestrator_file": orchestrator.__file__, "cases": rows,
            "scope": "fixed_model_response_control_layer", "real_model_tokens": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    logging.disable(logging.CRITICAL)
    result = asyncio.run(probe(json.loads(args.catalog.read_text(encoding="utf-8")), args.source_root.resolve()))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已重放 {len(result['cases'])} 例；源码 {result['source_root']}")
