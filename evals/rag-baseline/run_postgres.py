"""把只读检索程序通过stdin送入现有容器；本地保存逐题结果及执行器快照。"""
import argparse
import base64
from datetime import datetime,timezone
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
from build import read,digest,validate


def run(args):
    frozen=args.frozen.resolve()
    corpus=read(frozen/'corpus.json');dataset=read(frozen/'dataset.json')
    validate(corpus,dataset)
    if dataset['snapshot_sha256']!=digest(frozen/'corpus.json'):raise ValueError('题库与语料指纹不同')
    for name,sha in corpus['source_sha256'].items():
        if digest(frozen/'source'/name)!=sha:raise ValueError('冻结源码发生变化')
    artifact=read(args.embeddings)
    payload={'corpus':corpus,'dataset':dataset,'embeddings':artifact,'ids':args.ids.split(',') if args.ids else []}
    args.output.mkdir(parents=True,exist_ok=False)
    names=('build.py','score.py','replay.py','collect.py','topics.json','postgres.py','run_postgres.py')
    archive=args.output/'executor';archive.mkdir()
    for name in names:shutil.copyfile(Path(__file__).with_name(name),archive/name)
    code='import asyncio,base64,json,sys,types\n'
    for name in ('build','score','collect','postgres'):
        encoded=base64.b64encode((archive/f'{name}.py').read_bytes()).decode()
        code+=f'module=types.ModuleType({name!r});module.__file__={"/tmp/medaxis-rag-eval/"+name+".py"!r};sys.modules[{name!r}]=module\n'
        code+=f'exec(base64.b64decode({encoded!r}),module.__dict__)\n'
    encoded=base64.b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode()
    code+=f'payload=json.loads(base64.b64decode({encoded!r}))\nsys.exit(asyncio.run(sys.modules["postgres"].main(payload)))\n'
    command=['docker','exec','-i','-w','/app',args.container,'python','-']
    actual=subprocess.run(command,input=code,text=True,encoding='utf-8',capture_output=True)
    (args.output/'execution.json').write_text(json.dumps({'command':command,'exit_code':actual.returncode,
          'stderr':actual.stderr,'recorded_at':datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2),encoding='utf-8')
    if actual.returncode!=0:
        (args.output/'failed-response.json').write_text(actual.stdout,encoding='utf-8')
        raise ValueError('只读容器入口失败；见execution.json和failed-response.json')
    result=json.loads(actual.stdout)
    result.update(dataset_sha256=digest(frozen/'dataset.json'),corpus_sha256=digest(frozen/'corpus.json'),
        query_embeddings_sha256=digest(args.embeddings),runner_sha256=digest(Path(__file__)),
        scorer_sha256=digest(Path(__file__).with_name('score.py')),
        executor_sha256={name:digest(archive/name) for name in names},recorded_at=datetime.now(timezone.utc).isoformat(),
        environment={'local_python':platform.python_version(),'database':'PostgreSQL','container':args.container})
    shutil.copyfile(args.embeddings,args.output/'query-embeddings.json')
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    report=['# 实际PostgreSQL检索基线','',
        '复用一次真实模型生成的45条查询向量；在实际数据库运行原RAGService.search和最终来源排序，只读事务回滚。',
        '未修改业务检索算法。没有额外模型/网络调用；不是问诊、报告生成或完整HTTP端到端成绩。gold仍待专业核对。','',
        '查询向量使用text-embedding-3-small/1536维。计时不含首次向量请求，不能作为生产端到端耗时。','',
        '```json',json.dumps(result['summary'],ensure_ascii=False,indent=2),'```','',
        '| ID | 类型 | 粗召回命中 | 最终命中 | 完整证据 | 限定条件 | 来源数 |',
        '|---|---|---|---|---|---|---|']
    for row in result['cases']:
        s=row.get('score',{});coarse=row.get('stage_scores',{}).get('coarse',{})
        report.append(f"| {row['id']} | {row.get('family')} | {coarse.get('hit_at_k')} | {s.get('hit_at_k')} | {s.get('complete_evidence')} | {s.get('qualifier_recall')} | {len(row.get('sources',[]))} |")
    (args.output/'REPORT.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(json.dumps({'mode':result['mode'],**result['summary'],'additional_network_attempts':result['additional_network_attempts']},ensure_ascii=False))
    return 0 if result['summary']['status']=='complete_diagnostic' else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frozen',type=Path,required=True);p.add_argument('--embeddings',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--container',default='medaxis-backend');p.add_argument('--ids')
    args=p.parse_args()
    try:return run(args)
    except (ValueError,KeyError,OSError) as exc:
        print(f'评测拒绝：{exc}',file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
