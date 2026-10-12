"""量尺v2：只忽略原文范围中的纯空白缺口；其他字符与限定条件仍必须覆盖。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'rag-baseline'))
from score import score as strict_score,summarize


def covers_text(intervals,start,end,content):
    cursor=start
    for left,right in sorted(intervals):
        if right<=cursor:continue
        if left>cursor and content[cursor:min(left,end)].strip():return False
        cursor=max(cursor,right)
        if cursor>=end:return True
    return not content[cursor:end].strip()


def score(case,units,sources,documents):
    result=strict_score(case,units,sources,documents)
    if case['expected_action']=='no_evidence':return result
    ranges={}
    for s in sources:ranges.setdefault(s['document_id'],[]).append((s['start'],s['end']))
    gold=[units[uid] for uid in case['gold_ids']]
    covered=[covers_text(ranges.get(u['document_id'],[]),u['start'],u['end'],documents[u['document_id']]['content']) for u in gold]
    qualifiers=[covers_text(ranges.get(u['document_id'],[]),q['start'],q['end'],documents[u['document_id']]['content']) for u in gold for q in u['qualifiers']]
    result.update(evidence_recall_at_k=sum(covered)/len(gold),complete_evidence=all(covered),
                  qualifier_recall=sum(qualifiers)/len(qualifiers) if qualifiers else None)
    return result
