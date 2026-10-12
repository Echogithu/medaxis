"""四方案的最小实验变量；不更改生产提示词、供应商或解析协议。"""
import hashlib
import json

from app.services.query_requirements import SYSTEM, make_messages

VARIANTS = ('B0', 'B1', 'B2', 'B3')
PROMPT_ADDITION = '''
补充审核边界：
问题开头的指南名称、章节或“按某规范”通常是查找上下文，不自动拆成必须证明资料身份的要点；只有明确要求核对作者、发布机构、版次或出处时才把身份纳入请求。
把同一个临床主张的适用人群、比较方向、数值/单位、时间、否定和例外保留在同一个要点中。不能只核对年龄或标题而遗漏该年龄的剂量/阈值；所有并列要求必须保留。
covered=true的quote要足以支持该要点的完整主张：引用原文中的完整短句或带条件的连续片段，不用只出现同一个关键词、单个数字或“高”“无”等单字作为支持。
若摘录只覆盖请求中的部分，逐项保留已回答内容，未回答的项用false；原文没有提到不表示医学上否定，也不能靠其他候选补齐。只有本摘录含义确实不确定时使用null，不能为每份资料新增问题没问的标准。
若输入含verified_source_identity，身份字段仅作核验出处上下文，不能补出临床正文没有的数值、条件或疗效。无论有无该字段，所有covered=true的quote仍必须来自该候选excerpt，不能把元信息伪装成正文引文。'''


def system_for(variant):
    if variant not in VARIANTS:
        raise ValueError('未知实验方案')
    return SYSTEM + PROMPT_ADDITION if variant in {'B1', 'B3'} else SYSTEM


def messages_for(question, variant):
    system_for(variant)
    sources = [{'id': s['id'], 'title': s['title'], 'excerpt': s['quote']} for s in question['candidates']]
    messages = make_messages(question['query'], sources)
    if variant in {'B2', 'B3'}:
        payload = json.loads(messages[0]['content'])
        lookup = {s['id']: s for s in question['candidates']}
        for item in payload['candidates']:
            s = lookup[item['id']]
            meta = s['metadata']
            if set(meta) != {'publisher', 'edition', 'published_date', 'verification_status'}:
                raise ValueError('核验元信息字段不同')
            item['verified_source_identity'] = {**meta, 'source_url': s['source_url'],
                'document_id': s['document_id'], 'document_sha256': s['document_sha256'], 'start': s['start'], 'end': s['end']}
        messages = [{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        if len(messages[0]['content']) > 24000:
            raise ValueError('元数据输入超预算，不截断原文')
    return messages


def request_key(question, variant, model_snapshot):
    value = {'variant': variant, 'system': system_for(variant), 'messages': messages_for(question, variant),
             'model_snapshot': model_snapshot, 'max_tokens': 4096, 'temperature': 'omitted_by_current_LLMService',
             'timeout_seconds': 60, 'sdk_retries': 0}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
