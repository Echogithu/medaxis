"""定向健康咨询：患者确认快照、指定认证医生、持久回复与站内通知。"""
import hashlib
import json
from datetime import timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import CurrentUser
from app.api.v1.patient import get_case_recovery
from app.db.session import get_db
from app.models.consultation import ACTIVE_STATES, Consultation, ConsultationMessage, now
from app.models.document_parse import DocumentParseTask
from app.models.medical_case import MedicalCase
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole, UserStatus
from app.schemas.consultation import ConsultationAction, ConsultationCreate, ConsultationReply

router = APIRouter()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def profile(user):
    return {'id': str(user.id), 'name': user.full_name, 'role': user.role.value,
            'hospital': user.hospital, 'department': user.department, 'title': user.title}


def doctor_available(user):
    return user is not None and user.role == UserRole.DOCTOR and user.status == UserStatus.ACTIVE and user.is_verified


def permit(user):
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(403, '账号当前不可用')
    if user.role == UserRole.PATIENT:
        return
    if doctor_available(user):
        return
    raise HTTPException(403, '仅患者和已认证医生可使用咨询')


def patient_only(user):
    permit(user)
    if user.role != UserRole.PATIENT:
        raise HTTPException(403, '仅患者可执行此操作')


def result(item):
    return {'id': str(item.id), 'case_id': str(item.case_id), 'state': item.state, 'revision': item.revision}


def notify(db, item, sender, subject):
    is_patient = sender.id == item.patient_id
    recipient = item.doctor_id if is_patient else item.patient_id
    if recipient is None:
        return
    path = '/doctor' if is_patient else '/chat'
    db.add(Notification(sender_id=sender.id, recipient_id=recipient, notification_type=NotificationType.DIRECT,
        subject=subject, content='请打开咨询查看最新状态。', action_url=f'{path}?consultation_id={item.id}'))


async def expire_unavailable(db, item):
    doctor = await db.get(User, item.doctor_id, populate_existing=True) if item.doctor_id else None
    if item.state in ACTIVE_STATES and not doctor_available(doctor):
        item.state = 'unavailable'
        item.revision += 1
        item.updated_at = now()
        db.add(Notification(recipient_id=item.patient_id, notification_type=NotificationType.SYSTEM,
            subject='咨询医生当前不可用', content='本次咨询已停止共享，你可以重新选择医生。',
            action_url=f'/chat?consultation_id={item.id}'))


async def owned_consultation(db, user, consultation_id):
    permit(user)
    item = await db.scalar(select(Consultation).where(Consultation.id == consultation_id).with_for_update())
    if item is None or (user.role == UserRole.PATIENT and item.patient_id != user.id) or (user.role == UserRole.DOCTOR and item.doctor_id != user.id):
        raise HTTPException(404, '咨询不存在')
    if user.role == UserRole.PATIENT:
        await expire_unavailable(db, item)
    else:
        # 发布和读取时都重新查认证状态，不能依赖登录时的角色缓存。
        current = await db.get(User, user.id, populate_existing=True, with_for_update=True)
        if not doctor_available(current):
            raise HTTPException(403, '医生认证或账号已失效')
    return item


async def preview(db, user, case_id):
    patient_only(user)
    recovery = await get_case_recovery(case_id, user, db)
    case = await db.get(MedicalCase, case_id)
    file_ids = [material['file_id'] for material in recovery['materials'] if material['status'] == 'completed']
    tasks = (await db.scalars(select(DocumentParseTask).where(
        DocumentParseTask.owner_user_id == user.id, DocumentParseTask.file_id.in_(file_ids)).order_by(DocumentParseTask.created_at))).all() if file_ids else []
    data = {'case_title': case.title, 'chief_complaint': case.chief_complaint,
        'description': case.description, 'ai_summary': case.ai_diagnosis_summary,
        'report': recovery['report'], 'materials': [
            {'file_id': task.file_id, 'filename': task.filename, 'result': {**task.result, 'file_id': task.file_id}}
            for task in tasks if isinstance(task.result, dict) and task.result]}
    return {**data, 'source_fingerprint': digest(data)}


@router.get('/doctors')
async def doctors(user: CurrentUser, db: AsyncSession = Depends(get_db), page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=50)):
    patient_only(user)
    rows = (await db.scalars(select(User).where(User.role == UserRole.DOCTOR, User.status == UserStatus.ACTIVE,
        User.is_verified.is_(True)).order_by(User.full_name, User.id).offset((page-1)*limit).limit(limit+1))).all()
    return {'items': [profile(row) for row in rows[:limit]], 'has_more': len(rows) > limit}


@router.get('/preview/{case_id}')
async def consultation_preview(case_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await preview(db, user, case_id)


@router.post('', status_code=201)
async def create_consultation(data: ConsultationCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    patient_only(user)
    fingerprint = digest({**data.model_dump(mode='json'), 'material_ids': sorted(set(data.material_ids))})
    case = await db.scalar(select(MedicalCase).where(MedicalCase.id == data.case_id,
        MedicalCase.patient_id == user.id).with_for_update())
    if case is None:
        raise HTTPException(404, '病例不存在')
    existing = await db.get(Consultation, data.request_id, populate_existing=True)
    if existing:
        if existing.patient_id != user.id or existing.request_fingerprint != fingerprint:
            raise HTTPException(409, '提交编号已用于其他咨询内容')
        await expire_unavailable(db, existing)
        await db.commit()
        return result(existing)
    doctor = await db.get(User, data.doctor_id, populate_existing=True, with_for_update=True)
    if not doctor_available(doctor):
        raise HTTPException(409, '该医生当前不可接收咨询，请重新选择')
    active = await db.scalar(select(Consultation).where(Consultation.case_id == case.id, Consultation.state.in_(ACTIVE_STATES)))
    if active:
        await expire_unavailable(db, active)
        if active.state in ACTIVE_STATES:
            raise HTTPException(409, '本病例已有进行中的咨询，请查看或取消后再提交')
    source = await preview(db, user, case.id)
    if source['source_fingerprint'] != data.source_fingerprint:
        raise HTTPException(409, '病例资料已有变化，请重新核对共享范围')
    available = {material['file_id']: material for material in source['materials']}
    if any(file_id not in available for file_id in data.material_ids):
        raise HTTPException(404, '所选资料不属于本病例或尚未完成解析')
    snapshot = {key: value for key, value in source.items() if key not in ('materials', 'source_fingerprint')}
    snapshot['materials'] = [available[file_id] for file_id in sorted(set(data.material_ids))]
    item = Consultation(id=data.request_id, case_id=case.id, patient_id=user.id, doctor_id=doctor.id,
        doctor_profile=profile(doctor), question=data.question, snapshot=snapshot, request_fingerprint=fingerprint,
        state='pending', revision=1)
    db.add(item)
    notify(db, item, user, '收到新的患者咨询')
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, '本病例已有咨询或提交编号已被使用，请刷新确认')
    return result(item)


@router.get('/notifications')
async def notifications(user: CurrentUser, db: AsyncSession = Depends(get_db), limit: int = Query(20, ge=1, le=50)):
    permit(user)
    rows = (await db.scalars(select(Notification).where(Notification.recipient_id == user.id,
        Notification.recipient_deleted.is_(False), Notification.action_url.like('%?consultation_id=%')).order_by(
        Notification.created_at.desc(), Notification.id.desc()).limit(limit))).all()
    return [{'id': str(row.id), 'subject': row.subject, 'action_url': row.action_url,
        'is_read': row.is_read, 'created_at': row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at} for row in rows]


@router.post('/notifications/{notification_id}/read')
async def read_notification(notification_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    permit(user)
    row = await db.scalar(select(Notification).where(Notification.id == notification_id,
        Notification.recipient_id == user.id, Notification.action_url.like('%?consultation_id=%')).with_for_update())
    if row is None:
        raise HTTPException(404, '消息不存在')
    row.is_read, row.read_at = True, now()
    await db.commit()
    return {'id': str(row.id), 'is_read': True}


@router.get('')
async def list_consultations(user: CurrentUser, db: AsyncSession = Depends(get_db), case_id: UUID | None = None,
                             page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=50)):
    permit(user)
    owner = Consultation.patient_id == user.id if user.role == UserRole.PATIENT else Consultation.doctor_id == user.id
    query = select(Consultation).where(owner)
    if case_id:
        query = query.where(Consultation.case_id == case_id)
    rows = (await db.scalars(query.order_by(Consultation.updated_at.desc(), Consultation.id.desc())
                            .offset((page-1)*limit).limit(limit+1).with_for_update())).all()
    if user.role == UserRole.PATIENT:
        for item in rows:
            await expire_unavailable(db, item)
        await db.commit()
    return {'items': [{**result(item), 'doctor': item.doctor_profile,
        'case_title': item.snapshot.get('case_title') if user.role == UserRole.PATIENT or item.state in ACTIVE_STATES else '咨询已结束',
        'question': item.question if user.role == UserRole.PATIENT or item.state in ACTIVE_STATES else '',
        'created_at': item.created_at, 'updated_at': item.updated_at} for item in rows[:limit]], 'has_more': len(rows) > limit}


@router.get('/{consultation_id}')
async def get_consultation(consultation_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    item = await owned_consultation(db, user, consultation_id)
    if user.role == UserRole.DOCTOR and item.state not in ACTIVE_STATES:
        raise HTTPException(403, '本次咨询已结束，共享授权已停止')
    messages = (await db.scalars(select(ConsultationMessage).where(ConsultationMessage.consultation_id == item.id)
        .order_by(ConsultationMessage.created_at, ConsultationMessage.id))).all()
    await db.commit()
    return {**result(item), 'doctor': item.doctor_profile, 'question': item.question, 'snapshot': item.snapshot,
        'created_at': item.created_at, 'updated_at': item.updated_at, 'messages': [
            {'id': str(message.id), 'author': message.author_profile, 'kind': message.kind,
             'body': message.body, 'category': message.category, 'created_at': message.created_at} for message in messages]}


async def previous_message(db, item, user, request_id, kind, body, category, next_state):
    existing = await db.get(ConsultationMessage, request_id)
    if existing:
        if (existing.consultation_id, existing.author_id, existing.kind, existing.body, existing.category, existing.next_state) != (item.id, user.id, kind, body, category, next_state):
            raise HTTPException(409, '提交编号已用于其他内容')
        return True
    return False


def check_revision(item, expected):
    if item.revision != expected:
        raise HTTPException(409, '咨询状态已变化，请刷新后重试；未发送内容仍保留')


async def publish(db, item, user, request_id, kind, body, category, next_state):
    db.add(ConsultationMessage(id=request_id, consultation_id=item.id, author_id=user.id, author_profile=profile(user),
        kind=kind, body=body, category=category, next_state=next_state))
    item.state, item.revision, item.updated_at = next_state, item.revision + 1, now()
    notify(db, item, user, '咨询有新的回复' if kind == 'message' else '咨询状态已更新')
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, '提交结果发生冲突，请刷新确认')
    return result(item)


@router.post('/{consultation_id}/actions')
async def consultation_action(consultation_id: UUID, data: ConsultationAction, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    item = await owned_consultation(db, user, consultation_id)
    states = {'accept': 'accepted', 'decline': 'declined', 'cancel': 'cancelled', 'end': 'completed'}
    next_state = states[data.action]
    body = data.reason.strip()
    if await previous_message(db, item, user, data.request_id, data.action, body, None, next_state):
        await db.commit()
        return result(item)
    check_revision(item, data.expected_revision)
    if item.state not in ACTIVE_STATES:
        raise HTTPException(409, '咨询已结束，无法执行此操作')
    if data.action in ('accept', 'decline') and (user.role != UserRole.DOCTOR or item.state != 'pending'):
        raise HTTPException(409, '仅指定医生可接受或婉拒待接诊咨询')
    if data.action == 'decline' and not body:
        raise HTTPException(422, '请填写婉拒原因')
    if data.action == 'cancel' and user.role != UserRole.PATIENT:
        raise HTTPException(403, '仅患者可取消授权')
    if data.action == 'end' and item.state == 'pending':
        raise HTTPException(409, '待接诊咨询应先接受或取消')
    return await publish(db, item, user, data.request_id, data.action, body, None, next_state)


@router.post('/{consultation_id}/messages')
async def consultation_message(consultation_id: UUID, data: ConsultationReply, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    item = await owned_consultation(db, user, consultation_id)
    is_doctor = user.role == UserRole.DOCTOR
    if is_doctor and (data.category is None or data.next_state is None):
        raise HTTPException(422, '请选择建议类别及下一等待状态')
    if not is_doctor and (data.category is not None or data.next_state is not None):
        raise HTTPException(422, '患者留言不允许指定医生回复状态')
    next_state = data.next_state if is_doctor else 'accepted'
    if await previous_message(db, item, user, data.request_id, 'message', data.body, data.category, next_state):
        await db.commit()
        return result(item)
    check_revision(item, data.expected_revision)
    if item.state not in ('accepted', 'awaiting_patient'):
        raise HTTPException(409, '请等待医生接受，或重新发起已结束的咨询')
    return await publish(db, item, user, data.request_id, 'message', data.body, data.category, next_state)
