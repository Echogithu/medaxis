"""随访的归一化、患者自报执行和生命周期唯一真源。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select, update

from app.models.agent import CarePlan, MonitoringEvent

PROFILE_TIMEZONE = timezone(timedelta(hours=8))


def today():
    return datetime.now(PROFILE_TIMEZONE).date()


def envelope(plan):
    raw = deepcopy(plan.tasks or {})
    data = raw if isinstance(raw, dict) else {"tasks": raw}
    tasks = data.get("tasks", [])
    tasks = tasks if isinstance(tasks, list) else []
    normalized = []
    used = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or uuid5(NAMESPACE_URL, f"care-plan:{plan.id}:{index}"))
        if task_id in used:
            task_id = str(uuid5(NAMESPACE_URL, f"care-plan:{plan.id}:{index}:duplicate"))
        used.add(task_id)
        task["id"] = task_id
        task["status"] = "completed" if task.get("completed") is True or task.get("status") == "completed" else "pending"
        normalized.append(task)
    data["tasks"] = normalized
    data["metadata"] = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return data


def effective_status(plan):
    if plan.status == "active" and plan.end_date and plan.end_date < today():
        return "expired"
    return plan.status


def serialize(plan):
    data = envelope(plan)
    tasks, meta = data["tasks"], data["metadata"]
    for task in tasks:
        due = task.get("due_date")
        task["is_overdue"] = bool(due and isinstance(due, str) and due < today().isoformat() and task["status"] != "completed")
    status = effective_status(plan)
    return {
        "id": str(plan.id), "title": plan.title, "description": plan.description,
        "diagnosis_summary": plan.diagnosis_summary, "goals": [], "tasks": tasks,
        "status": plan.status, "effective_status": status,
        "progress_percent": round(100 * sum(task["status"] == "completed" for task in tasks) / len(tasks)) if tasks else 0,
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "end_date": plan.end_date.isoformat() if plan.end_date else None,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
        "source_type": meta.get("source_type", "legacy_record"),
        "source_case_id": meta.get("source_case_id"), "source_case_title": meta.get("source_case_title"),
        "confirmed_at": meta.get("confirmed_at"), "updated_at": meta.get("updated_at"),
        "revision": meta.get("revision", 0),
        "can_execute": status == "active" and (not plan.start_date or plan.start_date <= today()),
        "timezone": "Asia/Shanghai",
    }


async def owned_plan(db, plan_id, patient_id, *, lock=False):
    stmt = select(CarePlan).where(CarePlan.id == plan_id, CarePlan.patient_id == patient_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    plan = (await db.execute(stmt)).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, "随访计划不存在")
    return plan


def require_revision(plan, expected):
    if expected != envelope(plan)["metadata"].get("revision", 0):
        raise HTTPException(409, "计划已被更新，请重新加载后操作")


def save_envelope(plan, data):
    meta = data["metadata"]
    meta["revision"] = meta.get("revision", 0) + 1
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    plan.tasks = data
    tasks = data["tasks"]
    plan.progress_percent = round(100 * sum(t["status"] == "completed" for t in tasks) / len(tasks)) if tasks else 0


async def complete_task(db, plan_id, patient_id, task_id, *, value=None, notes=None):
    plan = await owned_plan(db, plan_id, patient_id, lock=True)
    data = envelope(plan)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(404, "随访任务不存在")
    # 已成功的请求重发保持原始执行记录，禁止覆盖数值、备注与时间。
    if task["status"] == "completed":
        return {"success": True, "task_id": task_id, "task_status": "completed", "plan": serialize(plan)}
    if not serialize(plan)["can_execute"]:
        raise HTTPException(409, "计划尚未生效、已暂停、到期或结束，不能执行任务")
    if value is not None and task.get("type") != "self_check":
        raise HTTPException(422, "仅自测任务可以记录数值")
    task.update(status="completed", completed=True, completed_at=datetime.now(timezone.utc).isoformat(),
                completion_source="patient_reported", last_value=value, completion_notes=notes or "")
    if all(t["status"] == "completed" for t in data["tasks"]):
        plan.status = "completed"
        plan.completed_at = datetime.now(timezone.utc)
    save_envelope(plan, data)
    # 任务或计划结束后，尚未发送的提醒失效；历史发送记录不改变。
    events = (await db.scalars(select(MonitoringEvent).where(
        MonitoringEvent.plan_id == plan.id, MonitoringEvent.patient_id == patient_id,
        MonitoringEvent.status.in_(["pending", "paused", "failed"]),
    ))).all()
    for event in events:
        if plan.status == "completed" or str((event.payload or {}).get("id") or (event.payload or {}).get("task_id")) == task_id:
            event.status = "cancelled"
    await db.commit()
    return {"success": True, "task_id": task_id, "task_status": "completed", "plan": serialize(plan)}


async def apply_action(db, plan, action, revision):
    data = envelope(plan)
    target = {"confirm": "active", "pause": "paused", "resume": "active", "cancel": "cancelled"}[action]
    previous_action = data["metadata"].get("last_action", {})
    if plan.status == target and previous_action == {"action": action, "expected_revision": revision}:
        return serialize(plan)
    require_revision(plan, revision)
    allowed = {"confirm": {"pending_confirmation"}, "pause": {"active"}, "resume": {"paused"},
               "cancel": {"pending_confirmation", "active", "paused"}}
    if plan.status not in allowed[action]:
        raise HTTPException(409, "当前计划状态不支持该操作")
    if action != "cancel" and plan.end_date and plan.end_date < today():
        raise HTTPException(409, "计划已到期，请取消后按新的日期创建")
    plan.status = target
    if action == "confirm":
        data["metadata"]["confirmed_at"] = datetime.now(timezone.utc).isoformat()
        data["metadata"]["confirmation_source"] = "patient_reported"
    data["metadata"]["last_action"] = {"action": action, "expected_revision": revision}
    save_envelope(plan, data)
    event_filter = [MonitoringEvent.plan_id == plan.id, MonitoringEvent.patient_id == plan.patient_id]
    if action == "pause":
        await db.execute(update(MonitoringEvent).where(*event_filter, MonitoringEvent.status == "pending").values(status="paused"))
    elif action == "resume":
        # 暂停期间错过的事件不集中补发，保留为取消；未来事件恢复等待。
        now = datetime.now(timezone.utc)
        await db.execute(update(MonitoringEvent).where(*event_filter, MonitoringEvent.status == "paused", MonitoringEvent.scheduled_at <= now).values(status="cancelled"))
        await db.execute(update(MonitoringEvent).where(*event_filter, MonitoringEvent.status == "paused", MonitoringEvent.scheduled_at > now).values(status="pending"))
    elif action == "cancel":
        await db.execute(update(MonitoringEvent).where(*event_filter, MonitoringEvent.status.in_(["pending", "paused", "failed"])).values(status="cancelled"))
    await db.commit()
    return serialize(plan)
