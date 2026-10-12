"""真实向量取证后才运行三路检索；预检技术探针不产生检索质量成绩。"""
import argparse
import base64
import json
import subprocess
from pathlib import Path
from resume_experiment import ROOT,HERE,inputs,load,sha,require,write,safe_output
from resume_embedding import payload as embedding_payload
from resume_embedding_verify import verify_preflight,verify_collect
from resume_retrieval_runtime import SOURCE_PATHS

EVAL_FILES=('resume_retrieval.py','resume_retrieval_runtime.py','resume_retrieval_verify.py','resume_keyword_runtime.py',
            'resume_embedding_runtime.py','resume_eval_score.py','build_resume_eval.py')


def payload(mode,embedding_preflight,vector_run=None,vector_plan=None):
    raw=verify_preflight(embedding_preflight)
    probe=embedding_payload('preflight')
    vectors=None;evidence=None
    if mode=='run':
        require(vector_run is not None and vector_plan is not None,'缺实际向量运行及冻结计划')
        checked=verify_collect(vector_run,vector_plan);observed=load(vector_run/'observations-raw.json')
        require(checked['model_snapshot']==raw['model_snapshot'] and checked['input_sha256']==probe['input_sha256'],'真实向量与当前预检范围不同')
        vectors=observed['vectors'];evidence=sha((vector_run/'observations-raw.json').read_bytes())
    return {'protocol':'resume-retrieval-ablation-v1','mode':mode,'questions':probe['questions'],'documents':probe['documents'],
            'input_sha256':probe['input_sha256'],'source_sha256':{n:sha((ROOT/'backend'/n).read_bytes()) for n in SOURCE_PATHS},
            'top_k':10,'embedding_probe':probe,'expected_snapshot':raw['model_snapshot'],'vectors':vectors,'vector_evidence_sha256':evidence}


def execute(value,output,reference):
    from resume_retrieval_runtime import validate_payload
    validate_payload(value)
    if value['mode']=='run':
        # 公共执行入口也重新验证，不能直接传人工向量绕过真实响应取证。
        require(value==payload('run',Path(reference['preflight']),Path(reference['vector_run']),Path(reference['vector_plan'])),'实际查询向量/输入/来源变化')
    else:require(value==payload('preflight',Path(reference['preflight'])),'预检输入变化')
    output=safe_output(output);output.mkdir(parents=True)
    for name in EVAL_FILES:(output/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    for name in SOURCE_PATHS:
        target=output/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/'backend'/name).read_bytes())
    write(output/'execution-input.json',value);write(output/'references.json',reference)
    modules=[(name[:-3],base64.b64encode(Path(__file__).with_name(name).read_bytes()).decode())
             for name in ('resume_embedding_runtime.py','resume_keyword_runtime.py','resume_retrieval_runtime.py')]
    encoded=base64.b64encode(json.dumps(value,ensure_ascii=False).encode()).decode()
    code=('import asyncio,base64,json,sys,types,os\n'
          'print(json.dumps({"runtime_started":{"pid":os.getpid(),"purpose":"retrieval_ablation"}}),flush=True)\n'
          f'modules={modules!r}\n'
          'for name,blob in modules:\n'
          ' m=types.ModuleType(name);m.__file__="/tmp/"+name+".py";sys.modules[name]=m\n'
          ' exec(compile(base64.b64decode(blob),m.__file__,"exec"),m.__dict__)\n'
          f'p=json.loads(base64.b64decode({encoded!r}))\n'
          'try:\n'
          ' r=asyncio.run(sys.modules["resume_retrieval_runtime"].run(p));print(json.dumps({"final":r},ensure_ascii=False,allow_nan=False),flush=True);sys.exit(0 if r["complete"] else 1)\n'
          'except Exception as e:\n'
          ' print(json.dumps({"fatal":{"error_type":type(e).__name__}},ensure_ascii=False),flush=True);sys.exit(1)\n')
    exit_code=None;timed_out=False
    with (output/'checkpoints.jsonl').open('x',encoding='utf-8') as stream:
        try:
            result=subprocess.run(['docker','exec','-i','-w','/app','medaxis-backend','python','-'],input=code,
                stdout=stream,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',timeout=120)
            exit_code=result.returncode
        except subprocess.TimeoutExpired:timed_out=True
    write(output/'execution.json',{'docker_exit_code':exit_code,'timed_out':timed_out,
          'input_sha256':sha((output/'execution-input.json').read_bytes()),'references_sha256':sha((output/'references.json').read_bytes()),
          'evaluation_sha256':{n:sha(Path(__file__).with_name(n).read_bytes()) for n in EVAL_FILES},'additional_model_http_requests':0})
    events=[json.loads(s) for s in (output/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    final=[e['final'] for e in events if set(e)=={'final'}]
    if len(final)==1:write(output/'observations-raw.json',final[0])
    require(exit_code==0 and not timed_out and len(final)==1 and final[0]['complete'],'检索运行未成功，保留证据不自动重发')
    return {'status':'RETRIEVAL_PREFLIGHT_ONLY' if value['mode']=='preflight' else 'REAL_RETRIEVAL_PENDING_OFFLINE_VERIFICATION',
            'rows':len(final[0]['rows']),'additional_model_http_requests':0,'retrieval_metrics':None}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['preflight','run'])
    parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--vectors',type=Path);parser.add_argument('--vector-plan',type=Path);args=parser.parse_args()
    reference={'preflight':str(args.preflight.resolve()),'vector_run':str(args.vectors.resolve()) if args.vectors else None,
               'vector_plan':str(args.vector_plan.resolve()) if args.vector_plan else None}
    value=payload(args.mode,args.preflight,args.vectors,args.vector_plan)
    print(json.dumps(execute(value,args.output,reference),ensure_ascii=False))
