import type { ReportLinksWorkspace } from '../api/reports.ts';

export const reportLinkLabels = {
  unverified: '关联原件，尚未本人核对', patient_confirmed: '关联的版本已本人核对',
  source_changed: '报告来源已变化，关联待更新', review_changed: '核对内容已变化，关联仍保留原版本',
};

/** 三个独立修订均不可倒退；晚到的刷新不能把关联/核对/来源显示回旧状态。 */
export function acceptLinksWorkspace(current: ReportLinksWorkspace | null, incoming: ReportLinksWorkspace) {
  if (current && (incoming.links_revision < current.links_revision || incoming.review_revision < current.review_revision
    || incoming.source_epoch < current.source_epoch)) return current;
  return incoming;
}
