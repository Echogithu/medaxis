"""创建专用合成演示资料；重复运行不覆盖数据或重置已用额度。"""
import argparse
import asyncio
import json
from pathlib import Path
import secrets
import subprocess
from uuid import UUID, uuid4, uuid5


def synthetic_pdf():
    lines = ['SYNTHETIC DEMO - NOT A REAL MEDICAL RECORD', 'Patient: Interview Demo (fictional)',
             'Institution: Synthetic Example Center', 'Date: 2026-10-06',
             'WBC: 6.2 x10^9/L   Reference: 3.5-9.5',
             'Hemoglobin: 142 g/L   Reference: 130-175',
             'Platelets: 230 x10^9/L   Reference: 125-350',
             'All values are invented for UI testing. No diagnosis or medical advice.']
    stream = ('BT /F1 12 Tf 45 780 Td ' + ' '.join(
        f'({line}) Tj 0 -28 Td' for line in lines) + ' ET').encode('ascii')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    result = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        result.extend(f'{offset:010d} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(result)


async def prepare(credentials, disable=False):
    from sqlalchemy import select, inspect
    from app.core.security import get_password_hash, verify_password
    from app.db.session import AsyncSessionLocal, async_engine
    from app.models.user import User, UserRole, UserStatus
    from app.models.agent import PatientHealthProfile
    from app.models.medical_case import MedicalCase, CaseStatus
    from app.models.config import SystemSetting
    from app.models.document_parse import DocumentParseTask
    # 准备过程不输出 SQL 或任何凭据参数。
    async_engine.echo = False
    user_id = UUID(credentials['user_id'])
    async with AsyncSessionLocal() as db:
        enabled = await db.scalar(select(SystemSetting).where(SystemSetting.key == 'interview_demo.enabled'))
        if disable:
            bound = await db.scalar(select(SystemSetting.value).where(SystemSetting.key == 'interview_demo.user_id'))
            if bound != str(user_id):
                raise RuntimeError('恢复凭据与演示账号不匹配，未改变开关')
            if enabled:
                enabled.value = 'false'
            user = await db.get(User, user_id)
            if user and user.email == credentials['email'] and user.full_name == '面试演示患者（合成）':
                user.status = UserStatus.INACTIVE
            await db.commit()
            print(json.dumps({'demo_enabled': False, 'records_preserved': True}))
            return
        user = await db.scalar(select(User).where(User.email == credentials['email']))
        if user and (user.id != user_id or user.role != UserRole.PATIENT
                     or user.full_name != '面试演示患者（合成）'
                     or not verify_password(credentials['password'], user.hashed_password)):
            raise RuntimeError('账号冲突，未覆盖已有用户或密码')
        if user is None:
            user = User(id=user_id, email=credentials['email'],
                hashed_password=get_password_hash(credentials['password']), full_name='面试演示患者（合成）',
                role=UserRole.PATIENT, status=UserStatus.ACTIVE, email_verified=True,
                age_years=30, gender='male', phone=None)
            db.add(user)
            await db.flush()
        else:
            user.status = UserStatus.ACTIVE
        profile = await db.scalar(select(PatientHealthProfile).where(PatientHealthProfile.patient_id == user_id))
        if profile is None:
            db.add(PatientHealthProfile(patient_id=user_id, height=175, weight=70,
                health_summary='合成演示资料，由准备脚本编写，不是真实患者记录或AI诊断。',
                allergies=[], chronic_diseases=[], current_medications=[],
                updated_by_agent='synthetic_demo_seed', record_metadata={'revision': 1,
                    'sections': {name: {'state': 'none', 'source': 'patient_reported'}
                        for name in ('allergies', 'conditions', 'medications')}}))
        case_titles = ['【合成演示】办公后轻微头痛', '【合成演示】体检报告资料整理']
        case_ids = []
        for index, title in enumerate(case_titles):
            case_id = uuid5(user_id, f'interview-case-{index}')
            case_ids.append(str(case_id))
            if await db.get(MedicalCase, case_id) is None:
                db.add(MedicalCase(id=case_id, patient_id=user_id, title=title,
                    chief_complaint='合成情境：连续办公后轻微头痛，想整理问诊要点。' if index == 0 else '合成情境：整理一份虚构血常规报告。',
                    description='此病例由脚本预置，仅用于页面演示；没有医生诊断或预置AI回答。可以另建真实AI问诊，输入合成情境。',
                    status=CaseStatus.IN_PROGRESS))
        report_id = str(uuid5(user_id, 'interview-report-1'))
        if await db.get(DocumentParseTask, report_id) is None:
            content = synthetic_pdf()
            await db.flush()
            db.add(DocumentParseTask(file_id=report_id, filename='【合成演示】synthetic-demo-report.pdf',
                mime_type='application/pdf', file_bytes=content, owner_user_id=user_id,
                case_id=UUID(case_ids[1]), parse_method='manual_archive', status='failed',
                error='此合成原件尚未自动解析，请查看病例附件；非真实医疗记录。'))
        connection = await db.connection()
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        report_ready = {'patient_reports', 'patient_report_files', 'patient_report_jobs',
                        'patient_report_review_versions', 'patient_report_case_links'}.issubset(tables)
        defaults = {'enabled': 'true', 'user_id': str(user_id), 'limit': '20', 'used': '0',
                    'report_center_ready': str(report_ready).lower()}
        for key, value in defaults.items():
            row = await db.scalar(select(SystemSetting).where(SystemSetting.key == 'interview_demo.' + key))
            if row is None:
                db.add(SystemSetting(key='interview_demo.' + key, value=value,
                    description='面试演示保护；不自动补充额度', category='interview_demo', value_type='string'))
            elif key == 'user_id' and row.value != value:
                raise RuntimeError('演示模式已绑定其他账号，未覆盖配置')
            elif key == 'report_center_ready':
                row.value = value
        if enabled:
            enabled.value = 'true'
        await db.commit()
        print(json.dumps({'user_id': str(user_id), 'role': 'patient', 'case_ids': case_ids,
                          'material_file_id': report_id, 'synthetic': True, 'quota_not_reset': True,
                          'report_center_ready': report_ready}))
    await async_engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', required=True)
    parser.add_argument('--generate-credentials', action='store_true')
    parser.add_argument('--disable', action='store_true')
    args = parser.parse_args()
    file = Path(args.credentials)
    if args.generate_credentials:
        ignored = subprocess.run(['git', 'check-ignore', '--quiet', str(file.resolve())],
            cwd=Path(__file__).resolve().parent.parent, capture_output=True)
        if ignored.returncode != 0:
            raise RuntimeError('凭据路径必须被 Git 忽略，未生成密码文件')
        if not file.exists():
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open('x', encoding='utf-8') as handle:
                json.dump({'user_id': str(uuid4()), 'email': 'interview-demo@medaxis.example.com',
                           'password': secrets.token_urlsafe(24)}, handle, ensure_ascii=False, indent=2)
        (file.parent / 'synthetic-demo-report.pdf').write_bytes(synthetic_pdf())
        print('演示凭据已保存到本地文件；未输出密码，未写入源码。')
    else:
        asyncio.run(prepare(json.loads(file.read_text(encoding='utf-8')), args.disable))
