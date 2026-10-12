"""预注册一次开发集向量批次；缺明确embedding额度时禁止供应商调用。"""
import argparse
import base64
import json
import subprocess
from pathlib import Path
from resume_experiment import ROOT,HERE,inputs,load,sha,require,write,safe_output
from resume_embedding_runtime import SOURCE_PATHS
from resume_allowance import allocate

EVAL_FILES=('resume_embedding.py','resume_embedding_runtime.py','resume_embedding_verify.py','resume_allowance.py')


def hashes():return {n:sha(Path(__file__).with_name(n).read_bytes()) for n in EVAL_FILES}


def payload(mode,snapshot=None):
    questions,fingerprint=inputs()
    docs={s['document_id']:{k:s[k] for k in ('document_id','document_sha256','title','source_url')} for q in questions for s in q['candidates']}
    return {'protocol':'resume-query-embeddings-v1','mode':mode,'questions':[{k:q[k] for k in ('id','query')} for q in questions],
            'documents':sorted(docs.values(),key=lambda d:d['document_id']),'input_sha256':fingerprint,
            'source_sha256':{n:sha((ROOT/'backend'/n).read_bytes()) for n in SOURCE_PATHS},'expected_snapshot':snapshot,
            'max_http_requests':0 if mode=='preflight' else 1}


def archive(output):
    for name in EVAL_FILES:(output/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    for name in SOURCE_PATHS:
        target=output/'source'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/'backend'/name).read_bytes())


def verify_allocation(audit,output,batch_key):
    require(set(audit)=={'allocation','authorization','plan_reference'},'缺向量调用授权证据')
    auth=audit['authorization'];allocation=audit['allocation']
    required={'status','source','message_reference','max_diagnosis_http_requests','max_embedding_http_requests','scope'}
    require(set(auth)==required and auth['status']=='approved' and auth['source']=='human_user_message'
            and isinstance(auth['message_reference'],str) and bool(auth['message_reference'].strip())
            and auth['scope']==str(HERE.resolve())
            and type(auth['max_embedding_http_requests']) is int and auth['max_embedding_http_requests']>0
            and type(auth['max_diagnosis_http_requests']) is int and auth['max_diagnosis_http_requests']>0,'授权来源/范围/额度非法')
    require(allocation['output']==str(output.resolve()) and allocation['request_kind']=='embedding'
            and type(allocation['reserved_requests']) is int and allocation['reserved_requests']==1 and allocation['request_keys']==[batch_key]
            and allocation['authorization_sha256']==sha(json.dumps(auth,sort_keys=True).encode()),'预留与本次授权/批次不同')
    ledger=[json.loads(line) for line in (HERE/'paid-allocations.jsonl').read_text(encoding='utf-8').splitlines()]
    matches=[row for row in ledger if batch_key in row['request_keys']]
    require(matches==[allocation],'预留账本缺失或重复')
    return allocation


def execute(value,output,batch_key=None,audit=None):
    output=safe_output(output)
    if value['mode']=='collect':
        require(isinstance(audit,dict),'付费执行缺授权/预留证据')
        verify_allocation(audit,output,batch_key)
    else:require(value['mode']=='preflight' and audit is None and batch_key is None,'预检不可带付费批次')
    output.mkdir(parents=True);archive(output)
    if audit:
        write(output/'allocation-audit.json',audit)
        write(output/'plan-reference.json',audit['plan_reference'])
    write(output/'execution-input.json',value)
    module=base64.b64encode(Path(__file__).with_name('resume_embedding_runtime.py').read_bytes()).decode()
    encoded=base64.b64encode(json.dumps(value,ensure_ascii=False).encode()).decode()
    code=('import asyncio,base64,json,sys,types,os\n'
          f'os.environ["MEDAXIS_EVAL_BATCH_KEY"]={batch_key!r} or "preflight"\n'
          'print(json.dumps({"runtime_started":{"pid":os.getpid(),"batch_key":os.environ["MEDAXIS_EVAL_BATCH_KEY"]}}),flush=True)\n'
          'm=types.ModuleType("resume_embedding_runtime");m.__file__="/tmp/resume_embedding_runtime.py";sys.modules[m.__name__]=m\n'
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
    write(output/'execution.json',{'docker_exit_code':exit_code,'timed_out':timed_out,'batch_key':batch_key,
         'input_sha256':sha((output/'execution-input.json').read_bytes()),'evaluation_sha256':hashes(),
         'note':'超时不证明容器子进程终止；保留pid/batch_key供只读核查，禁止未知请求自动补发'})
    records=[json.loads(line) for line in (output/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    final=[r['final'] for r in records if set(r)=={'final'}]
    if len(final)==1:write(output/'observations-raw.json',final[0])
    require(exit_code==0 and not timed_out and len(final)==1 and final[0]['complete'],'向量运行未成功；保留全部证据，不自动重试')
    return final[0]


def preflight(output):
    result=execute(payload('preflight'),output)
    require(result['requests']==result['vectors']==[],'向量预检发生供应商调用')
    return {'status':'PASS_EMBEDDING_PREFLIGHT_ONLY','snapshot':result['model_snapshot'],'model_http_requests':0}


def prepare(preflight_dir,output):
    from resume_embedding_verify import verify_preflight
    checked=verify_preflight(preflight_dir)
    value=payload('collect',checked['model_snapshot'])
    key=sha(json.dumps({'payload':value,'wire_request':checked['wire_request'],'evaluation_sha256':hashes()},sort_keys=True,ensure_ascii=False).encode())
    output=safe_output(output);output.mkdir(parents=True);archive(output)
    plan={'protocol':'resume-query-embeddings-v1','scope':'development_24_queries_only','payload':value,
          'wire_request':checked['wire_request'],'evaluation_sha256':hashes(),'batch_key':key,'max_http_requests':1,
          'preflight_path':str(preflight_dir.resolve()),'preflight_sha256':sha((preflight_dir/'observations-raw.json').read_bytes()),
          'authorization_status':'pending_new_embedding_allowance','holdout_loaded':False}
    write(output/'plan.json',plan)
    return {'status':'EMBEDDING_PLAN_READY_NOT_CALLED','queries':24,'http_requests_max':1,'authorization':'pending'}


def collect(plan_dir,authorization_path,output):
    from resume_embedding_verify import verify_preflight
    plan=load(plan_dir/'plan.json');checked=verify_preflight(Path(plan['preflight_path']))
    require(plan['protocol']=='resume-query-embeddings-v1' and plan['scope']=='development_24_queries_only'
            and plan['payload']==payload('collect',checked['model_snapshot']) and plan['evaluation_sha256']==hashes()
            and plan['wire_request']==checked['wire_request'] and plan['max_http_requests']==1
            and plan['preflight_sha256']==sha((Path(plan['preflight_path'])/'observations-raw.json').read_bytes()),'向量计划或预检漂移')
    key=sha(json.dumps({'payload':plan['payload'],'wire_request':plan['wire_request'],'evaluation_sha256':hashes()},sort_keys=True,ensure_ascii=False).encode())
    require(plan['batch_key']==key and plan['authorization_status']=='pending_new_embedding_allowance'
            and plan['holdout_loaded'] is False,'向量key/范围非法')
    output=safe_output(output)
    authorization=load(authorization_path)
    allocation=allocate(HERE,authorization,[key],output,kind='embedding')
    # 发送前保存关联；失败或未知请求的账本预留不得回收或自动补发。
    audit={'allocation':allocation,'authorization':authorization,
           'plan_reference':{'path':str(plan_dir.resolve()),'sha256':sha((plan_dir/'plan.json').read_bytes())}}
    result=execute(plan['payload'],output,key,audit)
    return {'status':'REAL_EMBEDDINGS_PENDING_OFFLINE_VERIFICATION','vectors':len(result['vectors']),'http_requests':len(result['requests'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['preflight','prepare','collect'])
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--preflight',type=Path)
    parser.add_argument('--plan',type=Path);parser.add_argument('--authorization',type=Path);args=parser.parse_args()
    if args.mode=='preflight':result=preflight(args.output)
    elif args.mode=='prepare':
        require(args.preflight is not None,'缺向量预检');result=prepare(args.preflight,args.output)
    else:
        require(args.plan is not None and args.authorization is not None,'缺冻结计划或明确embedding额度')
        result=collect(args.plan,args.authorization,args.output)
    print(json.dumps(result,ensure_ascii=False))
