# 图源与派生阅读材料

> Status: REVIEW · 2026-10-09

| 图 | 可编辑来源 | 实际图片 / 交互版 |
|---|---|---|
| 产品全景 | [product-map.mmd](product-map.mmd) | [SVG](product-map.svg) / [PNG](product-map.png) |
| 领域关系 | [domain-model.mmd](domain-model.mmd) | [SVG](domain-model.svg) / [PNG](domain-model.png) |
| 患者闭环 | [USER_FLOWS 第1图](../USER_FLOWS.md)；构建提取为 patient-flow.mmd | [SVG](patient-flow.svg) / [PNG](patient-flow.png) |
| 报告同意 | [USER_FLOWS 第2图](../USER_FLOWS.md)；构建提取为 report-consent.mmd | [SVG](report-consent.svg) / [PNG](report-consent.png) |
| 定向咨询 | [USER_FLOWS 第3图](../USER_FLOWS.md)；构建提取为 doctor-consultation.mmd | [SVG](doctor-consultation.svg) / [PNG](doctor-consultation.png) |
| 思维导图 | [product-mindmap.md](product-mindmap.md) | [交互 HTML](product-mindmap.html) / [静态预览 PNG](product-mindmap.png) |

本目录 PNG/SVG 由文档专用本地脚本读取节点和关系，按已记录布局绘制，不依赖 AI 生图，不冒充应用截图。流程节点及边从 USER_FLOWS 的 Mermaid 块提取，改文档后重新生成；布局文件仅承载位置，不维护第二份节点文字或关系。图是产品流程示意，不构成运行或权限验收。

## 本地生成与检查

需要现有 Python/Pillow 与中文字体、Node.js/marked；未新增项目依赖或应用构建链。当前使用 Codex 自带 runtime。指定可用依赖路径后，从仓库根目录运行：

```powershell
python docs/product/medaxis/tools/render_diagrams.py
node docs/product/medaxis/tools/build_reader.mjs --marked <已有marked目录的绝对路径>
node docs/product/medaxis/tools/validate_docs.mjs --yaml <已有yaml模块目录的绝对路径>
```

`validate_docs` 未提供 `--yaml` 时仍校验文档，但将 manifest 完整解析标记为未执行并返回非零，避免假通过。脚本不连接业务 API、数据库、模型；只读文档/源码定位，并写本目录的派生阅读材料。

思维导图使用当前已配置的 Markmap MCP：先 `list_mindmaps` 确认输出目录，再 `markdown_to_mindmap` 输入本目录源 `.md`、唯一文件名和 `format: html`。用 `node docs/product/medaxis/tools/prepare_mindmap.mjs <返回HTML绝对路径>` 派生到本目录，仅给控件预留空间；节点和关系不变。静态PNG来自本机浏览器适配完成后的实际截图。MCP图片导出另需浏览器依赖，本次未调用或安装；`--offline` 仅表示资源内联，是否零外联按浏览器请求另验。

浏览验证使用已有 Playwright/Edge，临时 HTTP 仅绑定127.0.0.1并限制文件范围，结束关闭本次浏览器与服务：

```powershell
node docs/product/medaxis/tools/verify_reader.mjs --playwright <已有playwright模块的绝对路径> --output .ai/tasks/2026-10-09-product-dossier/browser
```

本次生成/预览/交互的真实状态见 [VERIFICATION](../VERIFICATION.md)。Markdown 是内容真源，阅读版重新生成；不要只手改 HTML。浏览器查看流程图片可点击放大，思维导图可拖动、缩放、折叠。
