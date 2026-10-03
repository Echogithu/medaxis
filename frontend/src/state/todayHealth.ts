import type { CarePlan, CareTask, PatientReminder } from '../api/patient.ts';

export const CARE_TIMEZONE = 'Asia/Shanghai';

export function careDate(value: Date | string): string {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('sv-SE', { timeZone: CARE_TIMEZONE }).format(date);
}

export function careTasks(plan: CarePlan): CareTask[] {
  return Array.isArray(plan.tasks) ? plan.tasks : Array.isArray(plan.tasks?.tasks) ? plan.tasks.tasks : [];
}

export interface CareOverviewItem {
  id: string;
  title: string;
  detail: string;
  date: string;
  time: string;
  done: boolean;
  failed: boolean;
  path: '/followups' | '/reminders';
}

/** 首页只预览已安排事项，确认与打卡统一回到原功能页。 */
export function careOverview(plans: CarePlan[], reminders: PatientReminder[], today: string): CareOverviewItem[] {
  const tasks = plans.flatMap(plan => {
    const status = plan.effective_status || plan.status;
    if (!['active', 'completed'].includes(status || '')) return [];
    return careTasks(plan).filter(task => task.due_date && /^\d{4}-\d{2}-\d{2}$/.test(task.due_date))
      .map((task, index) => ({
        id: `task:${plan.id}:${task.id || index}`,
        title: task.description || task.name || '随访任务', detail: plan.title,
        date: task.due_date!, time: '', done: task.status === 'completed' || task.completed === true,
        failed: false, path: '/followups' as const,
      }));
  });
  const medications = reminders.filter(reminder => reminder.event_type === 'medication_reminder'
    && ['pending', 'in_flight', 'sent', 'acknowledged', 'failed'].includes(reminder.status))
    .map(reminder => {
      const payload = reminder.payload || {};
      const date = reminder.scheduled_at ? careDate(reminder.scheduled_at) : '';
      return {
        id: `reminder:${reminder.id}`,
        title: typeof payload.name === 'string' ? payload.name : '用药提醒',
        detail: [typeof payload.dosage === 'string' ? payload.dosage : '',
          reminder.status === 'sent' ? '待你确认' : reminder.status === 'failed' ? '发送失败' : '用药提醒'].filter(Boolean).join(' · '),
        date,
        time: date ? new Date(reminder.scheduled_at!).toLocaleTimeString('zh-CN', { timeZone: CARE_TIMEZONE, hour: '2-digit', minute: '2-digit' }) : '',
        done: reminder.status === 'acknowledged', failed: reminder.status === 'failed', path: '/reminders' as const,
      };
    });
  return [...tasks, ...medications].filter(item => item.date >= today)
    .sort((a, b) => `${a.date} ${a.time || '23:59'}`.localeCompare(`${b.date} ${b.time || '23:59'}`));
}
