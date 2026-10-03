import assert from 'node:assert/strict';
import { test } from 'node:test';
import { consultationContext } from '../src/state/consultationContext.ts';

const user = content => ({ id: content, role: 'user', content, timestamp: new Date() });

test('空会话不显示示例患者数据或安全判断', () => {
  const result = consultationContext([], null);
  assert.deepEqual(result.summary, []);
  assert.deepEqual(result.actions, []);
  assert.equal(result.urgent, false);
  assert.equal(result.safety.some(text => text.includes('没有危险信号')), false);
});

test('问诊中保留主诉与最新补充，不把助手文本当成患者描述', () => {
  const messages = [user('头痛'), { ...user('助手分析'), role: 'agent' }, ...['一天', '两天', '三天', '四天'].map(user)];
  assert.deepEqual(consultationContext(messages, null).summary, ['头痛', '两天', '三天', '四天']);
  assert.deepEqual(consultationContext([user('腹痛')], null).summary, ['腹痛']);
});

test('报告支持旧字段并显示所有风险，截短概览不截断安全提示', () => {
  const report = { key_findings: ['血压 135/85 mmHg', '睡眠 6 小时'],
    treatment_suggestions: ['建议一', '建议二', '建议三', '建议四'], follow_up_plan: '三天后复查',
    red_flags: ['风险一', '风险二', '风险三', '风险四', '风险五'],
    contraindications: ['注意事项'], referral_needed: true, referral_reason: '建议面诊' };
  const result = consultationContext([user('主诉')], report);
  assert.deepEqual(result.summary, report.key_findings);
  assert.deepEqual(result.actions, ['建议一', '建议二', '建议三', '三天后复查']);
  assert.deepEqual(result.safety, [...report.red_flags, '注意事项', '建议面诊']);
  assert.equal(result.urgent, true);
});

test('紧急等级即使无 red_flags 也保留就医提示', () => {
  const result = consultationContext([], { severity: 'emergency', red_flags: [] });
  assert.equal(result.urgent, true);
  assert.match(result.safety[0], /立即就医/);
});

test('报告后新补充纳入摘要并标注建议仍来自报告快照', () => {
  const report = { key_findings: ['原要点'], recommended_actions: ['原建议'], red_flags: ['原风险'] };
  const messages = [user('主诉'), { ...user('总结'), role: 'agent', structured: report }, user('今天症状变化')];
  const result = consultationContext(messages, report);
  assert.deepEqual(result.summary, ['原要点', '补充：今天症状变化']);
  assert.equal(result.hasNewInformation, true);
  assert.deepEqual(result.safety, ['原风险']);
  assert.deepEqual(result.actions, ['原建议']);
  assert.equal(consultationContext(messages.slice(0, 2), report).hasNewInformation, false);
});

test('异常展示字段与文件消息不生成错误摘要', () => {
  const result = consultationContext([{ ...user('上传文件'), uploadStatus: 'completed' }],
    { key_findings: [null, 1, '有效要点'], red_flags: '非数组', recommended_actions: [null] });
  assert.deepEqual(result.summary, ['有效要点']);
  assert.deepEqual(result.actions, []);
  assert.equal(result.urgent, false);
});
