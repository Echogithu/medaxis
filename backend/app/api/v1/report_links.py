"""患者本人报告与病例之间的引用，独立于医生材料和AI输入。"""
from typing import Annotated, Any
from uuid import UUID
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.v1.care_plans import require_patient
from app.api.v1.report_workflow import validate
from app.db.session import get_db
from app.models.medical_case import MedicalCase
from app.models.patient_report import PatientReport, PatientReportFile, ReportCaseLink, ReportReviewVersion
from app.schemas.report_links import SaveReportLinks
from app.services import report_links as service

router = APIRouter()


async def owned(db, user, report_id, *, lock=False):
    from app.api.v1.patient_reports import owned_report
    require_patient(user)
    return await owned_report(db, user.id, report_id, lock=lock)


@router.get('/reports/{report_id}/case-links')
async def get_links(report_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await service.workspace(db, await owned(db, user, report_id))


@router.post('/reports/{report_id}/case-links')
async def save_links(report_id: UUID, user: CurrentUser, body: Any = Body(...), db: AsyncSession = Depends(get_db)):
    report = await owned(db, user, report_id, lock=True)
    operation = await service.save(db, report, validate(SaveReportLinks, body))
    result = {'operation': {'id': operation.id, 'request_id': operation.request_id, 'revision': operation.revision},
        'workspace': await service.workspace(db, report)}
    await db.commit()
    return result


@router.get('/reports/{report_id}/case-options')
async def case_options(report_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db),
                       search: Annotated[str, Query(max_length=200)] = '',
                       page: Annotated[int, Query(ge=1, le=100000)] = 1,
                       limit: Annotated[int, Query(ge=1, le=50)] = 10):
    await owned(db, user, report_id)
    filters = [MedicalCase.patient_id == user.id]
    if search.strip():
        filters.append(MedicalCase.title.contains(search.strip(), autoescape=True))
    total = await db.scalar(select(func.count()).select_from(MedicalCase).where(*filters))
    rows = (await db.execute(select(MedicalCase.id, MedicalCase.title, MedicalCase.status, MedicalCase.created_at)
        .where(*filters).order_by(MedicalCase.created_at.desc(), MedicalCase.id.desc()).offset((page-1)*limit).limit(limit))).all()
    return {'items': [dict(row._mapping) for row in rows], 'total': total, 'page': page, 'limit': limit}


@router.get('/cases/{case_id}/reports')
async def case_reports(case_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db),
                       page: Annotated[int, Query(ge=1, le=100000)] = 1,
                       limit: Annotated[int, Query(ge=1, le=50)] = 10):
    from app.api.v1.patient_reports import processing_states, serialize
    require_patient(user)
    case = (await db.execute(select(MedicalCase.id, MedicalCase.title).where(
        MedicalCase.id == case_id, MedicalCase.patient_id == user.id))).one_or_none()
    if case is None:
        raise HTTPException(404, '病例不存在或无法访问')
    scope = [ReportCaseLink.case_id == case_id, PatientReport.patient_id == user.id, PatientReport.trashed_at.is_(None)]
    total = await db.scalar(select(func.count()).select_from(ReportCaseLink)
        .join(PatientReport, PatientReport.id == ReportCaseLink.report_id).where(*scope))
    rows = (await db.execute(select(PatientReport, ReportCaseLink).join(ReportCaseLink, ReportCaseLink.report_id == PatientReport.id)
        .where(*scope).order_by(ReportCaseLink.updated_at.desc(), PatientReport.id.desc()).offset((page-1)*limit).limit(limit))).all()
    reports = [report for report, _ in rows]
    files = (await db.scalars(select(PatientReportFile).where(PatientReportFile.report_id.in_([item.id for item in reports]))
        .order_by(PatientReportFile.position))).all() if reports else []
    grouped = {item.id: [] for item in reports}
    for file in files:
        grouped[file.report_id].append(file)
    states = await processing_states(db, reports)
    pins = [link.review_version_id for _, link in rows if link.review_version_id]
    revisions = dict((await db.execute(select(ReportReviewVersion.id, ReportReviewVersion.revision)
        .where(ReportReviewVersion.id.in_(pins)))).all()) if pins else {}
    return {'items': [serialize(report, grouped[report.id], states[report.id]) | {'link': {
        'source_version': link.source_version, 'review_version_id': link.review_version_id,
        'review_revision': revisions.get(link.review_version_id),
        'status': service.link_status(link, report), 'updated_at': link.updated_at}} for report, link in rows],
        'total': total, 'page': page, 'limit': limit}
