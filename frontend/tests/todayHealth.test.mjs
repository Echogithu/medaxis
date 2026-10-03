import assert from 'node:assert/strict';
import { test } from 'node:test';
import { careDate, careOverview } from '../src/state/todayHealth.ts';

test('今日按北京时间处理 UTC 跨日与无效时间', () => {
  assert.equal(careDate('2026-10-01T16:01:00Z'), '2026-10-02');
  assert.equal(careDate('2026-10-01T15:59:00Z'), '2026-10-01');
  assert.equal(careDate('invalid'), '');
});

test('已暂停和待确认计划不进入照护待办；兼容旧任务容器', () => {
  const task = { id: 't', description: '自测记录', due_date: '2026-10-02' };
  const plans = ['active', 'paused', 'pending_confirmation', 'expired', 'cancelled'].map(status => ({ id: status, title: status, effective_status: status, tasks: { tasks: [task] } }));
  assert.deepEqual(careOverview(plans, [], '2026-10-02').map(item => item.id), ['task:active:t']);
});

test('用药排除取消、未定时间与随访提醒，保留失败和打卡状态', () => {
  const base = { scheduled_at: '2026-10-01T23:00:00Z', event_type: 'medication_reminder', payload: { name: '合成药物', dosage: '原处方剂量' } };
  const reminders = [
    { ...base, id: 'done', status: 'acknowledged' },
    { ...base, id: 'failed', status: 'failed' },
    { ...base, id: 'cancelled', status: 'cancelled' },
    { ...base, id: 'unknown', status: 'pending', scheduled_at: null },
    { ...base, id: 'followup', status: 'sent', event_type: 'follow_up' },
  ];
  const result = careOverview([], reminders, '2026-10-02');
  assert.deepEqual(result.map(item => [item.id, item.time, item.done, item.failed]), [
    ['reminder:done', '07:00', true, false], ['reminder:failed', '07:00', false, true],
  ]);
  assert.equal(result[0].path, '/reminders');
});

test('忽略历史事项并按日期时间排序，不改写源数据', () => {
  const plans = [{ id: 'p', title: '合成计划', status: 'active', tasks: [
    { id: 'old', due_date: '2026-10-01' }, { id: 'next', due_date: '2026-10-03' },
    { id: 'today', due_date: '2026-10-02', completed: true },
  ] }];
  const reminders = [{ id: 'morning', scheduled_at: '2026-10-02T00:00:00Z', event_type: 'medication_reminder', status: 'sent', payload: null }];
  const original = structuredClone({ plans, reminders });
  assert.deepEqual(careOverview(plans, reminders, '2026-10-02').map(item => item.id), ['reminder:morning', 'task:p:today', 'task:p:next']);
  assert.deepEqual({ plans, reminders }, original);
});
