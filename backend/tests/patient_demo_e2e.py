"""使用真实本地 API/数据库的患者闭环验收；仅 LLM 生成由 demo server 替代。"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.session import async_session_maker
from app.models.agent import AgentSession
from app.models.case_preparation import CasePreparationPackage
from app.models.medical_case import MedicalCase
from app.models.post_visit_feedback import PatientPostVisitFeedback
from tests.database_safety import (
    repository_migration_head,
    resolve_demo_redis_mode,
    validate_demo_environment,
)

API = os.getenv("DEMO_API_URL", "http://127.0.0.1:8012/api/v1")
WEB = os.getenv("DEMO_WEB_URL", "http://127.0.0.1:3002")
PASSWORD = "Synthetic-Demo-2026!"


def api_request(path: str, *, method: str = "GET", body=None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else None


def login_token(email: str) -> str:
    data = urlencode({"username": email, "password": PASSWORD}).encode()
    request = Request(f"{API}/auth/login", data=data, method="POST")
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read())["access_token"]


async def database_evidence(
    patient_id: str,
    case_id: str,
    feedback_id: str,
    expected_migration_head: str,
) -> dict:
    """Read the actual migration and ownership links behind the API result."""
    async with async_session_maker() as db:
        migration_head = await db.scalar(text("SELECT version_num FROM alembic_version"))
        assert migration_head == expected_migration_head, (
            f"database migration head {migration_head!r} does not match "
            f"repository head {expected_migration_head!r}"
        )
        case = await db.get(MedicalCase, uuid.UUID(case_id))
        assert case is not None, "E2E case is missing from PostgreSQL"
        assert str(case.patient_id) == patient_id, "case owner does not match registered patient"
        assert case.source_session_id is not None, "case has no source AgentSession"

        source_session = await db.get(AgentSession, case.source_session_id)
        assert source_session is not None, "case source session is missing"
        assert source_session.user_id == case.patient_id, "source session belongs to another patient"
        assert source_session.structured_output, "source session has no structured report"

        preparation = await db.scalar(
            select(CasePreparationPackage)
            .where(CasePreparationPackage.case_id == case.id)
            .order_by(CasePreparationPackage.version.desc())
            .limit(1)
        )
        assert preparation is not None, "case has no persisted preparation package"

        feedback = await db.get(PatientPostVisitFeedback, uuid.UUID(feedback_id))
        assert feedback is not None, "patient feedback is missing from PostgreSQL"
        assert feedback.case_id == case.id, "patient feedback belongs to another case"

        return {
            "migration_head": migration_head,
            "expected_migration_head": expected_migration_head,
            "patient_id": str(case.patient_id),
            "case_id": str(case.id),
            "source_session_id": str(source_session.id),
            "preparation_id": str(preparation.id),
            "preparation_version": preparation.version,
            "preparation_revision": preparation.revision,
            "feedback_id": str(feedback.id),
            "feedback_case_id": str(feedback.case_id),
            "feedback_version": feedback.version,
            "feedback_revision": feedback.revision,
        }


def main() -> None:
    redis_mode = resolve_demo_redis_mode(
        os.environ, str(get_settings().redis_url)
    )
    target = validate_demo_environment(
        str(get_settings().database_url), API, WEB
    )
    expected_head = repository_migration_head(
        Path(__file__).resolve().parents[1] / "alembic.ini"
    )
    print(
        "Synthetic E2E target: "
        f"postgresql / {target.host} / {target.database}; "
        f"deterministic LLM substitute and Redis lock mode={redis_mode}"
    )
    suffix = uuid.uuid4().hex[:12]
    email = f"patient-demo-{suffix}@example.com"
    status, registration = api_request("/auth/register", method="POST", body={
        "email": email,
        "password": PASSWORD,
        "role": "patient",
        "full_name": f"合成演示患者 {suffix}",
        "province": "合成演示",
    })
    assert status == 201, registration

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True
        )
        try:
            context = browser.new_context(
                viewport={"width": 1365, "height": 980},
                permissions=["clipboard-read", "clipboard-write"],
            )
            page = context.new_page()

            page.goto(f"{WEB}/login", wait_until="domcontentloaded")
            page.locator("#email-input").fill(email)
            page.locator("#password-input").fill(PASSWORD)
            page.get_by_role("button", name="登录", exact=True).click()
            expect(page).to_have_url(f"{WEB}/chat", timeout=20_000)

            field = page.get_by_placeholder("描述您的症状，或补充检查报告…")
            field.fill("合成演示主诉：测试病例恢复闭环")
            field.press("Enter")
            expect(page.get_by_text("这次不适大约持续了多久？（合成演示问题）", exact=True)).to_be_visible(timeout=20_000)
            page.get_by_role("button", name="今天开始", exact=True).click()
            expect(page.get_by_text("合成演示报告（不是医学判断）", exact=True).last).to_be_visible(timeout=30_000)
            expect(page.get_by_role("button", name="查看问诊记录", exact=True)).to_be_visible()
            page.get_by_role("button", name="查看问诊记录", exact=True).click()

            page.wait_for_url("**/cases?case_id=*")
            case_id = page.url.split("case_id=", 1)[1]
            expect(page.get_by_text("合成演示报告（不是医学判断）", exact=True).last).to_be_visible(timeout=20_000)
            page.get_by_role('button', name='准备去就诊', exact=True).click()

            page.get_by_role("button", name="整理就诊摘要", exact=True).click()
            page.get_by_role("button", name="查看完整摘要", exact=True).click()
            preview = page.get_by_label("就诊摘要预览")
            expect(preview).to_be_visible(timeout=20_000)
            preview_value = preview.input_value()
            assert "患者陈述" in preview_value and "患者核对不等于医生确认" in preview_value
            page.get_by_role("button", name="核对或修改病情", exact=True).click()
            confirmation = page.get_by_label("我确认这项患者陈述准确").first
            if confirmation.count():
                confirmation.check()
            page.get_by_role("button", name="保存准备内容", exact=True).click()
            expect(page.get_by_text("已保存确认内容。", exact=True)).to_be_visible(timeout=20_000)
            page.get_by_role("button", name="复制摘要", exact=True).click()
            expect(page.get_by_text("已复制已保存的摘要到剪贴板。", exact=True)).to_be_visible()
            copied = page.evaluate("navigator.clipboard.readText()")
            assert "患者陈述" in copied and "患者核对不等于医生确认" in copied

            page.get_by_role("button", name="记录就诊结果", exact=True).click()
            page.get_by_label("就诊时间").fill("2026-09-26T18:00")
            page.get_by_label("就诊科室").fill("合成演示科室（患者自述）")
            page.get_by_label("就诊情况").fill("合成演示：已完成一次模拟就诊记录。")
            page.get_by_label("需要复查的事项（每行一条）").fill("合成演示复查事项")
            page.get_by_role("button", name="保存就诊结果", exact=True).click()
            expect(page.get_by_text("就诊结果已保存为患者自述。", exact=True)).to_be_visible(timeout=20_000)

            list_status, case_list = api_request("/patient/cases", token=login_token(email))
            assert list_status == 200 and len(case_list) == 1, case_list
            assert case_list[0]["id"] == case_id
            _, recovery = api_request(f"/patient/cases/{case_id}/recovery", token=login_token(email))
            assert recovery["case"]["id"] == case_id
            assert recovery["report"]["primary_diagnosis"] == "合成演示报告（不是医学判断）"
            _, prep = api_request(f"/patient/cases/{case_id}/preparation", token=login_token(email))
            assert prep["package"] and prep["package"]["case_id"] == case_id
            _, feedback = api_request(f"/patient/cases/{case_id}/post-visit-feedback", token=login_token(email))
            feedback_item = feedback["feedback"]
            assert feedback_item and feedback_item["case_id"] == case_id
            assert feedback_item["source_type"] == "patient_reported"
            assert feedback_item["actual_department"] == "合成演示科室（患者自述）"
            patient_id = api_request("/auth/me", token=login_token(email))[1]["id"]
            database = asyncio.run(
                database_evidence(
                    patient_id,
                    case_id,
                    feedback_item["feedback_id"],
                    expected_head,
                )
            )
            assert database["patient_id"] == patient_id
            assert database["case_id"] == case_id
            assert database["feedback_case_id"] == case_id

            # 清除全部浏览器状态后重新登录，再通过服务器恢复同一病例。
            page.evaluate("localStorage.clear(); sessionStorage.clear()")
            page.goto(f"{WEB}/login", wait_until="domcontentloaded")
            page.locator("#email-input").fill(email)
            page.locator("#password-input").fill(PASSWORD)
            page.get_by_role("button", name="登录", exact=True).click()
            expect(page).to_have_url(f"{WEB}/chat", timeout=20_000)
            page.goto(f"{WEB}/cases", wait_until="domcontentloaded")
            expect(page.get_by_text("合成演示报告（不是医学判断）", exact=True).last).to_be_visible(timeout=20_000)
            page.get_by_role("button", name="记录就诊结果", exact=True).click()
            expect(page.get_by_label("就诊科室")).to_have_value("合成演示科室（患者自述）")
            expect(page.get_by_label("需要复查的事项（每行一条）")).to_have_value("合成演示复查事项")

            # 独立第二位合成患者不得读取第一位患者的病例。
            other_email = f"patient-demo-other-{uuid.uuid4().hex[:12]}@example.com"
            other_status, other_registration = api_request("/auth/register", method="POST", body={
                "email": other_email,
                "password": PASSWORD,
                "role": "patient",
                "full_name": "合成隔离验证患者",
                "province": "合成演示",
            })
            assert other_status == 201, other_registration
            other_token = login_token(other_email)
            foreign_status, _ = api_request(f"/patient/cases/{case_id}/recovery", token=other_token)
            assert foreign_status == 404, foreign_status

            result = {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "mode": f"synthetic_llm_substitute_with_{redis_mode}_redis_and_real_auth_api_postgresql",
                **database,
                "case_count": len(case_list),
                "foreign_recovery_status": foreign_status,
                "report_source": "deterministic test substitute; not a clinical report",
                "completed_steps": [
                    "new registered synthetic patient",
                    "initial question and one follow-up answer",
                    "structured report and single case persistence",
                    "report action opens same case by case_id",
                    "preparation snapshot, patient confirmation, preview and clipboard copy",
                    "patient-reported visit feedback save",
                    "clear local browser storage, re-login and restore from server",
                    "foreign patient recovery rejected",
                ],
            }
            evidence_dir = Path(__file__).resolve().parents[2] / ".ai/tasks/patient-closure-evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            evidence_path = evidence_dir / f"demo-e2e-result-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{suffix}.json"
            evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False))
            print(f"EVIDENCE={evidence_path}")
            context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
