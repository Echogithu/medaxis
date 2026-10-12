"""独立复核真实入口归档的输入、源码、原文范围、锚点向量、评分与保存字段。"""
import argparse
import hashlib
import math
from pathlib import Path
from replay import ROOT,read,digest
import sys
sys.path.insert(0,str(ROOT/'evals/semantic-recall'))
from score_v2 import score,summarize


def verify(output):
    result=read(output/'results.json');frozen=ROOT/'.ai/tasks/2026-10-07-rag-baseline/frozen-v1'
    dataset,corpus=read(frozen/'dataset.json'),read(frozen/'corpus.json')
    original=read(ROOT/'.ai/tasks/2026-10-08-semantic-recall/union-final-v2/results.json')
    artifact=read(frozen.parent/'query-embeddings.json');vectors=dict(zip(artifact['queries'],artifact['vectors']))
    for key,path in [('dataset_sha256',frozen/'dataset.json'),('corpus_sha256',frozen/'corpus.json'),('query_embeddings_sha256',frozen.parent/'query-embeddings.json')]:
        if result[key]!=digest(path):raise ValueError('输入指纹错误')
    if result['network_attempts'] or result['extra_model_calls'] or not result['read_only'] or not result['rolled_back'] or result['external_search_included']:
        raise ValueError('评测运行范围错误')
    if read(output/'execution.json')['exit_code']!=0:raise ValueError('实际执行失败')
    for filename,sha in result['executor_sha256'].items():
        if Path(filename).name!=filename or digest(output/'executor'/filename)!=sha:raise ValueError('执行器归档损坏')
    for filename in ('rag.py','rag_context.py','knowledge_citations.py','medical.py'):
        key=('app/tools/' if filename=='medical.py' else 'app/services/')+filename
        if digest(output/'executor'/('current_'+filename))!=result['source_sha256'][key]:raise ValueError('实际源码归档损坏')
    cases_by_id={c['id']:c for c in dataset['cases']}
    ids=result['requested_ids']
    if len(ids)!=len(set(ids)) or any(cid not in cases_by_id for cid in ids):raise ValueError('题目集合错误')
    cases=[c for c in dataset['cases'] if c['id'] in ids]
    if set(result['groups'])!={'before','after'}:raise ValueError('对照组缺失或多余')
    docs={d['id']:d for d in corpus['documents']};chunks={c['id']:c for c in corpus['chunks']};units={u['id']:u for u in dataset['gold_units']}
    old={r['id']:r for r in original['cases']}
    for profile,group in result['groups'].items():
        rows=group['cases']
        if [r['id'] for r in rows]!=[c['id'] for c in cases]:raise ValueError('结果缺题或重复')
        for case,row in zip(cases,rows):
            if row['status']!='success' or row['score']!=score(case,units,row['sources'],docs):raise ValueError('原文/量尺成绩错误')
            if len(row['sources'])>original['k'] or len({s['chunk_id'] for s in row['sources']})!=len(row['sources']):raise ValueError('来源超额或重复')
            saved=row['serialized_sources']
            if len(saved)!=len(row['sources']):raise ValueError('保存来源数量不符')
            for source,item in zip(row['sources'],saved):
                cid=source['chunk_id'];anchor=chunks[cid];doc=docs[anchor['document_id']]
                if cid not in old[row['id']]['internal_chunk_ids'] or source['document_id']!=anchor['document_id'] or item['document_id']!=anchor['document_id'] or item['source_type']!='internal' or item['chunk_id']!=cid or item['excerpt']!=source['excerpt']:
                    raise ValueError('锚点或保存摘录不同')
                meta=source.get('context_metadata')
                if meta:
                    if item.get('context_metadata')!=meta or meta['start']!=source['start'] or meta['end']!=source['end'] or meta['document_id']!=anchor['document_id'] or meta['anchor_chunk_id']!=cid or meta['source_text_sha256']!=doc['text_sha256']:
                        raise ValueError('定位保存元信息错误')
                    if meta['method']!='anchor_neighbors' or not 1<=len(meta['chunk_ids'])<=3 or len(source['excerpt'])>1600 or anchor['content'].strip() not in source['excerpt'] or cid not in meta['chunk_ids']:
                        raise ValueError('完整锚点或预算错误')
                    participating=[chunks[x] for x in meta['chunk_ids']]
                    if len(set(meta['chunk_ids']))!=len(participating) or any(c['document_id']!=anchor['document_id'] or abs(c['chunk_index']-anchor['chunk_index'])>1 for c in participating):raise ValueError('跨文档或参与chunk错误')
                    cursor=source['start']
                    for c in sorted(participating,key=lambda c:c['start']):
                        if c['start']>cursor:break
                        cursor=max(cursor,c['end'])
                    if cursor<source['end']:raise ValueError('原文定位有缺口')
                elif not anchor['start']<=source['start']<source['end']<=anchor['end']:raise ValueError('无元信息却跨越锚点')
                if profile=='after':
                    q=vectors[case['query']];e=anchor['embedding_json']
                    cos=sum(x*y for x,y in zip(q,e))/math.sqrt(sum(x*x for x in q)*sum(x*x for x in e))
                    if not math.isclose(item['retrieval_score'],cos,rel_tol=1e-10) or item['retrieval_model']!=artifact['calls'][0]['model'] or item['retrieval_dimension']!=len(q) or item['retrieval_anchor_excerpt']!=anchor['content'].strip()[:800] or item['retrieval_method']!='embedding_cosine' or item['retrieval_query_fingerprint']!=hashlib.sha256(case['query'].strip()[:512].encode()).hexdigest():raise ValueError('锚点语义分或原始摘录被篡改')
            if profile=='before' and (row['sources']!=old[row['id']]['sources'] or row['score']!=old[row['id']]['score']):raise ValueError('旧路径未重现')
        if group['summary']!=summarize(cases,rows) or group['source_chars']!=sum(len(s['excerpt']) for r in rows for s in r['sources']):raise ValueError('汇总错误')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    result=verify(p.parse_args().output)
    print(f"PASS: {len(result['requested_ids'])}题实际工具前后归档，源码/原文/向量/评分/元信息独立复核")
