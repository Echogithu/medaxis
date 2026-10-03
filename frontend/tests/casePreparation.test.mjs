import assert from 'node:assert/strict';
import { test } from 'node:test';
import { getPreparationDraft, preparationFactId, preparationHasChanges, preparationSummary, preparationContext, setPreparationDraft } from '../src/state/casePreparation.ts';

function preparation() {
  return {
    version: 1, revision: 2,
    known_facts: [{ id: 'patient.chief_complaint', label: '主诉', value: '咳嗽三天', active: true, confirmed: false }],
    unknown_facts: [{ id: 'unknown.allergies', label: '过敏史', patient_response: '不清楚' }],
    unresolved_facts: [], patient_corrections: [], patient_questions: [],
    preparation_items: [{ id: 'bring.report', title: '携带报告', status: 'pending' }],
    summary: { materials: [{ filename: '合成检查.pdf' }], ai_inference: ['未确认的疑似诊断'] },
  };
}

test('档案摘要保留未填写和未知区别，显示中文记录而不暴露存储字段', () => {
  const item = preparation();
  item.known_facts = [{ id: 'patient.profile.chronic_diseases', label: '慢性病／特殊疾病',
    value: [{ id: 'internal-record-id', category: 'special', name: '合成疾病' }],
    display_value: '合成疾病；特殊疾病；严重程度：重度；确诊日期：2020-01-02' }];
  item.unknown_facts = [
    { id: 'unknown.allergies', label: '过敏史', record_state: 'not_recorded' },
    { id: 'unknown.medications', label: '当前用药', record_state: 'unknown' },
  ];
  const text = preparationSummary(item, [], {}, '');
  assert.match(text, /过敏史：未填写/);
  assert.match(text, /当前用药：未知/);
  assert.match(text, /特殊疾病；严重程度：重度；确诊日期：2020-01-02/);
  assert.equal(text.includes('internal-record-id'), false);
  assert.equal(text.includes('category'), false);
});

test('携带摘要与病情核对使用同一原话语境，修改草稿不会沿用旧判断', () => {
  const item = preparation();
  const fact = item.known_facts[0];
  fact.clinical_context = [{ text: '母亲患有糖尿病', status: 'non_patient', advisory: true },
    { text: '我目前咳嗽3天', status: 'present', advisory: true }];
  assert.deepEqual(preparationContext(fact), ['母亲患有糖尿病（家属信息）', '我目前咳嗽3天（当前表述）']);
  const text = preparationSummary(item, [], {}, '');
  assert.match(text, /母亲患有糖尿病（家属信息）/);
  assert.match(text, /我目前咳嗽3天（当前表述）/);
  const changed = preparationSummary(item, [], { 'patient.chief_complaint': '目前没有咳嗽' }, '');
  assert.equal(changed.includes('家属信息'), false);
  assert.match(changed, /语境待保存后重新核对/);
});

test('医生摘要保留患者事实、未知、材料与问题，AI 疑似诊断不混入患者陈述', () => {
  const text = preparationSummary(preparation(), [], {}, '需不需要复查？');
  assert.match(text, /咳嗽三天（待本人核对）/);
  assert.match(text, /过敏史：未知；患者原话：不清楚/);
  assert.match(text, /合成检查.pdf/);
  assert.match(text, /需不需要复查？/);
  assert.equal(text.includes('未确认的疑似诊断'), false);
  assert.match(text, /版本 1 · 修订 2/);
});

test('默认摘要只显示当前更正，原话仍留在数据和核对详情', () => {
  const item = preparation();
  item.known_facts[0].active = false;
  item.known_facts.push({ id: 'correction.patient.chief_complaint', label: '主诉', value: '牙痛', active: true, confirmed: true });
  item.patient_corrections = [{ fact_id: 'patient.chief_complaint', value: '牙痛' }];
  const text = preparationSummary(item, ['correction.patient.chief_complaint'], { 'patient.chief_complaint': '牙痛' }, '');
  assert.match(text, /主诉：牙痛/);
  assert.equal(text.includes('咳嗽三天'), false);
  assert.equal(item.known_facts[0].value, '咳嗽三天');
});

test('矛盾和当前补充同时保留，未知不会被自动变成否认', () => {
  const item = preparation();
  item.unresolved_facts = [{ id: 'unresolved.fever', label: '发热', statements: [{ value: '发热 38.5℃' }, { value: '没有发热' }] }];
  const text = preparationSummary(item, [], { 'unresolved.fever': '记不清，需要核对' }, '');
  for (const fragment of ['仍待核对', '发热 38.5℃', '没有发热', '记不清，需要核对', '过敏史：未知']) assert.ok(text.includes(fragment), fragment);
});

test('复制前能发现确认、补充、清单及问题的未保存变化', () => {
  const item = preparation();
  assert.equal(preparationHasChanges(item, [], {}, {}, ''), false);
  assert.equal(preparationHasChanges(item, ['patient.chief_complaint'], {}, {}, ''), true);
  assert.equal(preparationHasChanges(item, [], { 'unknown.allergies': '青霉素' }, {}, ''), true);
  assert.equal(preparationHasChanges(item, [], {}, { 'bring.report': 'ready' }, ''), true);
  assert.equal(preparationHasChanges(item, [], {}, {}, '复查时间？'), true);
  assert.equal(preparationHasChanges(item, [], { empty: '  ' }, {}, '\n'), false);
});

test('重复更正仍定位原事实，摘要读取本次更正', () => {
  const item = preparation();
  item.known_facts = [{ id: 'correction.correction.patient.chief_complaint', label: '主诉', value: '牙痛', active: true }];
  assert.equal(preparationFactId(item.known_facts[0]), 'patient.chief_complaint');
  const text = preparationSummary(item, [], { 'patient.chief_complaint': '腹泻' }, '');
  assert.match(text, /主诉：腹泻/);
  assert.equal(text.includes('牙痛'), false);
  assert.equal(text.includes('患者补充：腹泻'), false);
});

test('浏览会话草稿按病例隔离，保存后可清除，输入变化不污染已存草稿', () => {
  const draft = { version: 1, revision: 2, confirmedIds: [], corrections: {}, checklist: {}, questionsText: '复查？', summaryText: '合成草稿' };
  setPreparationDraft('synthetic-a', draft);
  draft.questionsText = '之后的输入';
  assert.equal(getPreparationDraft('synthetic-a').questionsText, '复查？');
  assert.equal(getPreparationDraft('synthetic-b'), undefined);
  setPreparationDraft('synthetic-a', null);
  assert.equal(getPreparationDraft('synthetic-a'), undefined);
});
