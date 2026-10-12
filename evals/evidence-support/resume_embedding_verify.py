"""独立核对真实批次及SDK解码；预检无向量，不声称语义检索成功。"""
import argparse
import json
import math
from pathlib import Path
from resume_experiment import ROOT,HERE,load,sha,require,write
from resume_embedding import EVAL_FILES,hashes,payload,verify_allocation
from resume_embedding_runtime import SOURCE_PATHS,decode_response,validate_payload


def core(folder,mode):
    folder=folder.resolve();folder.relative_to(HERE.resolve())
    execution=load(folder/'execution.json');value=load(folder/'execution-input.json');raw=load(folder/'observations-raw.json')
    validate_payload(value)
    require(value==payload(mode,raw['model_snapshot'] if mode=='collect' else None),'向量输入/源码/模型漂移')
    require(execution['docker_exit_code']==0 and not execution['timed_out'] and raw['complete'],'向量运行未完整成功')
    require(execution['input_sha256']==sha((folder/'execution-input.json').read_bytes())
            and raw['protocol']==value['protocol'] and raw['mode']==value['mode']==mode
            and raw['source_sha256']==value['source_sha256'] and raw['input_sha256']==value['input_sha256']
            and raw['questions']==value['questions'],'原始输出与实际输入不同')
    require(raw['read_only'] and raw['rolled_back'] and raw['read_gold'] is False and raw['settings_unchanged']
            and raw['settings_before']==raw['settings_after'] and raw['forbidden_http_attempts']==0
            and raw['status']=='success' and raw['error_type'] is None,'只读/保护/网络/状态门禁失败')
    for name in SOURCE_PATHS:require(sha((folder/'source'/name).read_bytes())==value['source_sha256'][name],'向量业务源码快照变化')
    require(execution['evaluation_sha256']==hashes(),'向量执行/核验源码版本变化')
    for name in EVAL_FILES:require(sha((folder/name).read_bytes())==execution['evaluation_sha256'][name],'向量实验源码快照变化')
    events=[json.loads(line) for line in (folder/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    require(events and set(events[0])=={'runtime_started'} and type(events[0]['runtime_started']['pid']) is int
            and events[0]['runtime_started']['pid']>0 and events[-1]=={'final':raw},'进程/最终记录缺失')
    require(type(raw['elapsed_ms']) in (int,float) and math.isfinite(raw['elapsed_ms']) and raw['elapsed_ms']>=0,'向量耗时非法')
    return raw,execution,events,value


def verify_preflight(folder):
    raw,execution,events,value=core(folder,'preflight')
    require(raw['requests']==raw['vectors']==[] and len(events)==2
            and execution['batch_key'] is None and events[0]['runtime_started']['batch_key']=='preflight','预检发生HTTP或有多余结果')
    snapshot=raw['model_snapshot']
    require(snapshot['sdk_retries']==0 and snapshot['follow_redirects'] is False and snapshot['encoding_format']=='base64'
            and type(snapshot['dimension']) is int and snapshot['dimension']>0
            and type(snapshot['chunks']) is int and snapshot['chunks']>0
            and isinstance(snapshot['corpus_sha256'],str) and len(snapshot['corpus_sha256'])==64,'向量预检参数非法')
    from app.services.text_privacy import redact_for_provider
    require(raw['wire_request']=={'model':snapshot['model'],'input':redact_for_provider([q['query'] for q in value['questions']]),'encoding_format':'base64'},'预检请求体与开发问题不同')
    return raw


def verify_collect(folder,plan_dir):
    raw,execution,events,value=core(folder,'collect')
    plan=load(plan_dir/'plan.json');reference=load(folder/'plan-reference.json')
    checked=verify_preflight(Path(plan['preflight_path']))
    require(plan['protocol']=='resume-query-embeddings-v1' and plan['scope']=='development_24_queries_only'
            and plan['holdout_loaded'] is False and plan['max_http_requests']==1
            and plan['authorization_status']=='pending_new_embedding_allowance'
            and plan['evaluation_sha256']==hashes()
            and plan['preflight_sha256']==sha((Path(plan['preflight_path'])/'observations-raw.json').read_bytes())
            and reference=={'path':str(plan_dir.resolve()),'sha256':sha((plan_dir/'plan.json').read_bytes())}
            and plan['payload']==value and plan['wire_request']==raw['wire_request']==checked['wire_request']
            and raw['model_snapshot']==checked['model_snapshot'],'向量计划/预检关联不一致')
    key=sha(json.dumps({'payload':value,'wire_request':plan['wire_request'],'evaluation_sha256':hashes()},sort_keys=True,ensure_ascii=False).encode())
    require(execution['batch_key']==plan['batch_key']==key==events[0]['runtime_started']['batch_key'],'向量批次key不同')
    audit=load(folder/'allocation-audit.json')
    require(audit['plan_reference']==reference,'发送前授权审计与计划不同')
    verify_allocation(audit,folder,key)
    require(len(raw['requests'])==1 and len(events)==4,'向量HTTP不是单次完整批量')
    record=raw['requests'][0]
    require(events[1]=={'http_started':{k:record[k] for k in ('wire_request','request_sha256')}} and events[2]=={'http_finished':record},'向量发送前/收包证据缺失')
    require(record['wire_request']==plan['wire_request'] and record['request_sha256']==sha(json.dumps(record['wire_request'],sort_keys=True,ensure_ascii=False).encode())
            and record['status_code']==200 and record['response_error_type'] is None,'实际向量请求体/状态不符')
    vectors,response=decode_response(record['raw_response'],24,raw['model_snapshot']['dimension'])
    require(raw['vectors']==vectors and record['native_usage']==response['usage'],'向量索引/原生结果/SDK解码/usage不一致')
    return {'status':'VERIFIED_REAL_QUERY_EMBEDDINGS_ONLY','queries':24,'http_requests':1,'batch_key':key,
            'model_snapshot':raw['model_snapshot'],'response_model':response['model'],'native_usage':response['usage'],
            'input_sha256':raw['input_sha256'],'elapsed_ms':raw['elapsed_ms'],'retrieval_metrics':None,'clinical_accuracy':None}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['preflight','collect']);parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--plan',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.mode=='preflight':
        raw=verify_preflight(args.run);result={'status':'PASS_EMBEDDING_PREFLIGHT_ONLY','snapshot':raw['model_snapshot'],'model_http_requests':0}
    else:
        require(args.plan is not None,'缺向量计划');result=verify_collect(args.run,args.plan)
    if args.output:write(args.output,result)
    print(json.dumps(result,ensure_ascii=False))
