"""合成报告反例：隐私遮蔽和候选原文依据，不调用真实模型。"""
import json
from types import SimpleNamespace

import pytest

from app.services.report_candidates import CandidateError, grounded_candidate, masked_pages, outgoing_text

USER = SimpleNamespace(full_name='合成患者', email='synthetic@example.invalid', phone='13800000000')
LINE = '白细胞 WBC 6.2 10^9/L 参考范围 3.5-9.5 ↑'


def candidate(**changes):
    return json.dumps({'indicators': [{'name': 'WBC', 'raw_value': '6.2', 'unit': '10^9/L',
        'reference_range': '3.5-9.5', 'abnormal_mark': '↑', 'source_page': 1, 'evidence': LINE} | changes],
        'sections': []}, ensure_ascii=False)


def test_masks_identity_and_urls_but_keeps_measurements():
    text = f'姓名：{USER.full_name}\n{USER.phone} {USER.email}\n报告编号：AB-12345\n'
    text += '条码: 555666777\nhttps://example.invalid/private.pdf\ndata:image/png;base64,secret\n' + LINE
    pages = masked_pages([{'page': 1, 'text': text}], USER)
    assert LINE in pages[0]['text']
    for hidden in [USER.full_name, USER.email, USER.phone, 'AB-12345', '555666777', 'https://', 'data:image']:
        assert hidden not in pages[0]['text']
    assert pages == masked_pages(pages, USER)
    assert outgoing_text('lab', pages).startswith('报告类别：检验报告\n')


def test_json_like_manual_text_is_not_reserialized_at_wire():
    from app.services.text_privacy import redact_for_provider
    pages = masked_pages([{'page': 1, 'text': '{"姓名":"合成患者","WBC":"6.2"}'}], USER)
    actual = outgoing_text('lab', pages)
    assert actual == redact_for_provider(actual)


def test_valid_numeric_and_unknown_optional_fields():
    result = grounded_candidate(candidate(), 'lab', [{'page': 1, 'text': LINE}])
    assert 'unverified' == result['review_status']
    assert '6.2' == result['indicators'][0]['raw_value']
    assert 'ai_text_extraction' == result['source']
    result = grounded_candidate(candidate(unit=None, reference_range=None, abnormal_mark=None), 'lab', [{'page': 1, 'text': LINE}])
    assert None is result['indicators'][0]['unit']
    assert None is result['indicators'][0]['abnormal_mark']


@pytest.mark.parametrize('changes', [
    {'raw_value': '正常'}, {'unit': 'mg/L'}, {'reference_range': '1-2'},
    {'abnormal_mark': '正常'}, {'source_page': 2}, {'evidence': '不存在的原文'},
    {'raw_value': '2'}, {'name': 'CRP'},
], ids=['invent-value', 'invent-unit', 'invent-range', 'invent-normal', 'wrong-page', 'wrong-quote', 'number-substring', 'wrong-name'])
def test_fabrications_are_rejected(changes):
    with pytest.raises(CandidateError):
        grounded_candidate(candidate(**changes), 'lab', [{'page': 1, 'text': LINE}])


def test_qualitative_and_imaging_without_lab_values():
    line = '示例项目 阴性'
    result = grounded_candidate(candidate(name='示例项目', raw_value='阴性', unit=None, reference_range=None,
        abnormal_mark=None, evidence=line), 'lab', [{'page': 1, 'text': line}])
    assert '阴性' == result['indicators'][0]['raw_value']
    text = '所见：合成影像描述，仅用于测试。'
    response = json.dumps({'indicators': [], 'sections': [{'kind': 'findings', 'text': text,
        'source_page': 1, 'evidence': text}]}, ensure_ascii=False)
    result = grounded_candidate(response, 'imaging', [{'page': 1, 'text': text}])
    assert [] == result['indicators'] and not result['needs_manual_entry']
    with pytest.raises(CandidateError):
        grounded_candidate(candidate(), 'imaging', [{'page': 1, 'text': LINE}])


@pytest.mark.parametrize('content', ['not json', '{}', '{"indicators":[],"sections":[],"diagnosis":"invented"}'], ids=['invalid-json', 'missing-fields', 'extra-diagnosis'])
def test_invalid_or_missing_result_is_not_success(content):
    with pytest.raises(CandidateError):
        grounded_candidate(content, 'lab', [{'page': 1, 'text': LINE}])


def test_empty_result_is_explicitly_manual_and_never_normal():
    result = grounded_candidate('{"indicators":[],"sections":[]}', 'lab', [{'page': 1, 'text': LINE}])
    assert result['needs_manual_entry'] and 'unverified' == result['review_status']


@pytest.mark.parametrize('line,value', [('WBC -6.2', '6.2'), ('WBC >6.2', '6.2'),
    ('WBC 弱阳性', '阳性'), ('WBC 非阴性', '阴性')], ids=['dropped-sign', 'dropped-operator', 'qualifier', 'negation'])
def test_result_must_not_drop_sign_operator_or_qualitative_modifier(line, value):
    with pytest.raises(CandidateError):
        grounded_candidate(candidate(raw_value=value, evidence=line, unit=None, reference_range=None,
            abnormal_mark=None), 'lab', [{'page': 1, 'text': line}])
