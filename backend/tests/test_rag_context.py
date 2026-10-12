"""验证元信息补上下文，跨片段出处准确且不超预算。"""
from app.services.rag_context import select_context


def chunks(content,cut=1000):
    return [{'chunk_id':'left','document_id':'doc','chunk_index':0,'content':content[:cut]},
            {'chunk_id':'right','document_id':'doc','chunk_index':1,'content':content[cut-100:]}]


def test_cross_chunk_condition_can_be_kept_with_exact_document_coordinates():
    condition='处理示例：不能只看实验指标就调整方案；必须同时核对症状、观察时间和既往反应。'
    text='概述仅供背景阅读。'*105+condition+'后续段落讨论其他主题。'
    parts=chunks(text,text.index(condition)+len(condition)//2)
    result=select_context('处理示例调整方案核对症状观察时间既往反应',parts[0],text,parts,max_chars=1600)
    assert result is not None
    excerpt,meta=result
    assert condition in excerpt
    assert excerpt==text[meta['start']:meta['end']]
    assert len(excerpt)<=1600
    assert meta['anchor_chunk_id']=='left'
    assert meta['chunk_ids']==['left','right']


def test_duplicate_anchor_position_is_not_guessed():
    anchor={'chunk_id':'same','document_id':'doc','chunk_index':0,'content':'重复原文。'}
    assert select_context('重复原文',anchor,'重复原文。其他内容。重复原文。',[anchor]) is None


def test_foreign_document_neighbor_cannot_add_text():
    anchor={'chunk_id':'a','document_id':'doc','chunk_index':0,'content':'主题原文。'}
    foreign={'chunk_id':'b','document_id':'other','chunk_index':1,'content':'其他病例记录。'}
    result=select_context('其他病例',anchor,'主题原文。其他病例记录。',[anchor,foreign])
    assert '其他病例' not in result[0]
    assert result[1]['chunk_ids']==['a']


def test_full_anchor_is_kept_for_cross_language_query():
    content='English excerpt without Chinese terms. '+('other sentence. '*80)
    anchor={'chunk_id':'a','document_id':'doc','chunk_index':0,'content':content}
    result=select_context('中文问题',anchor,content,[anchor],max_chars=1600)
    assert content.strip()==result[0]


def test_anchor_larger_than_budget_does_not_pretend_complete():
    anchor={'chunk_id':'a','document_id':'doc','chunk_index':0,'content':'完整句。'*100}
    assert select_context('问题',anchor,anchor['content'],[anchor],max_chars=100) is None


def test_missing_anchor_text_returns_no_context():
    anchor={'chunk_id':'a','document_id':'doc','chunk_index':0,'content':'不存在的原文'}
    assert select_context('问题',anchor,'实际原文。',[anchor]) is None


def test_gap_between_adjacent_indices_cannot_be_crossed():
    anchor={'chunk_id':'a','document_id':'doc','chunk_index':0,'content':'命中内容。'}
    neighbor={'chunk_id':'b','document_id':'doc','chunk_index':1,'content':'不相连邻居。'}
    result=select_context('',anchor,'命中内容。未被片段覆盖的空隙。不相连邻居。',[anchor,neighbor])
    assert result[0]=='命中内容。'
    assert result[1]['chunk_ids']==['a']


def test_neighbor_metadata_does_not_replace_anchor_identity():
    anchor={'chunk_id':'a','document_id':'doc','chunk_index':0,'content':'命中内容。'}
    forged={**anchor,'content':'另一段落。'}
    assert select_context('',anchor,'命中内容。另一段落。',[forged]) is None


def test_negative_margin_cannot_drop_the_anchor():
    anchor={'chunk_id':'a','document_id':'doc','chunk_index':0,'content':'命中内容。'}
    assert select_context('',anchor,anchor['content'],[anchor],margin=-100) is None
