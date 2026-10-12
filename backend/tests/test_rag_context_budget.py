"""实验预算不能悄悄改变旧来源或扩大外部摘录。"""
from app.services.knowledge_citations import build_knowledge_citations


def test_default_internal_budget_and_source_identity_are_preserved():
    source = {'source_type': 'internal', 'document_id': 'doc', 'chunk_id': 'chunk',
              'title': '原始来源', 'excerpt': '原' * 2000}
    item = build_knowledge_citations([source])[0]
    assert item.document_id == 'doc'
    assert item.chunk_id == 'chunk'
    assert item.citation_id == 'S1'
    assert len(item.excerpt) == 800


def test_explicit_internal_budget_is_bounded_and_external_budget_is_unchanged():
    sources = [{'source_type': 'internal', 'document_id': 'doc', 'chunk_id': 'chunk',
                'title': '内部', 'excerpt': '内' * 2000},
               {'source_type': 'external', 'url': 'https://example.org/source',
                'title': '外部', 'excerpt': '外' * 2000}]
    internal, external = build_knowledge_citations(sources, max_excerpt_chars=10000)
    assert len(internal.excerpt) == 1600
    assert len(external.excerpt) == 800
