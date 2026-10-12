"""实验控制与离线核验的隔离fixture；不联网，不产生真实模型成绩。"""
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
import httpx
from app.services.query_requirements import SYSTEM, make_messages, parse_assessment, rank_assessed
import resume_experiment as runner
import resume_experiment_verify as verifier
from resume_runtime import RequestObserver, digest, validate_payload, expected_wire
from resume_variants import VARIANTS, messages_for, system_for, request_key
import resume_allowance

CLI_FAILURES = []


class ExperimentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.questions, self.fingerprint = runner.inputs()
        self.q = copy.deepcopy(self.questions[0])
        self.snapshot = {'provider':'fixture', 'model':'fixture-model', 'sdk_retries':0,
                         'temperature_wire':'omitted', 'max_tokens':4096, 'timeout_seconds':60,
                         'thinking':'disabled', 'follow_redirects':False,
                         'endpoint_sha256':'fixture-endpoint', 'origin_sha256':'fixture-origin'}

    def test_baseline_exact_and_variants_change_only_planned_factor(self):
        baseline = make_messages(self.q['query'], [{'id':s['id'],'title':s['title'],'excerpt':s['quote']} for s in self.q['candidates']])
        self.assertEqual(SYSTEM, system_for('B0'))
        self.assertEqual(SYSTEM, system_for('B2'))
        self.assertEqual(baseline, messages_for(self.q,'B0'))
        self.assertEqual(baseline, messages_for(self.q,'B1'))
        self.assertEqual(system_for('B1'), system_for('B3'))
        self.assertNotEqual(SYSTEM, system_for('B1'))
        self.assertEqual(messages_for(self.q,'B2'), messages_for(self.q,'B3'))
        enriched = json.loads(messages_for(self.q,'B2')[0]['content'])
        for s, c in zip(self.q['candidates'], enriched['candidates']):
            self.assertEqual(s['quote'], c['excerpt'])
            self.assertEqual(s['source_url'], c['verified_source_identity']['source_url'])
            self.assertEqual({'id','title','excerpt','verified_source_identity'},set(c))

    def test_request_key_invalidates_prompt_query_model_and_metadata(self):
        key = request_key(self.q,'B3',self.snapshot)
        for change in ('query','quote','start','publisher','model'):
            q, snapshot = copy.deepcopy(self.q), copy.deepcopy(self.snapshot)
            if change == 'query': q['query'] += '补充问题'
            elif change == 'quote': q['candidates'][0]['quote'] += '补充原文'
            elif change == 'start': q['candidates'][0]['start'] += 1
            elif change == 'publisher': q['candidates'][0]['metadata']['publisher'] += '不同'
            else: snapshot['model'] += '-different'
            self.assertNotEqual(key, request_key(q,'B3',snapshot),change)
        self.assertEqual(4,len({request_key(self.q,v,self.snapshot) for v in VARIANTS}))
        with patch('resume_variants.PROMPT_ADDITION','不同提示词'):
            self.assertNotEqual(key,request_key(self.q,'B3',self.snapshot))

    def test_runtime_payload_rejects_gold_duplicate_tasks_and_wrong_budget(self):
        base = runner.payload('smoke',runner.tasks_for(runner.SMOKE_IDS),self.snapshot)
        self.assertEqual(24,len(validate_payload(base)))
        changes = []
        x=copy.deepcopy(base);x['gold']={};changes.append(x)
        x=copy.deepcopy(base);x['questions'][0]['expected_label']='answers';changes.append(x)
        x=copy.deepcopy(base);x['tasks'].append(x['tasks'][0]);x['max_http_requests']+=1;changes.append(x)
        x=copy.deepcopy(base);x['max_http_requests']+=1;changes.append(x)
        x=copy.deepcopy(base);x['mode']='preflight';changes.append(x)
        for x in changes:
            with self.assertRaises(ValueError): validate_payload(x)

    def observer(self):
        obj=RequestObserver(1)
        obj.active={'question_id':self.q['id'],'variant':'B0'}
        obj.wire=expected_wire(self.q,'B0','fixture-model')
        obj.origin_sha256=digest(json.dumps(['https','fixture.invalid',None]).encode())
        return obj

    def request(self, body):
        return httpx.Request('POST','https://fixture.invalid/v1/chat/completions',json=body)

    def test_actual_wire_budget_origin_and_started_checkpoint(self):
        obj=self.observer()
        output=io.StringIO()
        with redirect_stdout(output): record=obj.before(self.request(obj.wire))
        emitted=json.loads(output.getvalue())
        self.assertEqual(1,emitted['sequence'])
        self.assertEqual(record['request_sha256'],emitted['http_started']['request_sha256'])
        self.assertEqual(obj.wire,emitted['http_started']['wire_request'])
        with self.assertRaises(ValueError): obj.before(self.request(obj.wire))
        for mutated in ('temperature','origin','method','route'):
            obj=self.observer();body=copy.deepcopy(obj.wire)
            if mutated=='temperature': body['temperature']=0
            request=self.request(body)
            if mutated=='origin': request=httpx.Request('POST','https://other.invalid/v1/chat/completions',json=body)
            if mutated=='method': request=httpx.Request('GET','https://fixture.invalid/v1/chat/completions',json=body)
            if mutated=='route': request=httpx.Request('POST','https://fixture.invalid/v1/embeddings',json=body)
            with self.assertRaises(ValueError): obj.before(request)
            self.assertEqual([],obj.records)

    def test_native_usage_is_never_synthesized_from_service_defaults(self):
        for usage in (None,{}, {'prompt_tokens':True,'completion_tokens':-1}, {'prompt_tokens':7,'completion_tokens':3}):
            data={'model':'fixture-model','choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
            if usage is not None:data['usage']=usage
            record={};RequestObserver.after(record,httpx.Response(200,json=data))
            if usage=={'prompt_tokens':7,'completion_tokens':3}:
                self.assertEqual(usage,record['native_usage'])
            elif usage is None:
                self.assertNotIn('native_usage',record)
            else:
                self.assertEqual({},record['native_usage'])

    def test_allowance_gate_duplicate_key_and_unknown_reservation(self):
        auth={'status':'approved','source':'human_user_message','message_reference':'fixture-only',
              'max_diagnosis_http_requests':2,'scope':str(self.home.resolve())}
        with patch.object(runner,'HERE',self.home):
            x=copy.deepcopy(auth);x['source']='inferred'
            with self.assertRaises(ValueError):runner.allocate(x,['a'],self.home/'a')
            runner.allocate(auth,['a'],self.home/'a')
            with self.assertRaises(ValueError):runner.allocate(auth,['a'],self.home/'retry')
            with self.assertRaises(ValueError):runner.allocate(auth,['b','c'],self.home/'over')
            runner.allocate(auth,['b'],self.home/'b')
            with self.assertRaises(ValueError):runner.allocate(auth,['c'],self.home/'over2')
        records=[json.loads(line) for line in (self.home/'paid-allocations.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(2,sum(r['reserved_requests'] for r in records))

    def test_diagnosis_and_embeddings_share_cumulative_ledger(self):
        auth={'status':'approved','source':'human_user_message','message_reference':'fixture-only',
              'max_diagnosis_http_requests':2,'max_embedding_http_requests':1,'scope':str(self.home.resolve())}
        resume_allowance.allocate(self.home,auth,['d1'],self.home/'d1')
        resume_allowance.allocate(self.home,auth,['e1'],self.home/'e1',kind='embedding')
        resume_allowance.allocate(self.home,auth,['d2'],self.home/'d2')
        for key,kind in (('e2','embedding'),('d3','diagnosis'),('e1','diagnosis')):
            with self.assertRaises(ValueError):resume_allowance.allocate(self.home,auth,[key],self.home/key,kind=kind)
        records=[json.loads(line) for line in (self.home/'paid-allocations.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(['diagnosis','embedding','diagnosis'],[r['request_kind'] for r in records])

    def test_unapproved_embedding_invalid_keys_and_lock_do_not_reserve(self):
        auth={'status':'approved','source':'human_user_message','message_reference':'fixture-only',
              'max_diagnosis_http_requests':2,'scope':str(self.home.resolve())}
        with self.assertRaises(ValueError):resume_allowance.allocate(self.home,auth,['e1'],self.home/'e1',kind='embedding')
        for keys in ([],['a','a'],[''],[True]):
            with self.assertRaises(ValueError):resume_allowance.allocate(self.home,auth,keys,self.home/'invalid')
        with resume_allowance.ledger_lock(self.home/'paid-allocations.lock'):
            with self.assertRaises(OSError):resume_allowance.allocate(self.home,auth,['a'],self.home/'a')
        self.assertFalse((self.home/'paid-allocations.jsonl').exists())

    def fixture(self):
        # 只构造协议样本，所有候选一律false；结果不能称为模型实测。
        preflight=self.home/'preflight';preflight.mkdir()
        raw={'mode':'preflight','complete':True,'requests':[],'source_sha256':runner.source_hashes(),'model_snapshot':self.snapshot}
        runner.write(preflight/'observations-raw.json',raw)
        runner.write(preflight/'execution.json',{'evaluation_sha256':runner.eval_hashes()})
        plan_dir=self.home/'plan'
        with patch.object(runner,'HERE',self.home):runner.prepare(preflight,plan_dir)
        plan=runner.load(plan_dir/'plan.json')
        folder=self.home/'run';folder.mkdir();runner.archive_sources(folder)
        tasks=plan['tasks'][:24]
        payload=runner.payload('smoke',[{k:t[k] for k in ('question_id','variant')} for t in tasks],self.snapshot)
        runner.write(folder/'execution-input.json',payload)
        lookup={q['id']:q for q in self.questions}
        rows,requests,events=[],[],[]
        for i,t in enumerate(tasks):
            q=lookup[t['question_id']]
            content=json.dumps({'requirements':['仅用于协议fixture'], 'candidates':[
                {'id':s['id'],'checks':[{'covered':False,'quote':None,'reason':'隔离fixture，不是模型医学判断'}]} for s in q['candidates']]},ensure_ascii=False)
            parsed=parse_assessment(content,[{'id':s['id'],'excerpt':s['quote']} for s in q['candidates']])
            wire=plan['task_wire_requests'][t['request_key']]
            request={'task':{k:t[k] for k in ('question_id','variant')},'wire_request':wire,
                     'request_sha256':runner.sha(json.dumps(wire,sort_keys=True,ensure_ascii=False).encode()),
                     'status_code':200,'native_usage':{'prompt_tokens':100,'completion_tokens':10},
                     'raw_content':content,'finish_reason':'stop','response_model':'fixture-model'}
            row={**{k:t[k] for k in ('question_id','variant','request_key')},'raw_output':content,'parsed':parsed,
                 'ranked_ids':rank_assessed(parsed),'status':'success','error_type':None,
                 'native_usage':request['native_usage'],'http_attempts':1,'elapsed_ms':10.0}
            rows.append(row);requests.append(request)
            events.extend([{'http_started':{k:request[k] for k in ('task','wire_request','request_sha256')},'sequence':i+1},
                           {'http_finished':request,'sequence':i+1},{'checkpoint':row,'requests':[request]}])
        raw={'protocol':payload['protocol'],'mode':'smoke','input_sha256':self.fingerprint,'model_snapshot':self.snapshot,
             'source_sha256':runner.source_hashes(),'complete':True,'rows':rows,'requests':requests,'requested_tasks':24,
             'read_only':True,'rolled_back':True,'read_gold':False,'settings_unchanged':True,
             'settings_before':{},'settings_after':{},'vector_retrieval_executed':False,
             'external_search_executed':False,'forbidden_network_attempts':0}
        runner.write(folder/'observations-raw.json',raw)
        runner.write(folder/'execution.json',{'docker_exit_code':0,'timed_out':False,'read_gold_in_executor':False,
                     'input_sha256':runner.sha((folder/'execution-input.json').read_bytes()),
                     'source_sha256':runner.source_hashes(),'evaluation_sha256':runner.eval_hashes()})
        runner.write(folder/'plan-reference.json',{'path':str(plan_dir.resolve()),'sha256':runner.sha((plan_dir/'plan.json').read_bytes())})
        events.append({'final':raw})
        (folder/'wire-checkpoints.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
        return folder,plan_dir

    def test_independent_verifier_reparses_fixture_and_uses_six_group_scope(self):
        folder,plan=self.fixture()
        with patch.object(verifier,'HERE',self.home):result=verifier.verify_run(folder,plan,'smoke')
        self.assertEqual(24,result['http_requests'])
        self.assertIsNone(result['retrieval'])
        for metric in result['variants'].values():
            self.assertEqual(6,metric['groups'])
            self.assertEqual('explicit_smoke_subset',metric['evaluation_scope'])
            self.assertEqual(600,metric['usage']['input_tokens'])
            self.assertIsNone(metric['retrieval'])
        with patch.object(verifier,'HERE',self.home):
            with self.assertRaises(ValueError):verifier.verify_run(folder,plan,'development')

    def test_verifier_tampering_is_rejected_by_real_cli_nonzero(self):
        folder,plan=self.fixture()
        originals={name:(folder/name).read_bytes() for name in ('observations-raw.json','execution-input.json','wire-checkpoints.jsonl','resume_eval_score.py')}
        mutations={}
        raw=runner.load(folder/'observations-raw.json')
        for name in ('missing_result','wrong_usage','raw_response','duplicate_task','request_body','different_response_model'):
            x=copy.deepcopy(raw)
            if name=='missing_result':x['rows'].pop()
            elif name=='wrong_usage':x['rows'][0]['native_usage']['prompt_tokens']+=1
            elif name=='raw_response':x['rows'][0]['raw_output']='{}'
            elif name=='duplicate_task':x['rows'][1]['variant']=x['rows'][0]['variant']
            elif name=='request_body':x['requests'][0]['wire_request']['temperature']=0
            else:x['requests'][0]['response_model']='other-model'
            mutations[name]=('observations-raw.json',json.dumps(x,ensure_ascii=False).encode())
        x=runner.load(folder/'execution-input.json');x['gold']={}
        mutations['payload_gold']=('execution-input.json',json.dumps(x).encode())
        mutations['missing_http_started']=('wire-checkpoints.jsonl','\n'.join(originals['wire-checkpoints.jsonl'].decode().splitlines()[1:]).encode())
        mutations['changed_scorer']=('resume_eval_score.py',originals['resume_eval_score.py']+b'\n# changed\n')
        code='import sys;from pathlib import Path;import resume_experiment_verify as v;v.HERE=Path(sys.argv[1]);v.verify_run(Path(sys.argv[2]),Path(sys.argv[3]),"smoke")'
        for name,(target,data) in mutations.items():
            for file,original in originals.items():(folder/file).write_bytes(original)
            (folder/target).write_bytes(data)
            if target=='observations-raw.json':
                # 同步fixture日志，保证失败来自语义门禁而非仅日志文件不一致。
                x=json.loads(data);events=[]
                for i,(row,request) in enumerate(zip(x['rows'],x['requests'])):
                    events.extend([{'http_started':{k:request[k] for k in ('task','wire_request','request_sha256')},'sequence':i+1},
                                   {'http_finished':request,'sequence':i+1},{'checkpoint':row,'requests':[request]}])
                events.append({'final':x})
                (folder/'wire-checkpoints.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
            cli=subprocess.run([sys.executable,'-B','-X','utf8','-c',code,str(self.home),str(folder),str(plan)],
                cwd=Path(__file__).parent,capture_output=True,text=True,encoding='utf-8')
            self.assertNotEqual(0,cli.returncode,name)
            self.assertIn('ValueError',cli.stderr,name)
            CLI_FAILURES.append({'case':name,'exit_code':cli.returncode})


if __name__=='__main__':
    run=unittest.main(verbosity=2,exit=False)
    print(json.dumps({'fixture_only':True,'model_http_requests':0,'failure_injection_exits':CLI_FAILURES}))
    sys.exit(0 if run.result.wasSuccessful() else 1)
