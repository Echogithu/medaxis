"""复用真实RAG的关键词回退，比较原始chunk与邻接补全；HTTP0。"""
import argparse
import base64
import json
import subprocess
from pathlib import Path
from resume_experiment import ROOT, HERE, inputs, load, sha, require, write, safe_output
from resume_keyword_runtime import SOURCE_PATHS

EVAL_FILES=('resume_keyword.py','resume_keyword_runtime.py','resume_keyword_verify.py',
            'resume_eval_score.py','build_resume_eval.py')


def payload():
    questions,fingerprint=inputs()
    docs={s['document_id']:{k:s[k] for k in ('document_id','document_sha256','title','source_url')}
          for q in questions for s in q['candidates']}
    return {'protocol':'resume-keyword-context-ablation-v1','questions':[{k:q[k] for k in ('id','query')} for q in questions],
            'documents':sorted(docs.values(),key=lambda d:d['document_id']),'input_sha256':fingerprint,'top_k':10,
            'source_sha256':{n:sha((ROOT/'backend'/n).read_bytes()) for n in SOURCE_PATHS}}


def execute(output):
    output=safe_output(output);output.mkdir(parents=True)
    sources=output/'source';sources.mkdir()
    for name in SOURCE_PATHS:
        target=sources/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/'backend'/name).read_bytes())
    hashes={}
    for name in EVAL_FILES:
        data=Path(__file__).with_name(name).read_bytes();(output/name).write_bytes(data);hashes[name]=sha(data)
    value=payload();write(output/'execution-input.json',value)
    module=base64.b64encode(Path(__file__).with_name('resume_keyword_runtime.py').read_bytes()).decode()
    encoded=base64.b64encode(json.dumps(value,ensure_ascii=False).encode()).decode()
    code=('import asyncio,base64,json,sys,types\n'
          'm=types.ModuleType("resume_keyword_runtime");m.__file__="/tmp/resume_keyword_runtime.py";sys.modules[m.__name__]=m\n'
          f'exec(compile(base64.b64decode({module!r}),m.__file__,"exec"),m.__dict__)\n'
          f'p=json.loads(base64.b64decode({encoded!r}))\n'
          'try:\n'
          ' r=asyncio.run(m.run(p));print(json.dumps({"final":r},ensure_ascii=False,allow_nan=False),flush=True);sys.exit(0 if r["complete"] else 1)\n'
          'except Exception as e:\n'
          ' print(json.dumps({"fatal":{"error_type":type(e).__name__}},ensure_ascii=False),flush=True);sys.exit(1)\n')
    exit_code=None;timed_out=False
    with (output/'checkpoints.jsonl').open('x',encoding='utf-8') as stream:
        try:
            result=subprocess.run(['docker','exec','-i','-w','/app','medaxis-backend','python','-'],input=code,
                                  stdout=stream,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',timeout=90)
            exit_code=result.returncode
        except subprocess.TimeoutExpired:timed_out=True
    write(output/'execution.json',{'docker_exit_code':exit_code,'timed_out':timed_out,
          'input_sha256':sha((output/'execution-input.json').read_bytes()),'evaluation_sha256':hashes,'model_http_requests':0,
          'note':'超时不证明容器进程终止，不自动重发；此入口的模型和HTTP被强制禁止'})
    events=[json.loads(line) for line in (output/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    final=[e['final'] for e in events if set(e)=={'final'}]
    require(exit_code==0 and not timed_out and len(final)==1 and not any('fatal' in e for e in events),'关键词运行失败，保留记录')
    write(output/'observations-raw.json',final[0])
    return {'status':'REAL_KEYWORD_ABLATION_PENDING_OFFLINE_VERIFICATION','groups':len(final[0]['rows']),'model_http_requests':0,'full_production_pipeline':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(execute(args.output),ensure_ascii=False))
