"""独立离线核对真实请求/原文/原始响应并评分；不运行存档脚本或新增模型。"""
import argparse
import ast
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / '.ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal'
ASSETS = HERE / 'frozen-v2'
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.query_requirements import parse_assessment, rank_assessed
from resume_experiment import load, sha, require, write, SMOKE_IDS, SOURCE_PATHS, EVAL_FILES
from resume_runtime import validate_payload
from resume_eval_score import score
from build_resume_eval import validate


def parser_ast(data, name):
    tree = ast.parse(data)
    return ast.dump(next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name), include_attributes=False)


def verify_run(folder, plan_dir, mode, seen=None):
    folder = folder.resolve();folder.relative_to(HERE.resolve())
    seen = set() if seen is None else seen
    require(folder not in seen and len(seen) < 3, '继承循环/过深')
    seen = seen | {folder}
    validate(ASSETS)
    plan = load(plan_dir / 'plan.json')
    payload = load(folder / 'execution-input.json')
    validate_payload(payload)
    execution = load(folder / 'execution.json')
    raw = load(folder / 'observations-raw.json')
    reference = load(folder / 'plan-reference.json')
    require(reference['sha256'] == sha((plan_dir / 'plan.json').read_bytes()) and Path(reference['path']).resolve() == plan_dir.resolve(), '计划关联不符')
    frozen = load(ASSETS / 'inputs-development.json')
    require(mode in {'smoke', 'development'} and plan['scope'] == 'development_given_candidates_only'
            and plan['holdout_loaded'] is False and plan['retrieval_executed'] is False,
            '计划范围或阶段非法')
    task_pairs = [(t['question_id'], t['variant']) for t in plan['tasks']]
    require(len(task_pairs) == len(set(task_pairs)) == 96
            and set(task_pairs) == {(q['id'], v) for q in frozen['questions'] for v in ('B0','B1','B2','B3')}
            and {t['question_id'] for t in plan['tasks'][:24]} == set(SMOKE_IDS)
            and plan['smoke_ids'] == list(SMOKE_IDS), '四方案计划缺失/重复或烟测题不同')
    require(plan['input_sha256'] == payload['input_sha256'] == raw['input_sha256'] == sha((ASSETS / 'inputs-development.json').read_bytes()), '冻结输入指纹不同')
    require(payload['questions'] == frozen['questions'], '执行器收到的不是冻结开发输入')
    require(set(payload) == {'protocol','mode','questions','input_sha256','source_sha256','expected_model_snapshot','tasks','max_http_requests'}, '执行器payload含额外字段或gold')
    require(payload['mode'] == raw['mode'] == mode and payload['protocol'] == raw['protocol'] == plan['protocol'], '协议/阶段不同')
    require(execution['docker_exit_code'] == 0 and not execution['timed_out'] and execution['read_gold_in_executor'] is False, '执行不完整或未隔离gold')
    require(execution['input_sha256'] == sha((folder / 'execution-input.json').read_bytes()), '实际执行payload被改')
    for name in EVAL_FILES:
        require(sha((folder / name).read_bytes()) == execution['evaluation_sha256'][name] == plan['evaluation_sha256'][name], '实验源码快照不同')
        if name in {'resume_experiment_verify.py', 'resume_eval_score.py', 'build_resume_eval.py'}:
            require(sha((folder / name).read_bytes()) == sha(Path(__file__).with_name(name).read_bytes()), '离线评分或核验规则已变，需重新审查版本')
    for name in SOURCE_PATHS:
        require(sha((folder / 'production-source' / Path(name).name).read_bytes()) == execution['source_sha256'][name] == plan['source_sha256'][name] == raw['source_sha256'][name], '业务源码快照不同')
    # 读取AST做兼容核对，不执行归档代码；prompt变化不会把旧parser输出重新解释。
    for name in ('parse_assessment', 'rank_assessed'):
        require(parser_ast((folder / 'production-source/query_requirements.py').read_text(encoding='utf-8'), name) == parser_ast((ROOT / 'backend/app/services/query_requirements.py').read_text(encoding='utf-8'), name), '解析/排序规则已变，需原版本评分器')
    require(raw['complete'] and raw['read_only'] and raw['rolled_back'] and raw['read_gold'] is False
            and raw['settings_unchanged'] and raw['settings_before'] == raw['settings_after'], '只读/配置/完成门禁失败')
    require(raw['vector_retrieval_executed'] is False and raw['external_search_executed'] is False and raw['forbidden_network_attempts'] == 0, '范围夸大或额外网络')
    require(raw['model_snapshot'] == payload['expected_model_snapshot'] == plan['model_snapshot'], '模型/实际参数不同')
    tasks = plan['tasks'][:24] if mode == 'smoke' else plan['tasks'][24:]
    expected_tasks = [{k: t[k] for k in ('question_id','variant')} for t in tasks]
    require(payload['tasks'] == expected_tasks and payload['max_http_requests'] == len(tasks), '执行任务缺失/重复/额外')
    require(len(raw['rows']) == len(raw['requests']) == len(tasks) == raw['requested_tasks'], '请求/任务/输出数量不同')
    lookup = {q['id']: q for q in frozen['questions']}
    checkpoints = [json.loads(line) for line in (folder / 'wire-checkpoints.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    require(len(checkpoints) == 3 * len(tasks) + 1 and checkpoints[-1] == {'final': raw}, '请求前后/逐题checkpoint与final不一致')
    for index, (task, row, request) in enumerate(zip(tasks, raw['rows'], raw['requests'])):
        begin = {'http_started': {k: request[k] for k in ('task', 'wire_request', 'request_sha256')}, 'sequence': index + 1}
        finish = {'http_finished': request, 'sequence': index + 1}
        require(checkpoints[3 * index:3 * index + 3] == [begin, finish, {'checkpoint': row, 'requests': [request]}], '逐题实际请求/输出不一致')
        key = {k: task[k] for k in ('question_id','variant')}
        require({k: row[k] for k in key} == key == request['task'] and row['request_key'] == task['request_key'], '请求关联错误')
        require(request['wire_request'] == plan['task_wire_requests'][task['request_key']], '实际发送消息/参数与预注册不同')
        require(request['request_sha256'] == sha(json.dumps(request['wire_request'],sort_keys=True,ensure_ascii=False).encode()), '请求指纹不同')
        require(request['status_code'] == 200 and request['finish_reason'] == 'stop' and row['status'] == 'success'
                and row['error_type'] is None and row['http_attempts'] == 1, '请求失败或重试')
        require(row['raw_output'] == request['raw_content'] and row['native_usage'] == request['native_usage']
                and {'prompt_tokens','completion_tokens'} <= set(request['native_usage']), '原始模型输出/usage不一致')
        q = lookup[row['question_id']]
        parsed = parse_assessment(row['raw_output'], [{'id': s['id'],'excerpt': s['quote']} for s in q['candidates']])
        require(parsed == row['parsed'] and rank_assessed(parsed) == row['ranked_ids'], '原始JSON与分类/排序不同')
        require(not any(c['label'] == 'unknown' for c in parsed['candidates']), '存在unknown，停止扩量')
    inherited = []
    inherited_requests = []
    if mode == 'development':
        parent = load(folder / 'inherited-smoke.json')
        parent_path = Path(parent['path'])
        require(parent['sha256'] == sha((parent_path / 'observations-raw.json').read_bytes()), '继承烟测变化')
        verify_run(parent_path, plan_dir, 'smoke', seen)
        parent_raw = load(parent_path / 'observations-raw.json')
        inherited, inherited_requests = parent_raw['rows'], parent_raw['requests']
    all_rows = inherited + raw['rows']
    all_requests = inherited_requests + raw['requests']
    require(all(isinstance(r['response_model'], str) and r['response_model'] for r in all_requests)
            and len({r['response_model'] for r in all_requests}) == 1, '供应商返回模型名不同，比较条件待核实')
    by_variant = {}
    for variant in ('B0','B1','B2','B3'):
        rows = []
        native_rows = [r for r in all_rows if r['variant'] == variant]
        for r in native_rows:
            parsed = r['parsed']
            rows.append({'id': r['question_id'], 'status':'success', 'retrieved_sources':[],
                         'candidates':[{'id':c['id'],'label':c['label'],'retain':c['retain'],'score':c['coverage_fraction']} for c in parsed['candidates']],
                         'ranked_ids':r['ranked_ids'],'elapsed_ms':r['elapsed_ms'],
                         'usage':{'input_tokens':r['native_usage']['prompt_tokens'],'output_tokens':r['native_usage']['completion_tokens']},'error_type':None})
        observation = {'protocol':'resume-eval-observations-v1','split':'development','input_sha256':plan['input_sha256'],'rows':rows}
        metrics = score(ASSETS,observation,'development',retrieval_executed=False, selected_ids=SMOKE_IDS if mode=='smoke' else None)
        elapsed = sorted(r['elapsed_ms'] for r in native_rows)
        metrics['elapsed_ms_median'] = statistics.median(elapsed)
        metrics['elapsed_ms_p95_nearest_rank'] = elapsed[max(0, (95*len(elapsed)+99)//100-1)]
        metrics['http_requests'] = len(native_rows)
        by_variant[variant] = metrics
    require(len(all_requests) == (24 if mode=='smoke' else 96), '总请求或继承重复')
    return {'status':'VERIFIED_REAL_CANDIDATE_EXPERIMENT_ONLY','mode':mode,'http_requests':len(all_requests),
            'new_http_requests':len(raw['requests']),'variants':by_variant,'model_snapshot':raw['model_snapshot'],
            'response_model':all_requests[0]['response_model'],
            'professional_reviewed':0,'retrieval':None,'clinical_accuracy':None,'read_gold_only_in_offline_scorer':True}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--mode',choices=['smoke','development'],required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=verify_run(args.run,args.plan,args.mode)
    if args.output:
        write(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='variants'},ensure_ascii=False))
