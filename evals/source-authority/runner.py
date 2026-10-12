"""冻结当前语料、生成新题真实向量、执行同题实际检索对照；拒绝覆盖记录。"""
import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
TASK=ROOT/'.ai/tasks/2026-10-08-source-authority'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def inject(name,path):
    data=base64.b64encode(path.read_bytes()).decode()
    return f"m=types.ModuleType({name!r});m.__file__={'/tmp/source-authority/'+name+'.py'!r};sys.modules[{name!r}]=m\nexec(base64.b64decode({data!r}),m.__dict__)\n"


def execute(code,output,modules):
    output.mkdir(parents=True,exist_ok=False);archive=output/'executor';archive.mkdir()
    script='import asyncio,base64,json,sys,types\n'
    for name,path in modules:
        (archive/(name+'.py')).write_bytes(path.read_bytes());script+=inject(name,path)
    script+=code
    result=subprocess.run(['docker','exec','-i','-w','/app','medaxis-backend','python','-'],input=script,capture_output=True,text=True,encoding='utf-8')
    (output/'execution.json').write_text(json.dumps({'exit_code':result.returncode,'stderr':result.stderr},ensure_ascii=False,indent=2),encoding='utf-8')
    if result.returncode:raise RuntimeError('实际执行失败，查看execution.json')
    data=json.loads(result.stdout)
    (output/'results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return data


def main(args):
    collector=ROOT/'evals/rag-baseline/collect.py'
    if args.mode=='snapshot':
        data=execute('print(json.dumps(asyncio.run(sys.modules["collect"].collect()),ensure_ascii=False))\n',args.output,[('collect',collector)])
        print(f"snapshot: {len(data['documents'])} docs/{len(data['chunks'])} chunks; demo_enabled={data['demo_enabled']}")
    elif args.mode=='embeddings':
        dataset=read(args.dataset);queries=[c['query'] for c in dataset['cases']]
        encoded=base64.b64encode(json.dumps(queries,ensure_ascii=False).encode()).decode()
        data=execute(f'print(json.dumps(asyncio.run(sys.modules["collect"].embeddings({encoded!r},single_attempt=True)),ensure_ascii=False))\n',args.output,[('collect',collector)])
        if data['queries']!=queries or len(data['vectors'])!=len(queries):raise ValueError('向量不齐')
        print(json.dumps({'n':len(queries),'http_attempts':data['http_attempts'],'calls':data['calls'],'sdk_retries':data['sdk_retries']},ensure_ascii=False))
    else:
        corpus=read(args.corpus);dataset=read(args.dataset);embeddings=read(args.embeddings)
        hashes={p.relative_to(ROOT/'backend').as_posix():digest(p) for p in (ROOT/'backend/app').rglob('*.py')}
        for name,sha in corpus['source_sha256'].items():
            if name!='app/services/rag.py' and hashes[name]!=sha:raise ValueError('非目标源码发生漂移：'+name)
        payload={'corpus':{**corpus,'source_sha256':hashes},'dataset':dataset,'embeddings':embeddings}
        encoded=base64.b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode()
        modules=[('collect',collector),('score',ROOT/'evals/rag-baseline/score.py'),('score_v2',ROOT/'evals/semantic-recall/score_v2.py'),
            ('authority_old_rag',TASK/'source-before/rag.py'),('authority_postgres',Path(__file__).with_name('postgres.py'))]
        data=execute(f'p=json.loads(base64.b64decode({encoded!r}))\nr=asyncio.run(sys.modules["authority_postgres"].evaluate(p,sys.modules["authority_old_rag"]))\nprint(json.dumps(r,ensure_ascii=False,allow_nan=False))\n',args.output,modules)
        for name in ('rag.py','rag_context.py','knowledge_citations.py'):
            (args.output/'executor'/('current_'+name)).write_bytes((ROOT/'backend/app/services'/name).read_bytes())
        (args.output/'executor/current_medical.py').write_bytes((ROOT/'backend/app/tools/medical.py').read_bytes())
        (args.output/'executor/runner.py').write_bytes(Path(__file__).read_bytes())
        data.update(dataset_sha256=digest(args.dataset),corpus_sha256=digest(args.corpus),embeddings_sha256=digest(args.embeddings),
            source_sha256=hashes,executor_sha256={p.name:digest(p) for p in (args.output/'executor').iterdir()},api_process_loaded=None)
        (args.output/'results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'n':len(dataset['cases']),**{k:g['summary'] for k,g in data['groups'].items()},'extra_model_calls':0},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['snapshot','embeddings','evaluate'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--dataset',type=Path);p.add_argument('--corpus',type=Path);p.add_argument('--embeddings',type=Path)
    main(p.parse_args())
