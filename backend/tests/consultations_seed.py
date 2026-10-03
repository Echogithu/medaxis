"""只在命名隔离演示库写入合成双角色种子，不使用真实账号。"""
from uuid import uuid4
from tests.database_safety import validate_demo_database


async def seed(database_url):
    validate_demo_database(database_url)
    from app.core.security import create_access_token
    from app.db.session import async_session_maker, async_engine
    from app.models.user import User, UserRole, UserStatus
    from app.models.medical_case import MedicalCase
    from app.models.document_parse import DocumentParseTask
    async with async_session_maker() as db:
        patient = User(email=f'{uuid4()}@example.com', full_name='浏览器合成患者', role=UserRole.PATIENT,
                       status=UserStatus.ACTIVE, hashed_password='unused', age_years=30)
        doctor = User(email=f'{uuid4()}@example.com', full_name='认证合成医生', role=UserRole.DOCTOR,
                      status=UserStatus.ACTIVE, is_verified=True, hashed_password='unused', hospital='合成医院', department='全科')
        other = User(email=f'{uuid4()}@example.com', full_name='另一位合成医生', role=UserRole.DOCTOR,
                     status=UserStatus.ACTIVE, is_verified=True, hashed_password='unused')
        db.add_all([patient, doctor, other]); await db.flush()
        case = MedicalCase(patient_id=patient.id, title='浏览器合成问诊', chief_complaint='合成患者主诉', ai_diagnosis_summary='合成 AI 原始摘要')
        db.add(case); await db.flush()
        for name in ['共享的合成报告.png', '不共享的合成报告.png']:
            db.add(DocumentParseTask(file_id=uuid4().hex, filename=name, parse_method='image', status='completed',
                file_bytes=b'only synthetic', owner_user_id=patient.id, case_id=case.id,
                result={'indicators': [], 'overall_confidence': 1, 'requires_manual_review': False}))
        await db.commit()
        result = {'CONSULTATION_PATIENT_TOKEN': create_access_token(str(patient.id), platform='web'),
                  'CONSULTATION_DOCTOR_TOKEN': create_access_token(str(doctor.id), platform='web'),
                  'CONSULTATION_OTHER_TOKEN': create_access_token(str(other.id), platform='web'),
                  'CONSULTATION_CASE_ID': str(case.id)}
    await async_engine.dispose()
    return result
