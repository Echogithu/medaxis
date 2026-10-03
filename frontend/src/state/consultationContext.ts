import type { ChatMessageItem, DiagnosisReport } from '../types/agent';
import { patientList, patientText } from './patientText.ts';

/** 只展示本次会话已有内容，不从自由文本推断诊断或安全等级。 */
export function consultationContext(messages: ChatMessageItem[], report: DiagnosisReport | null) {
  const descriptions = messages
    .filter(message => message.role === 'user' && !message.uploadStatus)
    .map(message => patientText(message.content))
    .filter(Boolean);
  const findings = patientList(report?.key_findings);
  const reportIndex = messages.findLastIndex(message => Boolean(message.structured));
  const additions = report && reportIndex >= 0
    ? messages.slice(reportIndex + 1)
      .filter(message => message.role === 'user' && !message.uploadStatus)
      .map(message => patientText(message.content)).filter(Boolean)
    : [];
  // 保留最初主诉和最近补充，避免长问诊将主诉挤出侧栏。
  const recentDescriptions = descriptions.length > 4
    ? [descriptions[0], ...descriptions.slice(-3)]
    : descriptions;
  const flags = patientList(report?.red_flags);
  const precautions = patientList(report?.contraindications);
  const referral = report?.referral_needed === true
    ? patientText(report.referral_reason) || '请尽早就医，由医生当面评估。'
    : '';
  const urgent = flags.length > 0 || Boolean(referral)
    || report?.severity === 'severe' || report?.severity === 'emergency';
  const safety = [...flags, ...precautions, ...(referral ? [referral] : [])];
  if (report?.severity === 'emergency') safety.unshift('本次总结提示需立即就医，请勿等待在线回复。');
  else if (report?.severity === 'severe') safety.unshift('本次总结提示需及时就医，由医生进一步评估。');
  const actions = patientList(report?.recommended_actions ?? report?.treatment_suggestions);
  const followUp = patientText(report?.follow_up_timeline ?? report?.follow_up_plan);

  return {
    summary: findings.length
      ? [...findings.slice(0, 4), ...additions.slice(-2).map(text => `补充：${text}`)]
      : recentDescriptions,
    summarySource: findings.length ? '总结要点' : '你的描述',
    hasNewInformation: additions.length > 0,
    safety: safety.length ? [...new Set(safety)] : ['AI 建议不能替代医生诊断；紧急情况请及时就医。'],
    urgent,
    actions: [...actions.slice(0, 3), ...(followUp ? [followUp] : [])],
  };
}
