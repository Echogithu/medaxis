/** 合成 API 浏览器回归；科室包由实际 Python builder 构造，不访问病例库。 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { mkdirSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:3018';
const output = path.join(root, '.ai/tasks/2026-09-30-visit-preparation');
const python = process.env.MEDAXIS_TEST_PYTHON || path.join(root, 'backend/.venv/Scripts/python.exe');
const source = {
  case: { id: 'synthetic-a', title: '合成病例', chief_complaint: '咳嗽三天', is_emergency: false },
  patient_facts: { hpi_onset: '三天前' }, patient_profile: {}, report: { primary_diagnosis: '合成分析', red_flags: [] }, materials: [],
};
let nextPackageId = 1;
function buildPackage(corrections = []) {
  const result = spawnSync(python, ['-c',
    'import json,sys; from app.services.case_preparation import build_package; x=json.load(sys.stdin); print(json.dumps(build_package(x["source"],x["corrections"]),ensure_ascii=False))'],
  { cwd: path.join(root, 'backend'), input: JSON.stringify({ source, corrections }), encoding: 'utf8',
    env: { ...process.env, SECRET_KEY: randomBytes(32).toString('hex'), PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' } });
  assert.equal(result.status, 0, result.stderr);
  return { ...JSON.parse(result.stdout), package_id: `package-${nextPackageId++}`, case_id: 'synthetic-a', version: 1, revision: 1,
    state: 'ready_for_review', is_stale: false, source_fingerprint: 'synthetic', created_at: null, updated_at: null };
}
let preparation = null, history = [], failSave = false, copyCount = 0;
const report = { primary_diagnosis: '合成分析', key_findings: ['仅用于界面测试'], red_flags: [], severity: 'low' };
const payload = Buffer.from(JSON.stringify({ sub: 'synthetic-patient', exp: 9999999999 })).toString('base64url');
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
const checks = [];
try {
  const context = await browser.newContext({ viewport: { width: 1280, height: 960 } });
  await context.addInitScript(({ token }) => {
    localStorage.setItem('access_token', token);
    localStorage.setItem('user_role', 'patient');
    window.copiedSummary = [];
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async text => { window.copiedSummary.push(text); } }, configurable: true });
  }, { token: `header.${payload}.signature` });
  await context.route('**/api/v1/**', async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    let data = {};
    if (pathname.endsWith('/auth/me')) data = { id: 'synthetic-patient', role: 'patient', full_name: '合成患者' };
    else if (pathname.endsWith('/patient/cases')) data = [
      { id: 'synthetic-a', title: '合成病例 A', chief_complaint: '咳嗽三天', status: 'pending_review', created_at: null },
      { id: 'synthetic-b', title: '合成病例 B', chief_complaint: '牙痛', status: 'pending_review', created_at: null },
    ];
    else if (pathname.endsWith('/synthetic-b/recovery')) return route.fulfill({ status: 500, json: { detail: '合成读取失败' } });
    else if (pathname.endsWith('/recovery')) data = { case: { id: 'synthetic-a', title: '合成病例 A', status: 'pending_review' }, report, lab_reports: [], materials: [] };
    else if (/\/preparation\/package-\d+$/.test(pathname) && request.method() === 'PATCH') {
      if (failSave) return route.fulfill({ status: 409, json: { detail: { message: '合成版本冲突' } } });
      const update = request.postDataJSON();
      const changed = JSON.stringify(preparation.patient_corrections) !== JSON.stringify(update.patient_corrections);
      preparation = { ...preparation, revision: preparation.revision + 1, patient_corrections: update.patient_corrections,
        patient_questions: update.patient_questions, is_stale: preparation.is_stale || changed,
        known_facts: preparation.known_facts.map(fact => ({ ...fact, confirmed: update.confirmed_fact_ids.includes(fact.id) })),
        preparation_items: preparation.preparation_items.map(entry => ({ ...entry, status: update.checklist_updates.find(x => x.item_id === entry.id)?.status || entry.status })) };
      data = preparation;
    } else if (pathname.endsWith('/preparation')) {
      if (request.method() === 'POST') {
        const previous = preparation;
        preparation = buildPackage(previous?.patient_corrections || []);
        if (previous) {
          preparation.version = previous.version + 1;
          preparation.patient_questions = previous.patient_questions;
          history = [previous, ...history];
        }
        data = preparation;
      } else data = { package: preparation, history };
    } else if (pathname.endsWith('/post-visit-feedback')) data = { feedback: null, history: [] };
    await route.fulfill({ status: 200, json: data });
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {
    // 预期的合成 409/500 请求会产生网络日志；React 等应用错误仍必须失败。
    if (message.type() === 'error' && !/^Failed to load resource: the server responded with a status of (409|500) /.test(message.text())) errors.push(message.text());
  });
  await page.goto(`${base}/cases?case_id=synthetic-a`);
  await page.waitForLoadState('networkidle');
  await page.getByRole('button', { name: '准备去就诊', exact: true }).click();
  await page.getByRole('button', { name: '整理就诊摘要', exact: true }).click();
  await page.getByText('可考虑咨询：呼吸内科', { exact: true }).waitFor();
  for (const name of ['下一步建议', '出发前准备', '给医生看的摘要']) assert.equal(await page.getByRole('region', { name, exact: true }).count(), 1);
  assert.equal(await page.getByLabel('我确认这项患者陈述准确', { exact: true }).isVisible(), false);
  assert.equal(await page.getByLabel('就诊摘要预览', { exact: true }).isVisible(), false);
  checks.push('默认三块内容；核对、完整摘要、AI 与来源按需展开');

  await page.getByRole('button', { name: '查看科室参考依据与适用范围', exact: true }).click();
  assert.equal(await page.getByRole('link', { name: '中山大学附属第六医院 · 常见疾病导诊指引', exact: true }).getAttribute('href'), 'https://www.sysu6h.cn/guide/outpatient/502');
  await page.getByRole('button', { name: '查看科室参考依据与适用范围', exact: true }).click();
  const question = page.getByLabel('希望向医生询问的问题（每行一条）', { exact: true });
  await question.fill('需要带哪些检查？');
  await page.getByRole('navigation', { name: '问诊记录阶段' }).getByRole('button', { name: '记录就诊结果', exact: true }).click();
  await page.getByRole('navigation', { name: '问诊记录阶段' }).getByRole('button', { name: '准备去就诊', exact: true }).click();
  assert.equal(await question.inputValue(), '需要带哪些检查？');
  checks.push('切换就诊阶段保留准备表单的未保存输入');
  await page.getByRole('button', { name: '保存并复制摘要', exact: true }).click();
  await page.getByText('已复制已保存的摘要到剪贴板。', { exact: true }).waitFor();
  let copied = await page.evaluate(() => window.copiedSummary);
  assert.match(copied.at(-1), /需要带哪些检查？/);
  assert.equal(copied.at(-1).includes('合成分析'), false);
  assert.equal(preparation.patient_questions[0], '需要带哪些检查？');
  copyCount = copied.length;
  checks.push('官方来源链接；保存后复制；复制不混入 AI 疑似诊断');

  await question.fill('失败时也保留这个问题');
  failSave = true;
  await page.getByRole('button', { name: '保存并复制摘要', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '合成版本冲突' }).waitFor();
  assert.equal(await question.inputValue(), '失败时也保留这个问题');
  assert.equal((await page.evaluate(() => window.copiedSummary)).length, copyCount);
  failSave = false;
  checks.push('保存失败保留输入且不复制未保存内容');

  preparation.revision += 1;
  await page.getByRole('button', { name: '重新读取已保存版本', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '先前未保存的草稿仍保留' }).waitFor();
  await page.getByRole('button', { name: '查看先前未保存的草稿', exact: true }).click();
  assert.match(await page.getByLabel('先前未保存的草稿', { exact: true }).inputValue(), /失败时也保留这个问题/);
  await page.getByRole('button', { name: '已核对，继续编辑当前摘要', exact: true }).click();
  await question.fill('失败时也保留这个问题');
  await page.getByRole('button', { name: '保存准备内容', exact: true }).click();
  await page.getByText('已保存确认内容。', { exact: true }).waitFor();
  assert.equal(preparation.patient_questions[0], '失败时也保留这个问题');
  checks.push('版本冲突后可重新读取并核对保留草稿，再次保存');

  await page.getByRole('button', { name: '核对或修改病情', exact: true }).click();
  await page.getByRole('button', { name: '修改本次主要诉求', exact: true }).click();
  await page.getByLabel('补充更正（保留原记录）', { exact: true }).fill('牙痛');
  await page.getByRole('button', { name: '保存准备内容', exact: true }).click();
  await page.getByText('可考虑咨询：口腔科', { exact: true }).waitFor();
  await page.getByRole('button', { name: '复制摘要', exact: true }).click();
  await page.getByText('已复制已保存的摘要到剪贴板。', { exact: true }).waitFor();
  copied = await page.evaluate(() => window.copiedSummary);
  assert.match(copied.at(-1), /牙痛/);
  assert.equal(copied.at(-1).includes('咳嗽三天'), false);
  assert.equal(preparation.known_facts.find(fact => fact.id === 'patient.chief_complaint').value, '咳嗽三天');
  checks.push('更正后重新生成建议；当前摘要与保留原话不混淆');

  mkdirSync(output, { recursive: true });
  await page.getByRole('button', { name: '收起病情核对', exact: true }).click();
  await page.setViewportSize({ width: 1280, height: 1700 });
  await page.locator('fieldset:not([aria-hidden])').screenshot({ path: path.join(output, 'preparation-desktop.png') });
  preparation.is_stale = true;
  await page.reload();
  await page.getByRole('button', { name: '准备去就诊', exact: true }).click();
  await page.getByRole('button', { name: '更新就诊摘要', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '复制摘要', exact: true }).isDisabled(), true);
  await page.getByRole('button', { name: '更新就诊摘要', exact: true }).click();
  await page.getByText('可考虑咨询：口腔科', { exact: true }).waitFor();
  checks.push('过期摘要禁用复制，更新后恢复');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.getByRole('region', { name: '下一步建议', exact: true }).screenshot({ path: path.join(output, 'preparation-mobile.png') });
  await page.getByRole('region', { name: '给医生看的摘要', exact: true }).screenshot({ path: path.join(output, 'preparation-mobile-summary.png') });
  await page.getByRole('button', { name: '核对或修改病情', exact: true }).click();
  await page.getByRole('button', { name: '修改本次主要诉求', exact: true }).click();
  await page.getByLabel('补充更正（保留原记录）', { exact: true }).fill('腹泻');
  await page.getByRole('button', { name: '保存准备内容', exact: true }).click();
  await page.getByText('可考虑咨询：消化内科', { exact: true }).waitFor();
  assert.deepEqual(preparation.patient_corrections.map(entry => entry.fact_id), ['patient.chief_complaint']);
  await page.getByRole('button', { name: '复制摘要', exact: true }).click();
  copied = await page.evaluate(() => window.copiedSummary);
  assert.match(copied.at(-1), /腹泻/);
  assert.equal(copied.at(-1).includes('牙痛'), false);
  checks.push('重复修改已更正病情仍写回原字段，建议与复制摘要更新一致');

  await question.fill('切换后仍保留的草稿问题');
  await page.getByRole('button', { name: '返回问诊记录', exact: true }).click();
  await page.getByRole('list', { name: '问诊记录列表', exact: true }).getByRole('button', { name: /牙痛/ }).click();
  await page.getByRole('alert').filter({ hasText: '这条问诊记录暂时无法读取' }).waitFor();
  assert.equal(await page.getByRole('button', { name: '复制摘要', exact: true }).count(), 0);
  await page.getByRole('button', { name: '返回问诊记录', exact: true }).click();
  await page.getByRole('list', { name: '问诊记录列表', exact: true }).getByRole('button', { name: /咳嗽三天/ }).click();
  await page.getByRole('button', { name: '准备去就诊', exact: true }).click();
  await page.getByText('已恢复本次浏览中未保存的修改。', { exact: true }).waitFor();
  assert.equal(await question.inputValue(), '切换后仍保留的草稿问题');
  await page.getByRole('button', { name: '返回问诊记录', exact: true }).click();
  await page.getByRole('list', { name: '问诊记录列表', exact: true }).getByRole('button', { name: /牙痛/ }).click();
  await page.getByRole('alert').filter({ hasText: '这条问诊记录暂时无法读取' }).waitFor();
  preparation.revision += 1;
  await page.getByRole('button', { name: '返回问诊记录', exact: true }).click();
  await page.getByRole('list', { name: '问诊记录列表', exact: true }).getByRole('button', { name: /咳嗽三天/ }).click();
  await page.getByRole('button', { name: '准备去就诊', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '先前未保存的草稿仍保留' }).waitFor();
  assert.equal(await question.isDisabled(), true);
  await page.getByRole('button', { name: '查看先前未保存的草稿', exact: true }).click();
  assert.match(await page.getByLabel('先前未保存的草稿', { exact: true }).inputValue(), /切换后仍保留的草稿问题/);
  await page.getByRole('button', { name: '已核对，继续编辑当前摘要', exact: true }).click();
  assert.equal(await question.isDisabled(), false);
  assert.equal(await question.inputValue(), preparation.patient_questions.join('\n'));
  checks.push('病例切换恢复内存草稿；版本变化保留旧草稿供核对，不覆盖新版本');
  source.case.chief_complaint = '咳嗽和腹泻';
  preparation = null;
  history = [];
  await page.goto(`${base}/cases?case_id=synthetic-a`);
  await page.getByRole('button', { name: '准备去就诊', exact: true }).click();
  await page.getByRole('button', { name: '整理就诊摘要', exact: true }).click();
  await page.getByRole('combobox', { name: '这次主要想咨询哪类问题？', exact: true }).click();
  await page.getByRole('option', { name: '腹泻、便秘、反酸等消化相关问题', exact: true }).click();
  await page.getByRole('button', { name: '保存准备内容', exact: true }).click();
  await page.getByText('可考虑咨询：消化内科', { exact: true }).waitFor();
  checks.push('多个方向只补一个咨询主题，保存后更新参考');
  await page.getByRole('button', { name: '核对或修改病情', exact: true }).click();
  await page.getByRole('button', { name: '修改主要咨询问题', exact: true }).click();
  await page.getByRole('combobox', { name: /^修改本次咨询主题/ }).click();
  await page.getByRole('option', { name: '其他、多个问题或不确定', exact: true }).click();
  await page.getByRole('button', { name: '保存准备内容', exact: true }).click();
  await page.getByText('先确认本次咨询方向', { exact: true }).waitFor();
  assert.equal(await page.getByText('可考虑咨询：消化内科', { exact: true }).count(), 0);
  checks.push('已选咨询主题可明确撤回专科方向');
  source.report.red_flags = ['合成条件警示：如出现危险信号请及时就医'];
  preparation = buildPackage();
  await page.reload();
  await page.getByRole('button', { name: '准备去就诊', exact: true }).click();
  await page.getByText('先确认就医紧急程度', { exact: true }).waitFor();
  assert.equal(await page.getByRole('combobox', { name: '这次主要想咨询哪类问题？', exact: true }).count(), 0);
  assert.equal(await page.getByText('可考虑咨询：消化内科', { exact: true }).count(), 0);
  source.case.is_emergency = true;
  preparation = buildPackage();
  await page.reload();
  await page.getByRole('button', { name: '准备去就诊', exact: true }).click();
  await page.getByText('请优先处理紧急就医', { exact: true }).waitFor();
  checks.push('危险信号先确认；紧急标记优先，主题选择不能绕过');
  assert.deepEqual(errors, []);
  checks.push('手机无横向溢出；失败切换无串病例或运行时异常');
  writeFileSync(path.join(output, 'browser-result.json'), JSON.stringify({ scope: 'synthetic mocked API; real preparation builder', checks }, null, 2));
  for (const check of checks) console.log(`PASS: ${check}`);
} finally { await browser.close(); }
