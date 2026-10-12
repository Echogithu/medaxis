import assert from 'node:assert/strict';
import { test } from 'node:test';
import { workflowStatus } from '../src/state/workflowStatus.ts';

test('失败优先于完成；停止流本身不代表成功', () => {
  assert.equal(workflowStatus([{ type: 'thinking', status: 'error' }], false), 'error');
  assert.equal(workflowStatus([{ type: 'complete', status: 'done' }, { type: 'thinking', status: 'error' }], false), 'error');
  assert.equal(workflowStatus([{ type: 'thinking', status: 'done' }], false), 'stopped');
});

test('有效完成与仍在流式执行分开判断', () => {
  assert.equal(workflowStatus([{ type: 'complete', status: 'done' }], false), 'completed');
  assert.equal(workflowStatus([{ type: 'complete', status: 'done' }], true), 'running');
  assert.equal(workflowStatus([], false), 'stopped');
});
