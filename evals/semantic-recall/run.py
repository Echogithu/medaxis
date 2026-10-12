"""固定原文/题库/真实向量/量尺，在实际PostgreSQL对照指定RAG源码；禁止额外网络。"""
import argparse
import base64
from datetime import datetime,timezone
import json
from pathlib import Path
import math
import statistics
import shutil
import subprocess
import sys
from score_v2 import score,summarize
from build import read,digest,validate

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'evals/rag-baseline'


def run(args):
    previous=args.baseline.resolve();frozen=previous/'frozen-v1'
    corpus=read(frozen/'corpus.json');dataset=read(frozen/'dataset.json');validate(corpus,dataset)
    if dataset['snapshot_sha256']!=digest(frozen/'corpus.json'):raise ValueError('题库快照改变')
    ids=[c['id'] for c in dataset['cases'] if not args.split or c['split']==args.split]
    if args.ids:ids=args.ids.split(',')
    if not ids or len(ids)!=len(set(ids)) or not set(ids)<={c['id'] for c in dataset['cases']}:raise ValueError('指定题目为空、重复或不存在')
    if args.ids and args.split:raise ValueError('不能同时指定题目ID与分组')
    current_sha={}
    for name,old_sha in corpus['source_sha256'].items():
        current_sha[name]=digest(ROOT/'backend'/name)
        if name!='app/services/rag.py' and current_sha[name]!=old_sha:raise ValueError('非实验模块源码改变，不能归因')
    args.output.mkdir(parents=True,exist_ok=False)
    archive=args.output/'executor';archive.mkdir()
    for name in ('build.py','score.py','collect.py','postgres.py'):shutil.copyfile(BASE/name,archive/name)
    for name in ('score_v2.py','run.py'):shutil.copyfile(Path(__file__).with_name(name),archive/name)
    shutil.copyfile(args.rag_source,archive/'rag.py')
    program=(archive/'postgres.py').read_text(encoding='utf-8')
    old='async def cached_embed(_self,texts):return [vectors[q] for q in texts]'
    new="async def cached_embed(_self,texts):\n        _self._model=artifact['calls'][0]['model']\n        return [vectors[q] for q in texts]"
    if old not in program:raise ValueError('评测适配点改变')
    program=program.replace(old,new).replace('from score import score,summarize','from score_v2 import score,summarize')
    program=program.replace('    async def execute(self,statement):','    async def stream(self,statement):\n        return await self.session.stream(statement)\n    async def execute(self,statement):')
    (archive/'postgres-runtime.py').write_text(program,encoding='utf-8')
    execution_corpus={**corpus,'source_sha256':current_sha,'demo_enabled':False}
    payload={'corpus':execution_corpus,'dataset':dataset,'embeddings':read(previous/'query-embeddings.json'),'ids':ids}
    code='import asyncio,base64,json,sys,types,app.services\n'
    for name,filename in (('build','build.py'),('score','score.py'),('score_v2','score_v2.py'),('collect','collect.py'),('app.services.rag','rag.py'),('postgres','postgres-runtime.py')):
        encoded=base64.b64encode((archive/filename).read_bytes()).decode()
        code+=f'module=types.ModuleType({name!r});module.__file__={"/tmp/medaxis-eval/"+filename!r};sys.modules[{name!r}]=module\n'
        if name=='app.services.rag':code+='app.services.rag=module\n'
        code+=f'exec(base64.b64decode({encoded!r}),module.__dict__)\n'
    encoded=base64.b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode()
    code+=f'payload=json.loads(base64.b64decode({encoded!r}))\nsys.exit(asyncio.run(sys.modules["postgres"].main(payload)))\n'
    actual=subprocess.run(['docker','exec','-i','-w','/app','medaxis-backend','python','-'],input=code,capture_output=True,text=True,encoding='utf-8')
    (args.output/'execution.json').write_text(json.dumps({'exit_code':actual.returncode,'stderr':actual.stderr},ensure_ascii=False,indent=2),encoding='utf-8')
    if actual.returncode!=0:
        (args.output/'failed.json').write_text(actual.stdout,encoding='utf-8');raise ValueError('实际只读入口失败，见execution.json/failed.json')
    result=json.loads(actual.stdout)
    result.update(mode='postgres_same_inputs_retrieval_experiment',label=args.label,scoring_profile='non_whitespace_coverage_v2',
        dataset_sha256=digest(frozen/'dataset.json'),corpus_sha256=digest(frozen/'corpus.json'),
        query_embeddings_sha256=digest(previous/'query-embeddings.json'),executed_rag_sha256=digest(archive/'rag.py'),
        scorer_sha256=digest(archive/'score_v2.py'),executor_sha256={p.name:digest(p) for p in archive.iterdir()},
        recorded_at=datetime.now(timezone.utc).isoformat(),baseline_path=str(previous),
        requested_ids=ids,sample_selector={'split':args.split,'ids':args.ids})
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'label':args.label,**result['summary']},ensure_ascii=False))
    return 0 if result['summary']['status']=='complete_diagnostic' else 1


def verify(output,previous):
    r=read(output/'results.json');frozen=previous/'frozen-v1';dataset=read(frozen/'dataset.json');corpus=read(frozen/'corpus.json')
    for key,path in (('dataset_sha256',frozen/'dataset.json'),('corpus_sha256',frozen/'corpus.json'),('query_embeddings_sha256',previous/'query-embeddings.json')):
        if r[key]!=digest(path):raise ValueError('输入指纹不符')
    required={'build.py','score.py','collect.py','postgres.py','score_v2.py','run.py','rag.py','postgres-runtime.py'}
    if set(r['executor_sha256'])!=required:raise ValueError('执行器归档缺失或多余')
    for name,sha in r['executor_sha256'].items():
        if Path(name).name!=name:raise ValueError('执行器路径无效')
        if digest(output/'executor'/name)!=sha:raise ValueError('执行器指纹不符')
    if r['executed_rag_sha256']!=r['executor_sha256']['rag.py'] or r['scorer_sha256']!=r['executor_sha256']['score_v2.py']:raise ValueError('源码或量尺指纹不符')
    if r['executor_sha256']['score.py']!=digest(BASE/'score.py'):raise ValueError('严格评分依赖已改变')
    if set(r['source_sha256'])!=set(corpus['source_sha256']) or any(
        sha!=corpus['source_sha256'][name] for name,sha in r['source_sha256'].items() if name!='app/services/rag.py'):
        raise ValueError('非实验模块源码指纹改变')
    if (r['scorer_sha256']!=digest(Path(__file__).with_name('score_v2.py'))
        or r['additional_network_attempts']!=0 or r['read_only'] is not True or r['rolled_back'] is not True
        or read(output/'execution.json')['exit_code']!=0):raise ValueError('量尺或运行模式不符')
    validate(corpus,dataset)
    by_id={c['id']:c for c in dataset['cases']};units={u['id']:u for u in dataset['gold_units']};docs={d['id']:d for d in corpus['documents']}
    chunks={c['id']:c for c in corpus['chunks']}
    rows=r['cases'];cases=[by_id[x['id']] for x in rows]
    observed=[row['id'] for row in rows]
    if 'requested_ids' in r and (len(set(r['requested_ids']))!=len(r['requested_ids']) or set(observed)!=set(r['requested_ids'])):raise ValueError('指定题目与结果不符')
    if r['online_baseline_complete']!=(len(rows)==len(dataset['cases']) and all(row['status']=='success' for row in rows)):raise ValueError('完整运行标记不符')
    if r['k']!=corpus['policy']['report_limit']:raise ValueError('来源预算改变')
    for row in rows:
        case=by_id[row['id']]
        if row.get('family')!=case['family'] or row.get('split')!=case['split']:raise ValueError('题目分组改变')
        if row['status']!='success' or row['score']!=score(case,units,row['sources'],docs):raise ValueError('逐题成绩不符或执行失败')
        if len(row['sources'])>r['k'] or len({s['chunk_id'] for s in row['sources']})!=len(row['sources']):raise ValueError('返回来源超额或重复')
        for source in row['sources']:
            chunk=chunks[source['chunk_id']]
            if source['document_id']!=chunk['document_id'] or not chunk['start']<=source['start']<source['end']<=chunk['end']:raise ValueError('来源不在对应片段范围')
        for stage,field in (('coarse','coarse_chunk_ids'),('internal','internal_chunk_ids')):
            original=[{'document_id':chunks[cid]['document_id'],'start':chunks[cid]['start'],
                       'end':chunks[cid]['end'],'excerpt':chunks[cid]['content']} for cid in row[field]]
            if row['stage_scores'][stage]!=score(case,units,original,docs):raise ValueError('阶段成绩不符')
    if r['summary']!=summarize(cases,rows):raise ValueError('汇总不符')
    groups={field:{value:summarize([c for c in cases if c[field]==value],
            [row for row in rows if by_id[row['id']][field]==value]) for value in sorted({c[field] for c in cases})}
            for field in ('split','family')}
    if r['groups']!=groups:raise ValueError('分组汇总不符')
    return r


def changes(before,after):
    """覆盖、限定词和无答案候选是底线，排名下降单独列出。"""
    a={r['id']:r for r in before['cases']};b={r['id']:r for r in after['cases']}
    if set(a)!=set(b):raise ValueError('前后题目不同')
    improvements=[];regressions=[];ranking_regressions=[];negative_improvements=[]
    for cid in a:
        old,new=a[cid]['score'],b[cid]['score']
        if old['complete_evidence'] is not None:
            if new['mrr']<old['mrr']:ranking_regressions.append(cid)
            if new['evidence_recall_at_k']>old['evidence_recall_at_k']:improvements.append(cid)
            if new['evidence_recall_at_k']<old['evidence_recall_at_k'] or (new['qualifier_recall'] or 0)<(old['qualifier_recall'] or 0):regressions.append(cid)
        elif new['unsupported_candidate_returned'] and not old['unsupported_candidate_returned']:regressions.append(cid)
        elif old['unsupported_candidate_returned'] and not new['unsupported_candidate_returned']:negative_improvements.append(cid)
    return improvements,regressions,ranking_regressions,negative_improvements


def cached_timing(result):
    values=sorted(row['retrieval_with_cached_query_vector_ms'] for row in result['cases'])
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):raise ValueError('计时数值无效')
    return {'n':len(values),'p50_ms':statistics.median(values),'p95_ms':values[math.ceil(.95*len(values))-1],
            'scope':'缓存查询向量检索，单次顺序运行，不是生产端到端耗时','p95_method':'nearest_rank'}


def compare(args):
    before=verify(args.before,args.baseline);after=verify(args.after,args.baseline)
    for key in ('dataset_sha256','corpus_sha256','query_embeddings_sha256','scorer_sha256','scoring_profile','k'):
        if before[key]!=after[key]:raise ValueError('前后输入/量尺不可比较')
    if before['executor_sha256']['score.py']!=after['executor_sha256']['score.py']:raise ValueError('严格评分依赖不可比较')
    improvements,regressions,ranking_regressions,negative_improvements=changes(before,after)
    same_code=before['executed_rag_sha256']==after['executed_rag_sha256']
    verdict='regressed' if regressions else 'coverage_gain_with_ranking_tradeoff' if improvements and ranking_regressions and not same_code else 'improved' if improvements and not same_code else 'no_quality_gain'
    result={'verdict':verdict,'improved_ids':improvements,'regressed_ids':regressions,'ranking_regressed_ids':ranking_regressions,
            'no_answer_candidate_improved_ids':negative_improvements,'before':before['summary'],'after':after['summary'],
            'groups_before':before['groups'],'groups_after':after['groups'],
            'cached_timing_before':cached_timing(before),'cached_timing_after':cached_timing(after),
            'evaluation_is_blind':False,
            'before_rag_sha256':before['executed_rag_sha256'],'after_rag_sha256':after['executed_rag_sha256'],
            'dataset_sha256':before['dataset_sha256'],'scorer_sha256':before['scorer_sha256'],'clinical_effectiveness':None}
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=['# 独立语义召回同题对照','',f'结论：{verdict}；专业gold未核对，不报临床有效。','',
          f"前后同一{before['summary']['total']}题/原文/真实查询向量/量尺v2/来源预算，仅RAG源码变化。评分校准单列，不算算法收益。",'',
          '验收集此前已公开成绩，本次是固定样本回归，不是盲测或泛化证明。','',
          '| 指标 | 改前 | 改后 |','|---|---|---|']
    for key in ('hit_at_k','evidence_recall_at_k','qualifier_recall','mrr','unsupported_candidate_rate'):
        rows.append(f"| {key} | {before['summary'][key]} | {after['summary'][key]} |")
    rows+=['','| 分组 | 正例数 | 完整覆盖改前 | 完整覆盖改后 |','|---|---|---|---|']
    for field in ('split','family'):
        for name,old in before['groups'][field].items():
            new=after['groups'][field][name]
            rows.append(f"| {field}/{name} | {old['positive_cases']} | {old['complete_evidence_rate']} | {new['complete_evidence_rate']} |")
    rows+=['',f"完整证据改善：{', '.join(improvements) or '无'}",f"覆盖/限定词退步：{', '.join(regressions) or '无'}",f"首个证据排名退步：{', '.join(ranking_regressions) or '无'}",'',
           f"无答案候选减少题：{', '.join(negative_improvements) or '无'}",'',
           f"缓存向量检索P50：{cached_timing(before)['p50_ms']}→{cached_timing(after)['p50_ms']} ms；P95（nearest-rank）：{cached_timing(before)['p95_ms']}→{cached_timing(after)['p95_ms']} ms。",'',
           '无答案题的候选返回只代表检索层，不代表诊断报告误成功。流式JSON向量精确扫描复杂度O(N×D)，大语料须后续向量索引；单次小样本计时不是生产端到端耗时。']
    (args.output/'REPORT.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));return 0


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    run_p=sub.add_parser('run');run_p.add_argument('--rag-source',type=Path,required=True);run_p.add_argument('--label',required=True)
    run_p.add_argument('--ids');run_p.add_argument('--split',choices=['development','evaluation'])
    compare_p=sub.add_parser('compare');compare_p.add_argument('--before',type=Path,required=True);compare_p.add_argument('--after',type=Path,required=True)
    for parser in (run_p,compare_p):
        parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    try:return run(args) if args.command=='run' else compare(args)
    except (ValueError,KeyError,OSError) as exc:print(f'评测拒绝：{exc}',file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
