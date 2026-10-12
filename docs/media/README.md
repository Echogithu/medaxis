# MedAxis 展示素材

展示患者从描述症状到准备就医资料的连续过程。根 [README](../../README.md#演示预览) 使用本目录的 1 个 GIF 与 9 张 PNG；均来自 2026-10-09 录制时的前端实际运行页面。

2026-10-12 整理时，当前前端源码指纹已与录制清单不同。保留原始素材、录制日期与指纹作为历史展示记录；`--verify-media` 会拒绝当前源码与旧清单的组合。素材文件完整性可独立核对，但当前页面一致性需要重新录制后验证。

## 场景与录制边界

[scenario.json](demo/scenario.json) 是展示数据的唯一来源：虚构患者“林晓（演示）”，2 条病例、2 份本人安排的记录计划、5 项任务、2 道问诊补问。邮箱使用保留的 `example.test` 域名，没有真实个人信息或可用登录凭据。过敏史保持未知，病情陈述尚待本人核对；计划不代表医生医嘱。

展示日期固定为 **2026-10-08**，实际录制日期为 **2026-10-09**，便于各页面的日期、任务进度和时间线一致。

录制使用 Playwright 在本机拦截全部 `/api/v1/` 请求，以合成数据重放 API 与 SSE（逐条返回问答、问题卡片和总结的事件）。仅允许同源页面与 Vite 静态资源的 GET 请求；其他本机端口、未列出的请求、WebSocket 和 Service Worker 均阻止，使用本机字体。前端按照现有组件和交互渲染，没有替换页面布局或绘制虚构界面。GIF 是 9 个真实操作状态组成的分镜，底部字幕始终标明合成与预置重放。

**未验证范围：** 真实登录与权限、模型生成质量、实时检索、业务数据库保存与恢复、临床有效性。参考资料是预置的 NHS 公开资料，不是本次实际检索结果；页面保留“相关性待核对”和无逐条核对记录的状态。进入病例页展示的是重放响应，不能据此宣称数据库恢复成功。

## 素材清单

| 文件 | 内容 | 尺寸 |
|---|---|---|
| [patient-journey.gif](patient-journey.gif) | 描述症状 → 补问 → 总结 → 来源 → 同病例资料 → 就医核对 → 摘要 → 日常记录；9 帧、22.2 秒、循环播放 | 1080 × 825 |
| [consultation.png](consultation.png) | 主诉与两张补问卡片 | 1280 × 900 |
| [evidence-report.png](evidence-report.png) | 可能的原因、未知信息与下一步 | 1280 × 900 |
| [reference-source.png](reference-source.png) | 参考资料摘录及待核对状态 | 1280 × 900 |
| [case-preparation.png](case-preparation.png) | 患者陈述、未知项和给医生看的摘要 | 1280 × 900 |
| [today-health.png](today-health.png) | 今天的记录任务与近期问诊 | 1280 × 900 |
| [health-records.png](health-records.png) | 合成档案及未知过敏史 | 1280 × 900 |
| [followup-plans.png](followup-plans.png) | 本人安排的记录计划、任务进度与日程 | 1280 × 900 |
| [followups-mobile.png](followups-mobile.png) | 手机宽度下的随访计划 | 390 × 844 |
| [health-mobile.png](health-mobile.png) | 手机宽度下的健康档案 | 390 × 844 |

[manifest.json](demo/manifest.json) 记录录制时间、场景与前端源码的 SHA-256、每个文件的大小和校验值、浏览器异常与未定义 API 请求。GIF 小于 1 MB，整套素材约 1.6 MB；实际大小以清单为准。

## 本机复现

前置条件：已有前端开发依赖和 Node.js；Python 环境已安装 `playwright`、`Pillow`；本机已有 Microsoft Edge 和中文字体。此流程不需要后端、数据库、模型密钥或真实患者账号。

在第一个 PowerShell 终端进入 `frontend` 并启动页面：

```powershell
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3001 --strictPort
```

在第二个终端进入仓库根目录，校验数据、重新录制、核对文件：

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/capture_readme.py --validate-only
python scripts/capture_readme.py
python scripts/capture_readme.py --verify-media
```

默认使用 Edge；可通过 `--channel` 指定已可用的浏览器通道，或通过 `--font` 指定本机中文字体。`--base-url` 只接受本机地址，默认端口 3001；`--output` 可将素材录制到其他目录。

校验会完整解码图片与 GIF，核对 9 帧/22.2 秒、循环播放、尺寸、文件校验值和素材相对链接，要求两个 README 均覆盖清单中的全部素材。前端源码或场景文件变化后会要求重新录制；源码校验基于文件字节，换行方式变化也会改变结果。

此脚本不运行业务库的资料准备流程，不修改演示额度，不向业务库种数据。公开材料采用相对路径；发布时同步素材、场景、脚本及对应前端源码，避免截图与克隆版本不一致。
