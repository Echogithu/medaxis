"""为注册患者的诊断会话建立可恢复的病例记录。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSession
from app.models.document_parse import DocumentParseTask
from app.models.medical_case import CaseStatus, MedicalCase

logger = logging.getLogger(__name__)


class DiagnosisCasePersistenceError(RuntimeError):
    """诊断报告无法安全绑定到患者病例时抛出。"""


async def persist_diagnosis_case(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    source_session_id: uuid.UUID,
    report: dict[str, Any],
    fallback_chief_complaint: str,
) -> MedicalCase:
    """幂等保存诊断病例，并把该会话的注册患者材料绑定到病例。

    锁定来源会话作为同一诊断的串行化点，因此无需给既有 schema 增加唯一约束。
    """
    try:
        session = await db.scalar(
            select(AgentSession)
            .where(AgentSession.id == source_session_id)
            .with_for_update()
        )
        if session is None or session.user_id != patient_id:
            raise DiagnosisCasePersistenceError("诊断会话归属与当前患者不匹配")

        case = await db.scalar(
            select(MedicalCase).where(MedicalCase.source_session_id == source_session_id)
        )
        if case is not None and case.patient_id != patient_id:
            raise DiagnosisCasePersistenceError("来源会话病例归属与当前患者不匹配")

        interview = (session.context or {}).get("interview") or {}
        chief_complaint = (
            interview.get("chief_complaint")
            or (session.context or {}).get("chief_complaint")
            or fallback_chief_complaint
        )
        primary_diagnosis = str(report.get("primary_diagnosis") or "辅助诊断报告")
        severity = str(report.get("severity") or "unknown")

        if case is None:
            case = MedicalCase(
                patient_id=patient_id,
                source_session_id=source_session_id,
                title=f"AI Diagnosis: {primary_diagnosis[:50]}",
                chief_complaint=chief_complaint,
                ai_diagnosis_summary=primary_diagnosis[:500],
                severity=severity[:20],
                is_emergency=severity == "emergency",
                status=CaseStatus.PENDING_REVIEW,
            )
            db.add(case)
            await db.flush()

        materials = (
            await db.scalars(
                select(DocumentParseTask)
                .where(
                    DocumentParseTask.owner_user_id == patient_id,
                    DocumentParseTask.source_session_id == source_session_id,
                )
                .with_for_update()
            )
        ).all()
        for material in materials:
            if material.case_id not in (None, case.id):
                raise DiagnosisCasePersistenceError("患者材料已绑定到其他病例，拒绝覆盖")
            material.case_id = case.id

        await db.commit()
        await db.refresh(case)
        return case
    except DiagnosisCasePersistenceError:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception(
            "Failed to persist diagnosis case for source session %s", source_session_id
        )
        raise DiagnosisCasePersistenceError("病例保存失败，请重试后从病例列表确认") from exc
