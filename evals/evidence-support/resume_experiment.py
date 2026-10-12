"""冻结实验计划及只读Docker入口；此执行器不读取gold/题目审核稿。"""
import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / '.ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal'
ASSETS = HERE / 'frozen-v2'
sys.path.insert(0, str(ROOT / 'backend'))
from resume_runtime import SOURCE_PATHS, expected_wire
from resume_variants import VARIANTS, system_for, request_key

SMOKE_IDS = ('Qf1edb10326745fcbff42', 'Qc29bb941d23ad2b73e1c', 'Qe351d0a6632ab2c8e145',
             'Q903958a548d0d608e433', 'Q8ac732a3f2d88e304a86', 'Qc5eba22f99ee18259db0')
EVAL_FILES = ('resume_runtime.py', 'resume_variants.py', 'resume_experiment.py',
              'resume_experiment_verify.py', 'resume_eval_score.py', 'build_resume_eval.py', 'resume_allowance.py')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def source_hashes():
    return {name: sha((ROOT / 'backend' / name).read_bytes()) for name in SOURCE_PATHS}


def eval_hashes():
    return {name: sha(Path(__file__).with_name(name).read_bytes()) for name in EVAL_FILES}


def inputs():
    # 只读开发输入与公开指纹清单，不能调用会加载gold的资产构建器。
    manifest = load(ASSETS / 'manifest.json')
    path = ASSETS / 'inputs-development.json'
    require(sha(path.read_bytes()) == manifest['assets_sha256'][path.name], '开发输入SHA不同')
    data = load(path)
    require(data['version'] == 'resume-eval-v2' and len(data['questions']) == 24, '仅允许冻结开发集')
    return data['questions'], sha(path.read_bytes())


def tasks_for(ids):
    # 轮换方案先后顺序，避免某方案总在所有问题上先跑；每个任务最多一次。
    return [{'question_id': qid, 'variant': VARIANTS[(i + j) % 4]} for i, qid in enumerate(ids) for j in range(4)]


def payload(mode, tasks, snapshot=None):
    questions, fingerprint = inputs()
    return {'protocol': 'resume-four-variants-v1', 'mode': mode, 'questions': questions,
            'input_sha256': fingerprint, 'source_sha256': source_hashes(), 'expected_model_snapshot': snapshot,
            'tasks': tasks, 'max_http_requests': len(tasks)}


def safe_output(path):
    path = path.resolve()
    path.relative_to(HERE.resolve())
    require(path != HERE.resolve() and not path.exists(), '仅创建新的Goal子目录，禁止覆盖')
    return path


def docker_script(value):
    modules = [(name.removesuffix('.py'), base64.b64encode(Path(__file__).with_name(name).read_bytes()).decode())
               for name in ('resume_variants.py', 'resume_runtime.py')]
    encoded = base64.b64encode(json.dumps(value, ensure_ascii=False).encode()).decode()
    return ('import asyncio,base64,json,sys,types\n'
            f'modules={modules!r}\n'
            'for name,blob in modules:\n'
            ' m=types.ModuleType(name);m.__file__="/tmp/"+name+".py";sys.modules[name]=m\n'
            ' exec(compile(base64.b64decode(blob),m.__file__,"exec"),m.__dict__)\n'
            f'p=json.loads(base64.b64decode({encoded!r}))\n'
            'try:\n'
            ' result=asyncio.run(sys.modules["resume_runtime"].run(p))\n'
            ' print(json.dumps({"final":result},ensure_ascii=False,allow_nan=False),flush=True)\n'
            ' sys.exit(0 if result["complete"] else 1)\n'
            'except Exception as exc:\n'
            ' print(json.dumps({"fatal":{"error_type":type(exc).__name__}},ensure_ascii=False),flush=True)\n'
            ' sys.exit(1)\n')


def archive_sources(output):
    for name in EVAL_FILES:
        (output / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    snapshots = output / 'production-source'
    snapshots.mkdir()
    for name in SOURCE_PATHS:
        (snapshots / Path(name).name).write_bytes((ROOT / 'backend' / name).read_bytes())


def execute(value, output):
    output = safe_output(output)
    output.mkdir(parents=True)
    archive_sources(output)
    write(output / 'execution-input.json', value)
    # 逐题checkpoint由子进程flush直接保存；超时/中断保留文件，不自动重发。
    stdout_path = output / 'wire-checkpoints.jsonl'
    code = docker_script(value)
    exit_code = None
    timed_out = False
    with stdout_path.open('x', encoding='utf-8') as stdout:
        try:
            process = subprocess.run(['docker', 'exec', '-i', '-w', '/app', 'medaxis-backend', 'python', '-'],
                input=code, stdout=stdout, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                timeout=90 if value['mode'] == 'preflight' else len(value['tasks']) * 65 + 90)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    write(output / 'execution.json', {'docker_exit_code': exit_code, 'timed_out': timed_out,
        'input_sha256': sha((output / 'execution-input.json').read_bytes()), 'source_sha256': value['source_sha256'],
        'evaluation_sha256': eval_hashes(), 'read_gold_in_executor': False, 'max_http_requests': len(value['tasks']),
        'note': '超时不证明容器子进程终止；已预留全部请求，不自动重启/重发'})
    records = [json.loads(line) for line in stdout_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    final = [r['final'] for r in records if set(r) == {'final'}]
    require(exit_code == 0 and not timed_out and len(final) == 1, 'Docker未成功完整结束；保留checkpoint，不自动重试')
    require(not any('fatal' in r for r in records), '执行器fatal，停止')
    write(output / 'observations-raw.json', final[0])
    return final[0]


def preflight(output):
    result = execute(payload('preflight', []), output)
    require(result['requests'] == result['rows'] == [] and result['complete'], '预检发生模型请求')
    return {'status': 'PASS_READONLY_PREFLIGHT', 'model_snapshot': result['model_snapshot'],
            'verified_sources': result['verified_sources'], 'model_http_requests': 0}


def prepare(preflight_dir, output):
    checked = load(preflight_dir / 'observations-raw.json')
    require(checked['mode'] == 'preflight' and checked['complete'] and checked['requests'] == [], '预检未通过')
    require(checked['source_sha256'] == source_hashes(), '源码在预检后变化')
    execution = load(preflight_dir / 'execution.json')
    require(execution['evaluation_sha256'] == eval_hashes(), '实验源码在预检后变化')
    questions, fingerprint = inputs()
    lookup = {q['id']: q for q in questions}
    require(set(SMOKE_IDS) <= set(lookup), '烟测题不在冻结开发集')
    smoke = tasks_for(SMOKE_IDS)
    full = smoke + tasks_for([q['id'] for q in questions if q['id'] not in SMOKE_IDS])
    output = safe_output(output)
    output.mkdir(parents=True)
    archive_sources(output)
    for variant in VARIANTS:
        (output / f'prompt-{variant}.txt').write_text(system_for(variant), encoding='utf-8')
    keys = [{**t, 'request_key': request_key(lookup[t['question_id']], t['variant'], checked['model_snapshot'])} for t in full]
    plan = {'protocol': 'resume-four-variants-v1', 'scope': 'development_given_candidates_only',
            'input_sha256': fingerprint, 'source_sha256': source_hashes(), 'evaluation_sha256': eval_hashes(),
            'preflight_path': str(preflight_dir.resolve()), 'preflight_sha256': sha((preflight_dir / 'observations-raw.json').read_bytes()),
            'model_snapshot': checked['model_snapshot'], 'smoke_ids': list(SMOKE_IDS), 'tasks': keys,
            'smoke_http_requests_max': 24, 'development_http_requests_max_including_smoke': 96,
            'sdk_retries': 0, 'automatic_retry': False, 'authorization_status': 'pending_new_allowance',
            'holdout_loaded': False, 'retrieval_executed': False,
            'smoke_gate': '全部请求与原始JSON/引用/usage协议通过且无unknown；错误分类记badcase，不能因基线错题排除题目',
            'model_quality_gate': '开发后决定方案，完整/部分误删和引用门禁不得退步',
            'inheritance': '开发扩量必须继承同输入/源码/模型/提示词key的24条烟测结果，不重复付费'}
    plan['task_wire_requests'] = {t['request_key']: expected_wire(lookup[t['question_id']], t['variant'], checked['model_snapshot']['model']) for t in keys}
    write(output / 'plan.json', plan)
    return {'status': 'PLAN_READY_NOT_EXECUTED', 'smoke_requests': 24, 'development_total_requests': 96, 'authorization': 'pending'}


def allocate(authorization, keys, output):
    from resume_allowance import allocate as reserve
    return reserve(HERE,authorization,keys,output,kind='diagnosis')


def paid_run(mode, plan_dir, authorization_path, output, parent=None):
    plan = load(plan_dir / 'plan.json')
    questions, fingerprint = inputs()
    require(plan['input_sha256'] == fingerprint and plan['source_sha256'] == source_hashes()
            and plan['evaluation_sha256'] == eval_hashes(), '冻结实验计划漂移')
    require(plan['authorization_status'] == 'pending_new_allowance', '未知计划状态')
    checked = load(Path(plan['preflight_path']) / 'observations-raw.json')
    require(sha((Path(plan['preflight_path']) / 'observations-raw.json').read_bytes()) == plan['preflight_sha256']
            and checked['model_snapshot'] == plan['model_snapshot'], '预检或模型快照变化')
    lookup = {q['id']: q for q in questions}
    expected_tasks = tasks_for(SMOKE_IDS) + tasks_for([q['id'] for q in questions if q['id'] not in SMOKE_IDS])
    expected_keys = [{**t, 'request_key': request_key(lookup[t['question_id']], t['variant'], checked['model_snapshot'])} for t in expected_tasks]
    require(plan['tasks'] == expected_keys and plan['smoke_ids'] == list(SMOKE_IDS), '实验任务/缓存key变化')
    require(plan['task_wire_requests'] == {t['request_key']: expected_wire(lookup[t['question_id']], t['variant'], checked['model_snapshot']['model']) for t in expected_keys}, '预注册请求体变化')
    inherited = []
    tasks = plan['tasks'][:24]
    if mode == 'development':
        require(parent is not None, '扩量必须有已验收烟测')
        # 先由独立验证器验收原始响应，再继承，不能只凭一份score放行。
        from resume_experiment_verify import verify_run
        verify_run(parent, plan_dir, 'smoke')
        inherited = load(parent / 'observations-raw.json')['rows']
        tasks = plan['tasks'][24:]
    output = safe_output(output)
    keys = [t['request_key'] for t in tasks]
    allocate(load(authorization_path), keys, output)
    value = payload(mode, [{k: t[k] for k in ('question_id', 'variant')} for t in tasks], plan['model_snapshot'])
    result = execute(value, output)
    require(all(r['status'] == 'success' for r in result['rows']), '执行异常，停止扩量')
    if inherited:
        write(output / 'inherited-smoke.json', {'path': str(parent.resolve()), 'sha256': sha((parent / 'observations-raw.json').read_bytes())})
    write(output / 'plan-reference.json', {'path': str(plan_dir.resolve()), 'sha256': sha((plan_dir / 'plan.json').read_bytes())})
    return {'status': 'REAL_REQUESTS_COMPLETE_PENDING_INDEPENDENT_SCORE', 'new_rows': len(result['rows']), 'inherited_rows': len(inherited)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['preflight', 'prepare', 'smoke', 'development'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--preflight', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--authorization', type=Path)
    parser.add_argument('--parent', type=Path)
    args = parser.parse_args()
    if args.mode == 'preflight':
        result = preflight(args.output)
    elif args.mode == 'prepare':
        require(args.preflight is not None, '缺预检目录');result = prepare(args.preflight, args.output)
    else:
        require(args.plan is not None and args.authorization is not None, '缺冻结计划或新额度授权')
        result = paid_run(args.mode, args.plan, args.authorization, args.output, args.parent)
    print(json.dumps(result, ensure_ascii=False))
