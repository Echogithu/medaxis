"""归档执行器并在本地Docker只读运行新工具与旧路径对照。"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
from replay import ROOT,read,digest


def run(args):
    frozen=ROOT/'.ai/tasks/2026-10-07-rag-baseline/frozen-v1'
    original=read(frozen/'corpus.json');dataset=read(frozen/'dataset.json')
    task=ROOT/'.ai/tasks/2026-10-08-source-filter'
    payload={'corpus':original,'dataset':dataset,'embeddings':read(frozen.parent/'query-embeddings.json'),
        'stage3':read(ROOT/'.ai/tasks/2026-10-08-semantic-recall/union-final-v2/results.json'),
        'offline':read(args.offline/'results.json')}
    ids=[c['id'] for c in dataset['cases']] if not args.ids else args.ids.split(',')
    if not ids or len(set(ids))!=len(ids) or not set(ids)<={c['id'] for c in dataset['cases']}:raise ValueError('题目集合无效')
    payload['ids']=ids
    allowed={'app/services/rag.py','app/services/rag_context.py','app/services/knowledge_citations.py','app/tools/medical.py'}
    hashes={p.relative_to(ROOT/'backend').as_posix():digest(p) for p in (ROOT/'backend/app').rglob('*.py')}
    for name,sha in original['source_sha256'].items():
        if name not in allowed and hashes[name]!=sha:raise ValueError('未授权模块漂移：'+name)
    payload['corpus']={**original,'source_sha256':hashes,'demo_enabled':False}
    args.output.mkdir(parents=True,exist_ok=False)
    archive=args.output/'executor';archive.mkdir()
    modules=[('collect',ROOT/'evals/rag-baseline/collect.py'),('score',ROOT/'evals/rag-baseline/score.py'),
        ('score_v2',ROOT/'evals/semantic-recall/score_v2.py'),('eval_oldrag',task/'source-before/rag.py'),
        ('eval_oldcitations',task/'source-before/knowledge_citations.py'),('source_postgres',Path(__file__).with_name('postgres.py'))]
    code='import asyncio,base64,json,sys,types\n'
    for name,path in modules:
        filename=name+'.py';(archive/filename).write_bytes(path.read_bytes())
        encoded=base64.b64encode(path.read_bytes()).decode()
        code+=f'm=types.ModuleType({name!r});m.__file__={"/tmp/medaxis-filter/"+filename!r};sys.modules[{name!r}]=m\nexec(base64.b64decode({encoded!r}),m.__dict__)\n'
    encoded=base64.b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode()
    code+=f'payload=json.loads(base64.b64decode({encoded!r}))\nr=asyncio.run(sys.modules["source_postgres"].main(payload,sys.modules["eval_oldrag"],sys.modules["eval_oldcitations"]))\nprint(json.dumps(r,ensure_ascii=False,allow_nan=False))\n'
    execution=subprocess.run(['docker','exec','-i','-w','/app','medaxis-backend','python','-'],input=code,capture_output=True,text=True,encoding='utf-8')
    (args.output/'execution.json').write_text(json.dumps({'exit_code':execution.returncode,'stderr':execution.stderr},ensure_ascii=False,indent=2),encoding='utf-8')
    if execution.returncode:
        raise RuntimeError('实际入口失败：见execution.json')
    result=json.loads(execution.stdout)
    result.update(dataset_sha256=digest(frozen/'dataset.json'),corpus_sha256=digest(frozen/'corpus.json'),
        query_embeddings_sha256=digest(frozen.parent/'query-embeddings.json'),offline_sha256=digest(args.offline/'results.json'),
        source_sha256=hashes,executor_sha256={p.name:digest(p) for p in archive.iterdir()},api_process_loaded=None)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in allowed:
        path=ROOT/'backend'/name
        (archive/('current_'+path.name)).write_bytes(path.read_bytes())
    print(json.dumps({'mode':result['mode'],'n':len(ids),'before':result['groups']['before']['summary'],'after':result['groups']['after']['summary'],'extra_model_calls':0,'read_only':True},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ids');parser.add_argument('--offline',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args())
