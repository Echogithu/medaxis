"""离线独立重算输入、真实原文/余弦值、引用链接、逐题成绩与汇总。"""
import argparse
import hashlib
import math
import sys
from pathlib import Path
from runner import ROOT,TASK,digest,read
sys.path.insert(0,str(ROOT/'evals/semantic-recall'))
from score_v2 import score,summarize


def verify(output,dataset_path,corpus_path,vectors_path,result=None):
    r=read(output/'results.json') if result is None else result
    dataset,corpus,vectors=map(read,(dataset_path,corpus_path,vectors_path))
    for key,path in [('dataset_sha256',dataset_path),('corpus_sha256',corpus_path),('embeddings_sha256',vectors_path)]:
        if r[key]!=digest(path):raise ValueError('输入指纹不同')
    if (read(output/'execution.json')['exit_code']!=0 or r['mode']!='actual_search_medical_knowledge_paired'
        or not r['read_only'] or not r['rolled_back'] or r['network_attempts']!=0 or r['extra_model_calls']!=0
        or r['external_search_included']):raise ValueError('执行范围或退出码错误')
    for name,sha in r['executor_sha256'].items():
        if Path(name).name!=name or digest(output/'executor'/name)!=sha:raise ValueError('执行器指纹不同')
    for name in ('rag.py','rag_context.py','knowledge_citations.py','medical.py'):
        key=('app/tools/' if name=='medical.py' else 'app/services/')+name
        if digest(output/'executor'/('current_'+name))!=r['source_sha256'][key]:raise ValueError('实际源码指纹不同')
    freeze=read(TASK/'policy-before-validation.json')
    frozen_hashes={key.replace('\\','/'):value for key,value in freeze['source_sha256'].items()}
    if r['source_sha256']['app/services/rag.py']!=frozen_hashes['backend/app/services/rag.py']:raise ValueError('验证后算法漂移')
    if digest(output/'executor/authority_old_rag.py')!=read(TASK/'source-before-sha256.json')['rag.py']:raise ValueError('旧算法指纹不同')
    cases=dataset['cases'];docs={d['id']:d for d in corpus['documents']};chunks={c['id']:c for c in corpus['chunks']}
    units={u['id']:u for u in dataset['gold_units']};query_vectors=dict(zip(vectors['queries'],vectors['vectors']))
    if vectors['queries']!=[c['query'] for c in cases] or len(vectors['vectors'])!=len(cases):raise ValueError('向量题目不齐')
    for u in units.values():
        doc=docs[u['document_id']]
        if doc['content'][u['start']:u['end']]!=u['quote'] or hashlib.sha256(doc['content'].encode()).hexdigest()!=u['document_sha256']:raise ValueError('gold原文错误')
    verified_urls={d['document_id']:d['new_source_url'] for d in read(TASK/'source-authority-manifest.json')['documents']}
    if any(doc['source_url']!=verified_urls[key] for key,doc in docs.items()):raise ValueError('快照来源链接不同')
    if set(r['groups'])!={'before','after'}:raise ValueError('对照组不齐')
    for group in r['groups'].values():
        rows=group['cases']
        if [row['id'] for row in rows]!=[case['id'] for case in cases]:raise ValueError('结果缺题/重复/乱序')
        for case,row in zip(cases,rows):
            if row['status']!='success' or row['score']!=score(case,units,row['sources'],docs):raise ValueError('逐题评分不同')
            if (len(row['sources'])>corpus['policy']['report_limit'] or len(row['sources'])!=len(row['serialized_sources'])
                or len({s['chunk_id'] for s in row['sources']})!=len(row['sources'])
                or not len(row['sources'])<=row['candidate_count']<=corpus['policy']['internal_candidates']):raise ValueError('来源数量或候选预算不同')
            for s,item in zip(row['sources'],row['serialized_sources']):
                anchor=chunks[s['chunk_id']];doc=docs[anchor['document_id']];meta=s['context_metadata'];q=query_vectors[case['query']];e=anchor['embedding_json']
                if (s['document_id']!=anchor['document_id'] or item['document_id']!=s['document_id'] or item['chunk_id']!=s['chunk_id']
                    or s['title']!=doc['title'] or item['title']!=doc['title'] or item['chunk_index']!=anchor['chunk_index']
                    or item['source_type']!='internal' or item['url']!=verified_urls[doc['id']] or item['excerpt']!=s['excerpt']
                    or not 0<=s['start']<s['end']<=len(doc['content']) or doc['content'][s['start']:s['end']]!=s['excerpt']):raise ValueError('引用或原文坐标不同')
                if meta:
                    if (item['context_metadata']!=meta or meta['start']!=s['start'] or meta['end']!=s['end']
                        or meta['anchor_chunk_id']!=anchor['id'] or meta['document_id']!=doc['id']
                        or meta['source_text_sha256']!=doc['text_sha256'] or meta['method']!='anchor_neighbors'
                        or not 1<=len(meta['chunk_ids'])<=3 or len(set(meta['chunk_ids']))!=len(meta['chunk_ids'])
                        or anchor['id'] not in meta['chunk_ids'] or anchor['content'].strip() not in s['excerpt'] or len(s['excerpt'])>1600):raise ValueError('上下文元信息错误')
                    participants=[chunks[key] for key in meta['chunk_ids']]
                    if any(c['document_id']!=doc['id'] or abs(c['chunk_index']-anchor['chunk_index'])>1 for c in participants):raise ValueError('跨文档上下文')
                    cursor=s['start']
                    for c in sorted(participants,key=lambda c:c['start']):
                        if c['start']>cursor:break
                        cursor=max(cursor,c['end'])
                    if cursor<s['end']:raise ValueError('来源范围有缺口')
                elif not anchor['start']<=s['start']<s['end']<=anchor['end']:raise ValueError('无元信息却跨chunk')
                cos=sum(x*y for x,y in zip(q,e))/math.sqrt(sum(x*x for x in q)*sum(x*x for x in e))
                if (len(q)!=len(e) or not math.isclose(item['retrieval_score'],cos,rel_tol=1e-10,abs_tol=1e-10)
                    or item['retrieval_model']!=vectors['calls'][0]['model'] or item['retrieval_dimension']!=len(q)
                    or item['retrieval_method']!='embedding_cosine' or item['retrieval_anchor_excerpt']!=anchor['content'].strip()[:800]
                    or item['retrieval_query_fingerprint']!=hashlib.sha256(case['query'].strip()[:512].encode()).hexdigest()):raise ValueError('语义分被伪造')
        if group['summary']!=summarize(cases,rows) or group['source_chars']!=sum(len(s['excerpt']) for row in rows for s in row['sources']):raise ValueError('汇总不符')
    return r


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('--dataset',required=True,type=Path)
    p.add_argument('--corpus',required=True,type=Path);p.add_argument('--embeddings',required=True,type=Path)
    a=p.parse_args();r=verify(a.output,a.dataset,a.corpus,a.embeddings)
    print(f"PASS {len(r['groups']['after']['cases'])}题：输入/源码/原文/余弦值/URL/逐题/汇总独立重算")
