import test from 'node:test';
import assert from 'node:assert/strict';
import {
  reportFollowUp,
  reportRecommendedActions,
  reportRecommendedTests,
} from '../src/types/agent.ts';

test('report card and detail resolve canonical and legacy fields identically', () => {
  const report = {
    recommended_tests: ['血常规'],
    recommended_exams: ['旧检查字段'],
    recommended_actions: ['携带既有报告'],
    treatment_suggestions: ['旧措施字段'],
    follow_up_timeline: '复诊时间由医生确定',
    follow_up_plan: '旧随访字段',
  };
  assert.deepEqual(reportRecommendedTests(report), ['血常规']);
  assert.deepEqual(reportRecommendedActions(report), ['携带既有报告']);
  assert.equal(reportFollowUp(report), '复诊时间由医生确定');
});

test('report helpers retain legacy values when canonical fields are absent', () => {
  const report = {
    recommended_exams: ['旧检查字段'],
    treatment_suggestions: ['旧措施字段'],
    follow_up_plan: '旧随访字段',
  };
  assert.deepEqual(reportRecommendedTests(report), ['旧检查字段']);
  assert.deepEqual(reportRecommendedActions(report), ['旧措施字段']);
  assert.equal(reportFollowUp(report), '旧随访字段');
});
