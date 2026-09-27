"""尚未实现的医生操作必须显式失败，不返回模拟成功。"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.agent import AgentTask
from app.models.medical_case import MedicalCase
from app.models.user import User, UserRole, UserStatus


@pytest.mark.asyncio
async def test_plan_instruction_returns_not_implemented_without_creating_tasks(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    doctor = User(
        email=f"unimplemented-doctor-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name="Assigned Doctor",
        role=UserRole.DOCTOR,
        status=UserStatus.ACTIVE,
    )
    patient = User(
        email=f"unimplemented-patient-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name="Patient",
        role=UserRole.PATIENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([doctor, patient])
    await db_session.flush()
    case = MedicalCase(
        patient_id=patient.id,
        assigned_doctor_id=doctor.id,
        title="Test case",
        description="Synthetic test case",
    )
    db_session.add(case)
    await db_session.commit()
    before = await db_session.scalar(select(func.count()).select_from(AgentTask))

    response = await client.post(
        f"/api/v1/doctor/cases/{case.id}/plan",
        json={"instruction": "安排复查"},
        headers={
            "Authorization": f"Bearer {create_access_token(str(doctor.id), platform='web')}"
        },
    )

    after = await db_session.scalar(select(func.count()).select_from(AgentTask))
    assert response.status_code == 501
    assert after == before
