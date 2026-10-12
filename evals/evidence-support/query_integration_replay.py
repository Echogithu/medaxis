"""历史模型JSON回放到当前来源链路；不调用模型，不等于真实问诊验收。"""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch
from query_experiment import TASK, groups_from_inputs
from query_experiment_verify import verify_all
from verify import load, require, digest
from app.services import knowledge_citations as kc
from app.services.query_requirements import parse_assessment


async def replay():
    verify_all()
    records = []
    for folder, assets in [('dev-full', 'query-development-v2'), ('v4-full', 'frozen-v4')]:
        groups = {g['id']: g for g in groups_from_inputs(load(TASK / assets / 'inputs.json'))}
        for observed in load(TASK / 'query-assessment-v3' / folder / 'observations.json')['groups']:
            group = groups[observed['id']]
            sources = [dict(case['candidate_source'], excerpt=case['candidate_source']['quote'],
                            chunk_id=case['id'], source_type='internal', url=case['candidate_source']['source_url'])
                       for case in group['cases']]
            candidates = kc.build_knowledge_citations(sources)
            require(len(candidates) == len(sources), '回放候选丢失')
            mapping = {case['id']: citation.citation_id for case, citation in zip(group['cases'], candidates)}
            raw = json.loads(observed['assessment']['raw_output'])
            for row in raw['candidates']: row['id'] = mapping[row['id']]
            count = 0

            async def recorded_assessment(query, citations, db):
                nonlocal count
                count += 1
                require(query == group['query'], '回放问题改变')
                return dict(parse_assessment(json.dumps(raw, ensure_ascii=False), [
                    {'id': c.citation_id, 'excerpt': c.excerpt} for c in citations]), status='assessed')

            with patch.object(kc, '_assess_query_coverage', recorded_assessment):
                ranked = await kc.rank_knowledge_citations(group['query'], candidates, None)
                expected = [mapping[cid] for cid in observed['after_order']]
                require([c.citation_id for c in ranked] == expected, '生产排序与存档结果不同')
                require(all(c.excerpt == candidates[int(c.citation_id[1:])-1].excerpt and
                            c.url == candidates[int(c.citation_id[1:])-1].url for c in ranked), '原文或URL改变')
                # 模拟报告入口先归一化来源、再生成正文；覆盖缓存不应重复判断。
                restored = kc.build_knowledge_citations([c.model_dump() for c in ranked])
                cached = await kc.rank_knowledge_citations(group['query'], restored, None)
                require(count == 1, '归一化来源后重复模型判断')
                markers = ' '.join('[' + c.citation_id + ']' for c in cached)
                report = kc.attach_knowledge_citations({'key_findings': [markers]}, cached)
                reloaded = json.loads(json.dumps(report, ensure_ascii=False))
                require(reloaded == report and all(c['used_in_report'] for c in report['knowledge_citations']), '引用或JSON往返丢失')
                require(all(c['query_coverage'] is not None for c in reloaded['knowledge_citations']), '保存覆盖信息丢失')
            records.append({'group': observed['id'], 'candidates': len(candidates), 'retained': len(ranked),
                            'assessment_replays': count, 'citation_binding_and_json_roundtrip': True})
    return {'status': 'PASS_RECORDED_JSON_INTEGRATION_ONLY', 'groups': len(records),
            'candidates': sum(r['candidates'] for r in records), 'records': records,
            'source_sha256': {name: digest(TASK.parents[2] / 'backend/app/services' / name)
                              for name in ('knowledge_citations.py', 'query_requirements.py')},
            'model_calls': 0, 'database_save_verified': False, 'http_page_verified': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = asyncio.run(replay())
    if args.output:
        require(not args.output.exists(), '不得覆盖回放记录')
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
