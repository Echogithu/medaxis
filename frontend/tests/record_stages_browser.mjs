/** 问诊记录阶段导航回归；仅使用合成 API，不访问病例库。 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:3018';
const output = process.env.REPORT_SCREENSHOT_DIR || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.ai/tasks/2026-09-30-record-stages');
const cases = [
  { id: 'stage-a', chief_complaint: '餐后腹部不适与腹泻', title: '合成 A', status: 'pending_review', created_at: '2026-09-30T02:00:00Z' },
  { id: 'stage-empty', chief_complaint: '暂无总结的合成记录', title: '合成 B', status: 'pending_review' },
  { id: 'stage-failed', chief_complaint: '读取失败的合成记录', title: '合成 C', status: 'pending_review' },
];
const report = { primary_diagnosis: '合成问诊总结，原因待评估', severity: 'moderate', confidence: 'low',
  key_findings: Array.from({ length: 5 }, (_, i) => `合成症状要点 ${i + 1}：持续三天，餐后明显。`),
  recommended_actions: Array.from({ length: 5 }, (_, i) => `合成建议 ${i + 1}：与医生核对情况。`),
  red_flags: ['合成条件警示：如情况恶化，请及时就医。'],
};
let feedback = null;
let saves = 0;
const tokenPayload = Buffer.from(JSON.stringify({ sub: 'synthetic-stage-patient', exp: 9999999999 })).toString('base64url');
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
const checks = [];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript(token => { localStorage.setItem('access_token', token); localStorage.setItem('user_role', 'patient'); }, `header.${tokenPayload}.signature`);
  await context.route('**/api/v1/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    let data = {};
    if (url.pathname.endsWith('/demo/status')) data = { enabled: false, limit: 0, used: 0, remaining: 0, report_center_ready: true };
    else if (url.pathname.endsWith('/auth/me')) data = { id: 'synthetic-stage-patient', role: 'patient' };
    else if (url.pathname.endsWith('/patient/cases')) data = cases;
    else if (url.pathname.startsWith('/api/v1/patient/cases/') && url.pathname.endsWith('/reports')) data = { items: [], total: 0, page: 1, limit: 10 };
    else if (url.pathname.endsWith('/stage-failed/recovery')) return route.fulfill({ status: 500, json: { detail: '合成失败' } });
    else if (url.pathname.endsWith('/recovery')) {
      const current = cases.find(item => url.pathname.includes(`/${item.id}/`));
      data = { case: current, report: current.id === 'stage-a' ? report : null, materials: [], lab_reports: [] };
    } else if (url.pathname.endsWith('/preparation')) data = { package: null, history: [] };
    else if (url.pathname.endsWith('/post-visit-feedback')) {
      if (request.method() === 'POST') {
        saves += 1;
        feedback = { ...request.postDataJSON(), feedback_id: 'synthetic-feedback', case_id: 'stage-a', revision: 1, revision_history: [] };
        data = { feedback, created: true };
      } else data = { feedback: url.pathname.includes('/stage-a/') ? feedback : null, history: [] };
    }
    await route.fulfill({ status: 200, json: data });
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !/^Failed to load resource: the server responded with a status of 500 /.test(message.text())) errors.push(message.text()); });
  const navigation = page.getByRole('navigation', { name: '问诊记录阶段', exact: true });
  const stageButton = title => navigation.getByRole('button', { name: title, exact: true });
  const selected = async title => {
    await navigation.locator(`button[aria-label="${title}"][aria-current="step"]`).waitFor();
    assert.equal(await stageButton(title).getAttribute('aria-current'), 'step');
  };
  await page.goto(`${base}/cases?case_id=stage-a`);
  await page.waitForLoadState('networkidle');
  await stageButton('这次问诊总结').waitFor();
  for (const title of ['这次问诊总结', '准备去就诊', '记录就诊结果']) assert.equal(await stageButton(title).isVisible(), true);
  await selected('这次问诊总结');
  const initialHistoryLength = await page.evaluate(() => history.length);
  await stageButton('这次问诊总结').click();
  assert.equal(await page.evaluate(() => history.length), initialHistoryLength);
  assert.equal(await page.getByText(report.primary_diagnosis, { exact: true }).isVisible(), true);
  assert.equal(await page.getByLabel('就诊时间', { exact: true }).isVisible(), false);
  assert.equal(saves, 0);
  mkdirSync(output, { recursive: true });
  await page.screenshot({ path: path.join(output, 'stages-desktop.png') });
  await page.getByRole('button', { name: '下一步：准备就诊', exact: true }).click();
  await selected('准备去就诊');
  assert.equal(new URL(page.url()).searchParams.get('stage'), 'preparation');
  assert.equal(await page.getByText(report.primary_diagnosis, { exact: true }).isVisible(), false);
  await page.getByRole('button', { name: '整理就诊摘要', exact: true }).waitFor();
  checks.push('三阶段顶部可发现；下一步聚焦准备内容，阶段 URL 同步；当前阶段不重复添加历史');

  await stageButton('记录就诊结果').focus();
  await page.keyboard.press('Enter');
  await selected('记录就诊结果');
  await page.getByLabel('就诊科室', { exact: true }).fill('合成科室');
  await page.getByLabel('就诊情况', { exact: true }).fill('未保存的合成就诊内容');
  await stageButton('这次问诊总结').click();
  await stageButton('记录就诊结果').click();
  assert.equal(await page.getByLabel('就诊情况', { exact: true }).inputValue(), '未保存的合成就诊内容');
  assert.equal(saves, 0);
  await page.goBack();
  await selected('这次问诊总结');
  await page.goForward();
  await selected('记录就诊结果');
  assert.equal(await page.getByLabel('就诊情况', { exact: true }).inputValue(), '未保存的合成就诊内容');
  await page.getByRole('button', { name: '保存就诊结果', exact: true }).click();
  await page.getByText('就诊结果已保存为患者自述。', { exact: true }).waitFor();
  assert.equal(saves, 1);
  await page.reload();
  await page.getByLabel('就诊情况', { exact: true }).waitFor();
  await selected('记录就诊结果');
  assert.equal(await page.getByLabel('就诊情况', { exact: true }).inputValue(), '未保存的合成就诊内容');
  checks.push('键盘切换、后退前进保留表单；刷新恢复阶段和已保存结果；点击阶段不自动保存');

  await page.emulateMedia({ media: 'print' });
  assert.equal(await page.getByText(report.primary_diagnosis, { exact: true }).isVisible(), true);
  assert.equal(await navigation.isVisible(), false);
  assert.equal(await page.getByLabel('就诊情况', { exact: true }).isVisible(), false);
  assert.equal(await page.getByText(report.recommended_actions.at(-1), { exact: true }).isVisible(), true);
  await page.emulateMedia({ media: 'screen' });
  checks.push('任一阶段打印仍呈现完整问诊总结，隐藏导航和编辑表单');

  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${base}/cases?case_id=stage-a`);
    await stageButton('准备去就诊').waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const bounds = await navigation.boundingBox();
    assert.ok(bounds.y >= 0 && bounds.y + bounds.height < 900, `${width}: navigation must be visible initially`);
    for (const title of ['这次问诊总结', '准备去就诊', '记录就诊结果']) assert.equal(await stageButton(title).isVisible(), true);
    if (width === 390) await page.screenshot({ path: path.join(output, 'stages-mobile.png') });
    await page.locator('main').evaluate(element => { element.scrollTop = element.scrollHeight; });
    const sticky = await navigation.boundingBox();
    assert.ok(sticky.y >= 0 && sticky.y + sticky.height < 900, `${width}: sticky navigation`);
  }
  checks.push('320/390/768/1280 无横向溢出；三阶段首屏可见，长总结滚动时导航保留');

  await stageButton('记录就诊结果').click();
  await page.getByRole('list', { name: '问诊记录列表', exact: true }).getByRole('button', { name: /暂无总结的合成记录/ }).click();
  await page.getByText('这次问诊还没有总结。', { exact: true }).waitFor();
  await selected('这次问诊总结');
  assert.equal(new URL(page.url()).searchParams.has('stage'), false);
  assert.equal(await page.getByRole('button', { name: '下一步：准备就诊', exact: true }).isDisabled(), true);
  await stageButton('准备去就诊').click();
  await page.getByRole('alert').filter({ hasText: '暂时无法整理就诊摘要' }).waitFor();
  await stageButton('记录就诊结果').click();
  assert.equal(await page.getByLabel('就诊科室', { exact: true }).inputValue(), '');
  await page.getByRole('list', { name: '问诊记录列表', exact: true }).getByRole('button', { name: /读取失败的合成记录/ }).click();
  await page.getByRole('alert').filter({ hasText: '这条问诊记录暂时无法读取' }).waitFor();
  assert.equal(await navigation.count(), 0);
  assert.equal(await page.getByLabel('就诊科室', { exact: true }).count(), 0);
  assert.deepEqual(errors, []);
  checks.push('换病例重置阶段且隔离表单；无报告有明确空状态；加载失败不残留旧内容');
  writeFileSync(path.join(output, 'browser-result.json'), JSON.stringify({ scope: 'synthetic mocked API; native Edge headless', checks }, null, 2));
  for (const check of checks) console.log(`PASS: ${check}`);
} finally { await browser.close(); }
