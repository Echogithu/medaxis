"""患者手动随访入口；来源与确认不会升级为医护核验。"""
from datetime import datetime
import hashlib
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_db
from app.models.agent import CarePlan, AgentSession
from app.models.medical_case import MedicalCase
from app.models.user import User, UserRole
from app.schemas.care_plan import CarePlanCreate, CarePlanEdit, CarePlanAction
from app.services.care_plan import apply_action, complete_task, envelope, owned_plan, require_revision, save_envelope, serialize, today

router = APIRouter()


def require_patient(user):
    if user.role != UserRole.PATIENT:
        raise HTTPException(403, "仅患者可维护本人随访计划")


async def source_case(db, case_id, patient_id):
    if case_id is None:
        return None
    case = (await db.execute(select(MedicalCase).where(
        MedicalCase.id == case_id, MedicalCase.patient_id == patient_id,
    ))).scalar_one_or_none()
    if case is None:
        raise HTTPException(404, "关联病历不存在")
    if case.source_session_id:
        session = await db.get(AgentSession, case.source_session_id)
        if session is None or session.user_id != patient_id:
            raise HTTPException(404, "关联病历来源不存在")
    return case


def fields_into_plan(plan, fields, case):
    plan.title, plan.description = fields.title, fields.description
    plan.start_date, plan.end_date = fields.start_date, fields.end_date
    plan.source_session_id = case.source_session_id if case else None
    data = envelope(plan)
    data["tasks"] = [dict(task.model_dump(mode="json"), id=str(task.id or uuid4()), status="pending") for task in fields.tasks]
    data["metadata"].update(source_type="patient_reported", source_case_id=str(case.id) if case else None,
                            source_case_title=case.title if case else None)
    save_envelope(plan, data)


@router.post("/care-plans", status_code=201)
async def create_care_plan(data: CarePlanCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(current_user)
    # 同一患者重复点击/网络重试只创建一条；共享主键阻止跨患者冒用请求ID。
    await db.execute(select(User).where(User.id == current_user.id).with_for_update())
    fingerprint = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    existing = await db.get(CarePlan, data.request_id)
    if existing:
        if existing.patient_id != current_user.id:
            raise HTTPException(409, "创建请求 ID 已使用，请重新创建")
        if envelope(existing)["metadata"].get("creation_fingerprint") != fingerprint:
            raise HTTPException(409, "同一创建请求内容发生变化，请使用新的请求 ID")
        return serialize(existing)
    case = await source_case(db, data.source_case_id, current_user.id)
    plan = CarePlan(id=data.request_id, patient_id=current_user.id, status="pending_confirmation",
                    tasks={}, created_by="patient")
    fields_into_plan(plan, data, case)
    plan.tasks["metadata"]["creation_fingerprint"] = fingerprint
    db.add(plan)
    await db.commit()
    return serialize(plan)


@router.get("/care-plans")
async def list_care_plans(
    current_user: CurrentUser,
    status: Literal["pending_confirmation", "active", "paused", "completed", "cancelled", "expired"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    include_page: bool = False,
    cursor_at: datetime | None = None,
    cursor_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    require_patient(current_user)
    if (cursor_at is None) != (cursor_id is None) or (cursor_at is not None and cursor_at.utcoffset() is None):
        raise HTTPException(422, "分页游标需同时提供含时区的时间和 ID")
    stmt = select(CarePlan).where(CarePlan.patient_id == current_user.id)
    if status == "expired":
        stmt = stmt.where(CarePlan.status == "active", CarePlan.end_date < today())
    elif status:
        stmt = stmt.where(CarePlan.status == status)
        if status == "active":
            stmt = stmt.where(or_(CarePlan.end_date.is_(None), CarePlan.end_date >= today()))
    stmt = stmt.order_by(CarePlan.created_at.desc(), CarePlan.id.desc())
    if cursor_at:
        stmt = stmt.where(or_(CarePlan.created_at < cursor_at, and_(CarePlan.created_at == cursor_at, CarePlan.id < cursor_id)))
    else:
        stmt = stmt.offset((page - 1) * limit)
    plans = (await db.scalars(stmt.limit(limit + 1 if include_page else limit))).all()
    if not include_page:
        return [serialize(p) for p in plans]
    more = len(plans) > limit
    plans = plans[:limit]
    last = plans[-1] if more else None
    return {"items": [serialize(p) for p in plans], "next_cursor":
            {"created_at": last.created_at.isoformat(), "id": str(last.id)} if last else None}


@router.get("/care-plans/{plan_id}")
async def get_care_plan(plan_id: UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(current_user)
    return serialize(await owned_plan(db, plan_id, current_user.id))


@router.patch("/care-plans/{plan_id}")
async def edit_care_plan(plan_id: UUID, data: CarePlanEdit, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(current_user)
    plan = await owned_plan(db, plan_id, current_user.id, lock=True)
    require_revision(plan, data.expected_revision)
    if plan.status != "pending_confirmation":
        raise HTTPException(409, "只有待确认计划可以编辑；执行中的计划请先取消，再创建修订计划")
    case = await source_case(db, data.source_case_id, current_user.id)
    fields_into_plan(plan, data, case)
    await db.commit()
    return serialize(plan)


@router.post("/care-plans/{plan_id}/actions")
async def change_care_plan(plan_id: UUID, data: CarePlanAction, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(current_user)
    plan = await owned_plan(db, plan_id, current_user.id, lock=True)
    return await apply_action(db, plan, data.action, data.expected_revision)


@router.post("/care-plans/{plan_id}/ack")
async def ack_task(plan_id: UUID, task_id: Annotated[str, Query(min_length=1, max_length=100)],
                   current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(current_user)
    return await complete_task(db, plan_id, current_user.id, task_id)
