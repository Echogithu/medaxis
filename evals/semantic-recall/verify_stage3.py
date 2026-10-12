"""只读复算第三阶段归档及反例；不访问Docker、不调用模型、不修改历史。"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from run import verify,changes,cached_timing,ROOT
from build import read,digest


def check(task,baseline):
    before=verify(task/'before-v2',baseline)
    after=verify(task/'union-final-v2',baseline)
    rrf=verify(task/'after-final',baseline)
    report=read(task/'comparison-current-final-v2'/'comparison.json')
    for key in ('dataset_sha256','corpus_sha256','query_embeddings_sha256','scorer_sha256','scoring_profile','k'):
        if before[key]!=after[key]:raise ValueError('最终对照输入不一致')
    if before['executor_sha256']['score.py']!=after['executor_sha256']['score.py']:raise ValueError('严格评分依赖不一致')
    gain,loss,rank_loss,negative_gain=changes(before,after)
    expected={'improved_ids':gain,'regressed_ids':loss,'ranking_regressed_ids':rank_loss,
              'no_answer_candidate_improved_ids':negative_gain,'before':before['summary'],'after':after['summary'],
              'groups_before':before['groups'],'groups_after':after['groups'],
              'cached_timing_before':cached_timing(before),'cached_timing_after':cached_timing(after),
              'before_rag_sha256':before['executed_rag_sha256'],'after_rag_sha256':after['executed_rag_sha256'],
              'dataset_sha256':before['dataset_sha256'],'scorer_sha256':before['scorer_sha256'],
              'evaluation_is_blind':False,'clinical_effectiveness':None}
    verdict='regressed' if loss else 'coverage_gain_with_ranking_tradeoff' if gain and rank_loss else 'improved' if gain else 'no_quality_gain'
    expected['verdict']=verdict
    if report!=expected:raise ValueError('对照报告不符合逐题复算')
    if after['summary']['total']!=45 or not after['online_baseline_complete']:raise ValueError('最终题集不完整')
    if digest(ROOT/'backend/app/services/rag.py')!=after['executed_rag_sha256']:raise ValueError('当前工作区RAG与最终归档不一致')
    old=read(baseline/'postgres-full-v1/results.json')
    old_rows={r['id']:r for r in old['cases']}
    calibration=[]
    for row in before['cases']:
        prior=old_rows[row['id']]
        if row['sources']!=prior['sources']:raise ValueError('量尺校准时检索结果改变')
        if row['score']!=prior['score']:calibration.append(row['id'])
    if calibration!=['R19']:raise ValueError('评分校准改变了其他题目')
    runtime=read(task/'runtime-final.json');disabled=read(task/'demo-disabled.json')
    if (runtime['settings']['enabled']!='false' or runtime['health_http_status']!=200
        or any(runtime['settings'][key]!=disabled['before']['interview_demo.'+key] for key in ('limit','used'))
        or not disabled['kept_disabled_by_user_request'] or runtime['provider_calls']!=0):raise ValueError('记录的保护状态、额度或健康不符合要求')

    # 改成绩/输入/模式而不改变代码时，校验仍必须拒绝；不是自报通过。
    guards=[]
    mutations={
        'dataset_fingerprint':lambda r:r.update(dataset_sha256='0'*64),
        'rag_fingerprint':lambda r:r.update(executed_rag_sha256='0'*64),
        'missing_case':lambda r:r['cases'].pop(),
        'failed_case':lambda r:r['cases'][0].update(status='failed'),
        'changed_split':lambda r:r['cases'][0].update(split='evaluation' if r['cases'][0]['split']=='development' else 'development'),
        'changed_group_score':lambda r:r['groups']['split']['development'].update(hit_at_k=-1),
        'changed_quote':lambda r:r['cases'][0]['sources'][0].update(excerpt='fabricated quote'),
        'transaction_not_rolled_back':lambda r:r.update(rolled_back=False),
        'extra_network':lambda r:r.update(additional_network_attempts=1),
    }
    with tempfile.TemporaryDirectory(prefix='medaxis-stage3-') as folder:
        probe=Path(folder)/'probe';shutil.copytree(task/'union-final-v2',probe)
        for name,mutate in mutations.items():
            changed=copy.deepcopy(after);mutate(changed)
            (probe/'results.json').write_text(json.dumps(changed,ensure_ascii=False),encoding='utf-8')
            try:verify(probe,baseline)
            except (ValueError,KeyError):guards.append(name)
            else:raise ValueError('反例未被拒绝：'+name)
    return {'status':'verified_stage3','database_cases':45,'read_only':True,'extra_model_network':0,
            'calibration_only_ids':calibration,'improved_ids':gain,'regressed_ids':loss,
            'ranking_regressed_ids':rank_loss,'no_answer_candidate_improved_ids':negative_gain,
            'complete_evidence_before':before['summary']['complete_evidence_rate'],
            'complete_evidence_after':after['summary']['complete_evidence_rate'],
            'rrf_complete_evidence':rrf['summary']['complete_evidence_rate'],'negative_guards':guards,
            'current_rag_matches_archived':True,'online_api_loaded':None,'clinical_effectiveness':None}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',type=Path,required=True);parser.add_argument('--baseline',type=Path,required=True)
    args=parser.parse_args()
    try:print(json.dumps(check(args.task,args.baseline),ensure_ascii=False));return 0
    except (ValueError,KeyError,OSError) as exc:print(f'校验拒绝：{exc}',file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
