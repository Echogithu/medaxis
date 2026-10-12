"""运行固定的新筛选反例；分数为合成测试输入，不能当作真实Embedding效果。"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock,patch
from replay import ROOT,read,digest
from app.services.knowledge_citations import build_knowledge_citations,rank_knowledge_citations
from app.services.reranker import RerankerService


async def main(output):
    path=Path(__file__).with_name('cases.json');data=read(path);rows=[]
    with patch.object(RerankerService,'rerank',AsyncMock(side_effect=ValueError('不调用重排供应商'))):
        for case in data['cases']:
            query=case['query'];sources=[]
            for index,source in enumerate(case['sources']):
                sources.append({'source_type':'internal','document_id':'synthetic-doc','chunk_id':str(index),
                    'title':source['title'],'excerpt':source['excerpt'],'retrieval_score':source['score'],
                    'retrieval_method':source.get('method','embedding_cosine'),'retrieval_model':source.get('model','text-embedding-3-small'),
                    'retrieval_dimension':source.get('dimension',1536),'retrieval_anchor_excerpt':source['excerpt'],
                    'retrieval_query_fingerprint':source.get('fingerprint',hashlib.sha256(query.encode()).hexdigest())})
            selected=await rank_knowledge_citations(query,build_knowledge_citations(sources),None)
            observed=[c.citation_id for c in selected]
            rows.append({'id':case['id'],'expected':case['expected_ids'],'actual':observed,'pass':observed==case['expected_ids']})
    result={'mode':'synthetic_source_filter_cases','cases_sha256':digest(path),'cases':rows,
            'passed':sum(r['pass'] for r in rows),'total':len(rows),'real_embedding_or_retrieval':False,'extra_model_calls':0}
    output.mkdir(parents=True,exist_ok=False)
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'cases.json').write_bytes(path.read_bytes())
    print(f"{result['passed']}/{result['total']} 合成筛选反例；不是新查询向量评测")
    if result['passed']!=result['total']:raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    asyncio.run(main(p.parse_args().output))
