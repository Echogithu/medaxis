# 产品文档与阅读材料验证记录

> Status: REVIEW · 2026-10-09 · 本文记录文档交付检查，不是业务功能或医学质量验收

## 验证范围

检查新文档的需求编号/覆盖、相对链接与行定位、生命周期字段、图源/图片一致性、阅读版桌面/手机布局和思维导图交互。业务 API、数据库、迁移、模型、SMTP、真实患者及发布均未执行。

## 实际执行的检查

| 检查 | 命令 / 工具 | 退出码 / 关键结果 |
|---|---|---|
| 图片生成 | Python `tools/render_diagrams.py` | exit 0；5组SVG/PNG，节点/关系来自图源 |
| 阅读版生成 | Node `tools/build_reader.mjs --marked …` | exit 0；10篇Markdown派生为index.html，未引用外部静态资源 |
| 静态契约 | Node `tools/validate_docs.mjs --yaml …` | exit 0 / PASS；19需求、25路由含fallback、5流程/关系图、8阶段、10篇阅读版；相对链接及源码行定位检查通过 |
| 浏览与交互 | Node `tools/verify_reader.mjs --playwright … --output …` | exit 0 / PASS；桌面10/10、390px手机10/10；破图/console/page error/外部请求均0；搜索、内部锚点、手机菜单、嵌入导图通过 |
| 导图真实画面 | 同上 Edge/Playwright | 54节点可见；折叠后51、恢复展开；缩放与拖动通过；控件区不遮盖初始图节点 |
| 独立事实审查 | 两个只读审查者，分别检查事实边界与产品契约 | 0实质finding；仅定向抽查，不是全仓安全或专业批准 |
| 改动范围/恢复点 | 本机任务目录before-files.json与当前SHA-256比对，结合本任务写入路径核对 | 本任务仅新文档/过程材料和docs/README.md两处导航；同期6个AI相关既有路径另有变化，记录后定向复核，不回滚；索引恢复副本匹配原工作区哈希 |

原始浏览结果及截图在本机 `.ai/tasks/2026-10-09-product-dossier/browser/`；范围结果在同任务的 `scope-results.json`。过程目录不随公开克隆分发；上表记录稳定结论，不声称缺少本机证据时仍可复现过去运行。

### 完整复跑命令（本机已用路径）

从仓库根目录运行。依赖来自已安装 runtime/Markmap，不新增项目依赖；其他机器应换成已存在路径。

```powershell
$docPython = 'C:/Users/56318/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$docMarked = 'C:/Users/56318/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/marked'
$docYaml = 'D:/AI-Command-Center/.ai/tools/markmap-mcp/node_modules/yaml'
$docBrowser = 'C:/Users/56318/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
& $docPython docs/product/medaxis/tools/render_diagrams.py
node docs/product/medaxis/tools/build_reader.mjs --marked $docMarked
node docs/product/medaxis/tools/validate_docs.mjs --yaml $docYaml
node docs/product/medaxis/tools/verify_reader.mjs --playwright $docBrowser --output .ai/tasks/2026-10-09-product-dossier/browser
```

思维导图生成接口和派生排版命令见 [图源说明](visuals/README.md)。浏览脚本临时服务仅绑定127.0.0.1，限制在本产品文档和两张合成素材；测试结束关闭自己创建的浏览器和服务。

### 检查中发现并修正

- 图源静态比较曾因Windows换行差异失败，现按规范化换行比较，节点与关系未改变。
- 第一轮截图捕获到切篇平滑滚动/导图适配未稳定的画面；改为切篇即时归位，并增加实际可见节点检查、等待字体与适配完成，重新运行通过。
- 内部锚点测试曾只等hash变化而未等正文渲染，出现测试时序失败；补齐DOM条件后通过，未修改业务代码。
- 依赖检查首次误用frontend的不存在yaml路径；改用实际已安装Markmap依赖后解析通过，没有安装依赖。
- 全工作区“只有索引变化”假设在最终哈希检查失败：同期6个AI服务/评测路径也变动。本任务写入范围未扩展；保留变动，定向复核问题覆盖v3新增证据，更新本包，不把旧快照或他处历史测试当本轮通过。

## 审查重点

最可能失败的五处：把新咨询与旧医生页成熟度混为一谈；把新报告只发文字推广到旧附件；把检索覆盖写成专业准确率；把图源存在写成图片/交互通过；把文档授权写成产品批准或上线授权。逐条以源码/画面/实际命令核对。

## 复跑与恢复

图源/阅读版构建见 [visuals/README](visuals/README.md)。Markdown可独立阅读；生成器或交互版失败不影响原文和已有图片。人工检查清单在本机 `.claude/manual-test-product-dossier.md`，覆盖直接打开、图像放大、标签理解和证据阅读。

恢复点：`.ai/tasks/2026-10-09-product-dossier/docs-README-before.md` 是两处导航改动前的精确工作区副本，SHA-256已与开工快照匹配。恢复只处理本次新增 `docs/product/medaxis/` 并在确认没有后续索引修改后恢复该副本，保留全部先前业务改动；大范围删除需按项目回收站与确认规则执行，不自动清理。独立Markmap中央输出保留，不自动永久删除。

残留边界：整稿REVIEW、开发规划NOT_READY；当前部署、真实患者可用性、专业原文支持/适用性、保留与外发政策未由本次验证解决。文档检查通过不改变这些状态。
