"""恢复脚本用隔离会话验证，不切换运行中的演示或访问真实资料。"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from app.models.user import UserStatus

spec = importlib.util.spec_from_file_location('demo_seed', Path(__file__).resolve().parents[2] / 'scripts' / 'prepare_interview_demo.py')
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)
USER = 'd59b206e-81d2-448a-bbfd-57dd095fa276'


@pytest.mark.asyncio
@pytest.mark.parametrize('matches', [True, False])
async def test_disable_checks_binding_and_preserves_records(monkeypatch, matches):
    from app.db import session
    enabled = SimpleNamespace(value='true')
    user = SimpleNamespace(email='interview-demo@medaxis.example.com', full_name='面试演示患者（合成）', status=UserStatus.ACTIVE)
    db = AsyncMock()
    db.__aenter__.return_value = db
    db.scalar.side_effect = [enabled, USER if matches else str(UUID(int=1))]
    db.get.return_value = user
    monkeypatch.setattr(session, 'AsyncSessionLocal', lambda: db)
    credentials = {'user_id': USER, 'email': user.email}
    if matches:
        await seed.prepare(credentials, disable=True)
        assert 'false' == enabled.value
        assert UserStatus.INACTIVE == user.status
        db.commit.assert_awaited_once()
    else:
        with pytest.raises(RuntimeError, match='恢复凭据与演示账号不匹配'):
            await seed.prepare(credentials, disable=True)
        assert 'true' == enabled.value
        assert UserStatus.ACTIVE == user.status
        db.commit.assert_not_awaited()
    db.delete.assert_not_awaited()


def test_synthetic_pdf_is_explicit_and_has_correct_cross_reference():
    content = seed.synthetic_pdf()
    assert content.startswith(b'%PDF-1.4')
    assert b'SYNTHETIC DEMO - NOT A REAL MEDICAL RECORD' in content
    offset = int(content.split(b'startxref\n')[1].split(b'\n')[0])
    assert content[offset:].startswith(b'xref\n')
