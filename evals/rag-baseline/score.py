"""按文档原文坐标评分，区分证据命中、完整覆盖和限定条件；不评价临床准确率。"""
def covers(intervals,start,end):
    cursor=start
    for left,right in sorted(intervals):
        if left>cursor:
            break
        cursor=max(cursor,right)
        if cursor>=end:
            return True
    return False


def score(case,units,sources,documents):
    ranges={}
    for source in sources:
        doc=documents.get(source['document_id'])
        a,b=source['start'],source['end']
        if not doc or not 0<=a<b<=len(doc['content']) or doc['content'][a:b]!=source['excerpt']:
            raise ValueError('返回来源与原文定位不一致')
        ranges.setdefault(source['document_id'],[]).append((a,b))
    if case['expected_action']=='no_evidence':
        return {'hit_at_k':None,'evidence_recall_at_k':None,'complete_evidence':None,
                'qualifier_recall':None,'mrr':None,'unsupported_candidate_returned':bool(sources)}
    gold=[units[uid] for uid in case['gold_ids']]
    hit=lambda u,s: s['document_id']==u['document_id'] and max(s['start'],u['start'])<min(s['end'],u['end'])
    covered=[covers(ranges.get(u['document_id'],[]),u['start'],u['end']) for u in gold]
    first=next((i+1 for i,s in enumerate(sources) if any(hit(u,s) for u in gold)),None)
    qualifiers=[covers(ranges.get(u['document_id'],[]),q['start'],q['end']) for u in gold for q in u['qualifiers']]
    return {'hit_at_k':bool(first),'evidence_recall_at_k':sum(covered)/len(gold),
            'complete_evidence':all(covered),'qualifier_recall':sum(qualifiers)/len(qualifiers) if qualifiers else None,
            'mrr':1/first if first else 0,'unsupported_candidate_returned':None}


def summarize(cases,rows):
    expected={c['id'] for c in cases}
    observed=[r.get('id') for r in rows]
    if not expected or len(expected)!=len(cases) or len(observed)!=len(expected) or set(observed)!=expected:
        raise ValueError('汇总拒绝空、缺失、重复或多余结果')
    failures=[r['id'] for r in rows if r.get('status')!='success']
    if failures:
        return {'status':'execution_incomplete','failed_ids':failures,'total':len(cases),'quality_metrics':None}
    positive=[r['score'] for r in rows if r['score']['hit_at_k'] is not None]
    negative=[r['score'] for r in rows if r['score']['hit_at_k'] is None]
    average=lambda name:sum(r[name] for r in positive if r[name] is not None)/sum(r[name] is not None for r in positive)
    return {'status':'complete_diagnostic','total':len(cases),'positive_cases':len(positive),'no_answer_cases':len(negative),
            'hit_at_k':average('hit_at_k') if positive else None,
            'evidence_recall_at_k':average('evidence_recall_at_k') if positive else None,
            'complete_evidence_rate':average('complete_evidence') if positive else None,
            'qualifier_recall':average('qualifier_recall') if positive and any(r['qualifier_recall'] is not None for r in positive) else None,
            'mrr':average('mrr') if positive else None,
            'unsupported_candidate_rate':sum(r['unsupported_candidate_returned'] for r in negative)/len(negative) if negative else None,
            'clinical_accuracy':None,'report_false_success_rate':None}
