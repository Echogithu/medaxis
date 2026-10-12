"""独立复算归档的原文坐标、三组量尺和回退题；拒绝缺题或错误出处。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'evals/semantic-recall'))
from score_v2 import score,summarize


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(output):
    result=read(output/'results.json')
    frozen=ROOT/'.ai/tasks/2026-10-07-rag-baseline/frozen-v1'
    baseline=ROOT/'.ai/tasks/2026-10-08-semantic-recall/union-final-v2/results.json'
    dataset,corpus,previous=read(frozen/'dataset.json'),read(frozen/'corpus.json'),read(baseline)
    for key,path in (('dataset_sha256',frozen/'dataset.json'),('corpus_sha256',frozen/'corpus.json'),('baseline_sha256',baseline)):
        if result[key]!=digest(path):raise ValueError('输入指纹不同')
    for path,sha in result['code_sha256'].items():
        filename=Path(path).name
        archived=output/filename if filename in {'rag_context.py','knowledge_citations.py','replay.py'} else ROOT/path
        if digest(archived)!=sha:raise ValueError('执行源码指纹不同')
    # v2所依赖的严格评分器也必须保持阶段3原样。
    if digest(ROOT/'evals/rag-baseline/score.py')!=digest(baseline.parent/'executor/score.py'):
        raise ValueError('严格评分器改变')
    if result['online_or_postgres_execution'] or result['network_attempts'] or result['extra_model_calls']:
        raise ValueError('运行模式不符')
    cases=[c for c in dataset['cases'] if not result['split'] or c['split']==result['split']]
    ids=[c['id'] for c in cases]
    if result['prefix_parity_ids']!=ids:raise ValueError('基线复现题目不同')
    old={r['id']:r for r in previous['cases']}
    docs={d['id']:d for d in corpus['documents']}
    chunks={c['id']:c for c in corpus['chunks']}
    units={u['id']:u for u in dataset['gold_units']}
    if result['profiles']!={'prefix800':800,'prefix1600':1600,'context1600':1600}:
        raise ValueError('三组预算不同')
    for name,budget in result['profiles'].items():
        group=result['groups'][name];rows=group['cases']
        if [r['id'] for r in rows]!=ids:raise ValueError('结果缺题或重复')
        for case,row in zip(cases,rows):
            if row['status']!='success' or row['score']!=score(case,units,row['sources'],docs):
                raise ValueError('原文或逐题成绩不同')
            sources=row['sources']
            if len(sources)>previous['k'] or len({s['chunk_id'] for s in sources})!=len(sources):
                raise ValueError('来源数量或去重错误')
            for source in sources:
                cid=source['chunk_id'];anchor=chunks[cid]
                if cid not in old[row['id']]['internal_chunk_ids'] or source['document_id']!=anchor['document_id'] or len(source['excerpt'])>budget:
                    raise ValueError('召回锚点或预算错误')
                meta=(row.get('context_metadata') or {}).get(cid)
                if meta:
                    document=docs[anchor['document_id']]['content']
                    if meta['document_id']!=anchor['document_id'] or meta['anchor_chunk_id']!=cid or meta['start']!=source['start'] or meta['end']!=source['end'] or meta['source_text_sha256']!=hashlib.sha256(document.encode()).hexdigest():
                        raise ValueError('上下文元信息错误')
                    if anchor['content'].strip() not in source['excerpt'] or cid not in meta['chunk_ids']:
                        raise ValueError('命中锚点内容丢失')
                    participating=[chunks[x] for x in meta['chunk_ids']]
                    if len(set(meta['chunk_ids']))!=len(participating) or any(c['document_id']!=anchor['document_id'] or abs(c['chunk_index']-anchor['chunk_index'])>1 for c in participating):
                        raise ValueError('参与chunk超范围')
                    cursor=source['start']
                    for chunk in sorted(participating,key=lambda c:c['start']):
                        if chunk['start']>cursor:break
                        cursor=max(cursor,chunk['end'])
                    if cursor<source['end'] or meta['max_chars']!=budget or meta['method']!='anchor_neighbors':
                        raise ValueError('参与chunk未连续覆盖上下文或方法/预算错误')
                elif not anchor['start']<=source['start']<source['end']<=anchor['end']:
                    raise ValueError('未扩展来源超出锚点')
            if name=='prefix800' and (sources!=old[row['id']]['sources'] or row['score']!=old[row['id']]['score']):
                raise ValueError('阶段3基线复现不一致')
        if group['summary']!=summarize(cases,rows) or group['source_chars']!=sum(len(s['excerpt']) for r in rows for s in r['sources']):
            raise ValueError('汇总或文本量错误')
    for label,before,after in [('budget_effect','prefix800','prefix1600'),('context_effect','prefix1600','context1600'),('overall_effect','prefix800','context1600')]:
        prior={r['id']:r['score'] for r in result['groups'][before]['cases']}
        actual={k:[] for k in ('improved_ids','regressed_ids','ranking_regressed_ids','new_no_answer_candidates')}
        for row in result['groups'][after]['cases']:
            a,b,cid=prior[row['id']],row['score'],row['id']
            if b['complete_evidence'] is None:
                if b['unsupported_candidate_returned'] and not a['unsupported_candidate_returned']:actual['new_no_answer_candidates'].append(cid)
                continue
            if b['evidence_recall_at_k']>a['evidence_recall_at_k']:actual['improved_ids'].append(cid)
            if b['evidence_recall_at_k']<a['evidence_recall_at_k'] or (b['qualifier_recall'] or 0)<(a['qualifier_recall'] or 0):actual['regressed_ids'].append(cid)
            if b['mrr']<a['mrr']:actual['ranking_regressed_ids'].append(cid)
        if actual!=result[label]:raise ValueError('增益或回退记录错误')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    result=verify(parser.parse_args().output)
    print(f"PASS: {len(result['prefix_parity_ids'])}题，三组原文/锚点/预算/评分/回退逐项复核；上线结论另看门禁")
