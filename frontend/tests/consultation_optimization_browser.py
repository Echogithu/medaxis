"""合成报告/API：统一排序、稳定编号、阶段摘要和补充追问；不读写真实患者数据。"""
import os
from copy import deepcopy
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, MockAPI, REPORT, token
from report_reading_browser import seed_report


def main():
    saved = seed_report()
    REPORT.update(interview_is_sufficient=False, interview_stop_reason="budget_reached",
                  interview_information_gaps=["用药情况：患者尚未确认"],
                  knowledge_evidence=[{"claim_path": "recommended_actions.0", "citation_id": "S1",
                                       "claim": "合成建议：与医生讨论", "quote": "", "status": "needs_review",
                                       "reason": "合成原文尚不能支持这项建议"}])
    for index, citation in enumerate(REPORT["knowledge_citations"][:5]):
        citation.update(relevance=[.2, .9, .5, .7, None][index],
                        relevance_method="keyword" if index < 4 else "unassessed",
                        relevance_query_fingerprint="synthetic-same-query",
                        relevance_reason="合成匹配理由；词匹配不等于语义支持" if index < 4 else "跨语言待核对")
    api = MockAPI()
    artifacts = Path(os.environ["REPORT_SCREENSHOT_DIR"])
    artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.route("**/api/v1/**", api.route)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.evaluate("""([jwt, saved]) => {
                localStorage.setItem('access_token', jwt);
                localStorage.setItem('user_role', 'patient');
                localStorage.setItem('medaxis.chat-history.v1:user:reading-test', JSON.stringify(saved));
            }""", [token("reading-test"), saved])
            page.goto(f"{BASE}/chat")
            for width in [1440, 390, 320]:
                page.set_viewport_size({"width": width, "height": 1000})
                page.get_by_role("button", name="查看问诊总结", exact=True).last.click()
                dialog = page.get_by_role("dialog", name="这次问诊总结")
                expect(dialog.get_by_text("用药情况：患者尚未确认", exact=True)).to_be_visible()
                # 等待弹窗淡入结束，避免截图把正常入场动画误呈现为半透明报告。
                page.wait_for_function("""() => {
                    const dialog = document.querySelector('[role="dialog"][aria-labelledby="patient-report-title"]');
                    if (!dialog) return false;
                    for (let node = dialog; node; node = node.parentElement) {
                        if (Number(getComputedStyle(node).opacity) < 0.99) return false;
                    }
                    return true;
                }""")
                page.screenshot(path=str(artifacts / f"consultation-stage-{width}.png"))
                dialog.get_by_role("link", name="引用 S1，查看来源").click()
                expect(dialog.get_by_role("article", name="参考资料 S1", exact=True)).to_be_focused()
                cards = dialog.locator('article[aria-label^="参考资料 S"]')
                assert cards.evaluate_all("els => els.filter(el => el.getBoundingClientRect().height).map(el => el.getAttribute('aria-label'))") == [
                    "参考资料 S2", "参考资料 S4", "参考资料 S3", "参考资料 S1", "参考资料 S5"]
                card1 = dialog.get_by_role("article", name="参考资料 S1", exact=True)
                expect(card1.get_by_text("主题词匹配", exact=True)).to_be_visible()
                expect(card1.get_by_text("对应报告陈述：合成建议：与医生讨论", exact=True)).to_be_visible()
                card1.get_by_role("button", name="查看 S1 原文片段").click()
                expect(card1.get_by_text("核对说明：合成原文尚不能支持这项建议", exact=True)).to_be_visible()
                expect(dialog.get_by_role("article", name="参考资料 S5").get_by_text("相关性待核对", exact=True)).to_be_visible()
                body = dialog.get_by_role("region", name="问诊总结正文")
                assert body.evaluate("el => el.scrollWidth <= el.clientWidth"), width
                page.screenshot(path=str(artifacts / f"consultation-sources-{width}.png"))
                dialog.get_by_role("button", name="补充情况，继续问", exact=True).click()
                expect(dialog).not_to_be_visible()
                expect(page.locator("textarea:visible")).to_be_focused()
            page.locator("textarea:visible").fill("合成补充信息：用药情况仍待确认")
            page.locator("textarea:visible").press("Enter")
            expect(page.get_by_text("历史上下文续聊成功", exact=True)).to_be_visible()
            assert any(path.endswith("/chat") for path, *_ in api.requests)
            assert not any(path.endswith("/route/stream") for path, *_ in api.requests)
            page.get_by_role("button", name="查看问诊总结", exact=True).last.click()
            expect(page.get_by_role("dialog").get_by_text("用药情况：患者尚未确认", exact=True)).to_be_visible()
            page.get_by_role("button", name="关闭问诊总结", exact=True).click()
            legacy = deepcopy(saved)
            legacy_report = legacy["sessions"][0]["reportData"]
            original_sources = deepcopy(legacy_report["knowledge_citations"])
            legacy_report.update(knowledge_citations=[], knowledge_sources=[], knowledge_retrieval_count=5,
                                 knowledge_retrieval_status="retrieved_not_cited", primary_diagnosis="合成历史总结",
                                 recommended_actions=["合成建议：与医生讨论"], knowledge_evidence=[],
                                 interview_information_gaps=["adv_stool_pattern", "adv_epidemic", "adv_unfamiliar_key"])
            legacy["sessions"][0]["messages"][-1]["workflowSteps"] = [{
                "id": "source-result", "type": "tool_result", "toolName": "search_medical_knowledge",
                "status": "done", "title": "合成检索结果", "timestamp": "2026-10-03T00:00:00Z",
                "toolResult": {"sources": original_sources}}]
            page.evaluate("saved => localStorage.setItem('medaxis.chat-history.v1:user:reading-test', JSON.stringify(saved))", legacy)
            page.reload()
            page.get_by_role("button", name="查看问诊总结", exact=True).last.click()
            dialog = page.get_by_role("dialog", name="这次问诊总结")
            expect(dialog.get_by_text("大便的性状与次数", exact=True)).to_be_visible()
            expect(dialog.get_by_text("近期饮食及接触情况", exact=True)).to_be_visible()
            assert "adv_" not in dialog.inner_text()
            dialog.get_by_text("参考资料", exact=True).click()
            expect(dialog.get_by_role("article", name="参考资料 S2", exact=True)).to_be_visible()
            expect(dialog.get_by_role("article", name="参考资料 S4", exact=True)).to_be_visible()
            assert "但报告正文没有引用它们" not in dialog.inner_text()
            dialog.get_by_role("article", name="参考资料 S2").get_by_role("button", name="查看 S2 原文片段").click()
            expect(dialog.get_by_role("region", name="S2 原文片段")).to_be_visible()
            # 等待展开原文的过渡结束，使验收截图包含完整卡片。
            page.wait_for_timeout(350)
            dialog.get_by_role("article", name="参考资料 S2").scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / "historical-sources-restored-320.png"))
            assert not errors, errors
            print("PASS: 1440/390/320 排序 S2/S4/S3/S1/S5，稳定引用跳转，缺口与理由可见，无溢出")
            print("PASS: 补充入口聚焦输入框，走追问接口，保留原阶段总结；无浏览器异常")
            print("PASS: 零引用历史总结恢复原来源与原文；内部缺口标识不泄露；未引用资料可阅读")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
