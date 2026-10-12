import type { WorkflowStep } from '../types/agent.ts';

/** 流结束也可能是失败或等待回答，只有显式完成步骤才算成功。 */
export function workflowStatus(
  steps: Pick<WorkflowStep, 'type' | 'status'>[],
  isStreaming: boolean,
): 'error' | 'running' | 'completed' | 'stopped' {
  if (steps.some(step => step.status === 'error')) return 'error';
  if (isStreaming) return 'running';
  if (steps.some(step => step.type === 'complete' && step.status === 'done')) return 'completed';
  return 'stopped';
}
