"""冻结输入的Docker真实生产函数诊断。拒绝覆盖；执行器不接收gold。"""
import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / '.ai/tasks/2026-10-09-evidence-support/frozen-v3'
BASELINE = ROOT / '.ai/tasks/2026-10-09-evidence-support/baseline-v2'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(mode, output_root=BASELINE, assets_dir=FROZEN):
    from verify import validate
    validate(assets_dir, check_production=True)
    output_root = output_root.resolve()
    output_root.relative_to((ROOT / '.ai/tasks/2026-10-09-evidence-support').resolve())
    inputs = read(assets_dir / 'inputs.json')
    if mode == 'smoke':
        if inputs['version'].startswith('query-development-'):
            # 只依据已排序的不透明输入ID取样，不读取金标或候选类型。
            selected = inputs['cases'][:6]
        else:
            selected = []
            for family, count in [('query_specificity', 2), ('statement_support', 2), ('applicability', 1), ('version_scope', 1)]:
                selected.extend([c for c in inputs['cases'] if c['family'] == family][:count])
        inputs['cases'] = selected
    else:
        smoke = read(output_root / 'smoke/observations.json')
        if smoke['input_sha256'] != digest(assets_dir / 'inputs.json') or smoke['version'] != inputs['version']:
            raise ValueError('小样本与完整运行题库不同')
        if len(smoke['rows']) != 6 or any(r['status'] == 'execution_error' for r in smoke['rows']) or not smoke['settings_unchanged']:
            raise ValueError('小样本执行失败，禁止完整诊断')
        if read(output_root / 'smoke/execution.json')['runtime_sha256'] != digest(Path(__file__).with_name('baseline_runtime.py')):
            raise ValueError('执行协议已变，须重跑小样本')
    manifest = read(assets_dir / 'manifest.json')
    expected = {name.removeprefix('backend/'): sha for name, sha in manifest['production_sha256'].items()}
    for name, sha in manifest['production_sha256'].items():
        if digest(ROOT / name) != sha:
            raise ValueError('本地生产源码漂移，停止：' + name)
    payload = {'inputs': inputs, 'input_sha256': digest(assets_dir / 'inputs.json'), 'expected_production_sha256': expected}
    output = output_root / mode
    output.mkdir(parents=True, exist_ok=False)
    module = Path(__file__).with_name('baseline_runtime.py')
    (output / 'runtime.py').write_bytes(module.read_bytes())
    (output / 'runner.py').write_bytes(Path(__file__).read_bytes())
    (output / 'execution-input.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding='utf-8')
    code = (
        'import asyncio,base64,json,types\n'
        "m=types.ModuleType('baseline_runtime');m.__file__='/tmp/baseline_runtime.py'\n"
        f"exec(base64.b64decode({base64.b64encode(module.read_bytes()).decode()!r}),m.__dict__)\n"
        f"p=json.loads(base64.b64decode({base64.b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode()!r}))\n"
        'print(json.dumps(asyncio.run(m.evaluate(p)),ensure_ascii=False,allow_nan=False))\n'
    )
    result = subprocess.run(['docker', 'exec', '-i', '-w', '/app', 'medaxis-backend', 'python', '-'],
                            input=code, capture_output=True, text=True, encoding='utf-8', timeout=180)
    # 执行器只输出安全JSON；异常文本只记录类型/退出码，避免潜在连接信息进入记录。
    execution = {'docker_exit_code': result.returncode, 'runtime_sha256': digest(module),
                 'runner_sha256': digest(Path(__file__)), 'stderr_present': bool(result.stderr.strip()),
                 'read_gold_in_executor': False, 'mode': mode}
    (output / 'execution.json').write_text(json.dumps(execution, indent=2), encoding='utf-8')
    if result.returncode:
        raise RuntimeError('容器执行失败：exit=' + str(result.returncode))
    data = json.loads(result.stdout)
    inspect = subprocess.run(['docker', 'inspect', '--format', '{{.State.StartedAt}}', 'medaxis-backend'],
                             capture_output=True, text=True, encoding='utf-8', check=True)
    data['container_started_at'] = inspect.stdout.strip()
    data['execution_input_sha256'] = digest(output / 'execution-input.json')
    (output / 'observations.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'mode': mode, 'rows': len(data['rows']),
                      'executed': sum(r['status'] == 'executed' for r in data['rows']),
                      'capability_absent': sum(r['status'] == 'capability_absent' for r in data['rows']),
                      'errors': sum(r['status'] == 'execution_error' for r in data['rows']),
                      'settings_unchanged': data['settings_unchanged'], 'extra_model_calls': data['extra_model_calls']}, ensure_ascii=False))
    if any(r['status'] == 'execution_error' for r in data['rows']) or not data['settings_unchanged']:
        raise ValueError('执行质量或配置不变门禁失败')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['smoke', 'full'])
    parser.add_argument('--output-root', type=Path, default=BASELINE)
    parser.add_argument('--assets-dir', type=Path, default=FROZEN)
    args = parser.parse_args()
    run(args.mode, args.output_root, args.assets_dir)
