"""只复核本次已保存的真实 HTTP/UI 证据，不发起模型调用。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.ai/tasks/2026-10-08-source-authority/restart-http-v3'


def main():
    read = lambda name: json.loads((OUT / name).read_text(encoding='utf-8'))
    result = read('results.json')
    report = next(e['data'] for t in result['turns'] for e in t['events'] if e['event'] == 'structured')
    before, after, ui = read('ui-before.json'), read('ui-after.json'), read('ui-check.json')
    norm = lambda text: re.sub(r'\s+', '', text)
    sources = report['knowledge_citations']
    checks = {
        'real_http_mode': result['mode'] == 'running_http_real_models_and_database',
        'generated_saved_report': result['has_report'] and result['has_nonblank_reply'] and result['saved_report_matches'],
        'settings_unchanged': result['settings_unchanged'],
        'ten_source_cards': len(sources) == len(before['cards']) == len(after['cards']) == 10,
        'cards_identical_after_reload': before['cards'] == after['cards'],
        'all_citation_targets_exist': all(c['targetExists'] for c in after['citations']),
        'citation_count': len(after['citations']) == 29,
        'clicked_source_visible': ui['clickedCitation'] == 'S2' and 0 <= ui['target']['top'] < 500,
        'all_full_excerpts_visible': all(norm(s['excerpt']) in norm(c['text']) for s, c in zip(sources, after['cards'])),
        'all_source_urls_match': all(any(a['href'] == s['url'] for a in c['links']) for s, c in zip(sources, after['cards'])),
    }
    evidence = report['knowledge_evidence']
    summary = {
        'checks': checks, 'passed': all(checks.values()), 'source_count': len(sources),
        'independent_documents': len({s['document_id'] for s in sources}),
        'used_sources': sum(bool(s['used_in_report']) for s in sources),
        'evidence_count': len(evidence), 'needs_review': sum(e['status'] == 'needs_review' for e in evidence),
        'interview_stop_reason': report['interview_stop_reason'],
        'interview_is_sufficient': report['interview_is_sufficient'],
        'interview_information_gaps': report['interview_information_gaps'],
        'semantic_recovery_live_branch_verified': False, 'clinical_correctness_verified': False,
    }
    (OUT / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    assert summary['passed'], '引用链路存档证据检查失败'


if __name__ == '__main__':
    main()
