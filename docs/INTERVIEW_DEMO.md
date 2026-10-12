# 面试演示的访问与费用保护

> 最近运行证据：2026-10-06。文档复核同日；本次文档整理未重新查询运行库、剩余额度或 Funnel。下列计数与容器路径属于这次本机记录，异地克隆需重新准备。

用户选择保留真实 AI，仅专用演示账号可用并设置共享总调用上限。本模式在原有 Docker 应用中生效，尚未开启公网 Funnel。

## 已实现

- 专用普通患者账号；保留原密码验证、JWT、注销撤销与业务数据归属检查。
- 关闭访客创建、公开注册、访客迁移、角色切换、共享账号改密和直接模型调试接口。其他账号的新登录和旧令牌不允许进入演示 API。
- 所有当前模型 HTTP 客户端在实际发送前锁定 `system_settings` 的计数行并持久化扣额。总上限 20 次，重试、多轮、embedding、rerank、文件请求都计数；失败不返还，重启和资料脚本重复执行不补充额度。没有专用账号请求身份的后台模型任务暂停。
- 每次生成默认最多 2048 输出 token，显式请求最多 8192。请求数上限不等于固定人民币费用；具体成本取决于模型和输入输出长度。
- 一份合成健康档案、两份合成病例和一份明确标识为合成的 PDF 原件。预置病例没有伪造 AI 或医生诊断。
- 当前数据库尚无新版报告中心的表，未执行迁移。合成 PDF 通过既有病例附件下载，标记未自动解析；演示页面提供附件入口提示，不假装报告中心已就绪。

## 本地使用

打开 `http://127.0.0.1:3000/`。凭据保存在 Git 忽略的 `.ai/tasks/2026-10-06-original-site/demo-credentials.local.json`，账号为 `interview-demo@medaxis.example.com`。请将密码单独提供给指定面试官，不放在公开网页、源码或公开链接中。

准备脚本 `scripts/prepare_interview_demo.py` 生成随机密码时强制检查凭据路径被 Git 忽略；再次准备已有账号时检查身份和密码匹配，仅补缺失的合成记录，不改已有病例或清零额度。密码未输出到命令日志。

## 验证与恢复

定向测试（不连接业务数据库、不调用真实模型）：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_interview_demo.py backend/tests/test_interview_demo_seed.py backend/tests/test_intent_latency.py backend/tests/test_patient_llm_errors.py -q -p no:cacheprovider
```

目标容器的登录、拒绝入口、合成档案与病例、附件下载检查：

```powershell
backend/.venv/Scripts/python.exe .ai/tasks/2026-10-06-original-site/demo_smoke.py
```

此脚本属于 Git 忽略的本机过程资料，异地克隆不包含它。它读取本次专用凭据，仅输出检查结果，不输出密码或令牌，也不调用模型。2026-10-06 的浏览器验证完成两次真实 AI 短对话，当时累计 4 次请求、剩余 16 次；实时额度以页面或状态接口为准。第二次测试后再次准备资料并重启后端，仍为 4/20；普通回复结束后输入框已实际恢复。

本次命令证据：上述后端定向测试退出码 0，74 项通过；前端 `node --experimental-strip-types --test tests/*.test.mjs` 退出码 0，90 项通过；`node node_modules/typescript/bin/tsc -b --pretty false` 退出码 0；Vite 构建退出码 0（仍有原有大 chunk 提示）；目标容器 `demo_smoke.py` 退出码 0，拒绝入口与合成资料均通过；`/ready` 显示数据库和 Redis 均为 `ok`；`tailscale funnel status` 显示 `No serve config`。

**恢复个人使用前，必须先关闭所有公开 Funnel，并确认 `tailscale funnel status` 显示无公开配置。** 演示模式关闭后会恢复原应用入口，不能在公网入口仍开启时执行。

本次验证容器内已放入准备脚本和凭据；下列 /tmp 路径为本机快照，不由镜像保证，重建或异地克隆后须重新准备。确认文件存在且公网已关闭后，可停用演示账号并保留资料与额度：

```powershell
docker exec -w /app medaxis-backend python /tmp/prepare_interview_demo.py --credentials /tmp/medaxis-demo-credentials.json --disable
```

前端恢复点：`.ai/tasks/2026-10-06-original-site/frontend-before-guards/`。如需恢复前端外观，将该目录内容复制回现有前端容器的 `/usr/share/nginx/html/`；恢复前仍须确认公网入口已关闭。没有删除原病例、修改真实患者记录或执行数据库迁移。

## 已知边界

该账号与其他账号共用原数据库，依赖原业务鉴权；本次核验不能替代全应用安全审计。共享账号持有人可以消耗剩余额度或修改自己的演示记录。Funnel 开启、外部浏览器与公网深链验证尚未执行。

## 实现位置

- `backend/app/services/interview_demo.py`：演示鉴权、配置失败关闭、供应商请求扣额和输出长度限制；`backend/app/main.py` 注册中间件。
- `llm.py`、`embedding.py`、`reranker.py`、`intent.py`、`post_visit_actions.py`、`report_processing.py`：现有供应商客户端接入发送前拦截。
- `frontend/src/components/DemoMode.tsx`、`frontend/src/App.tsx`、`frontend/src/auth/LoginPage.tsx`：状态和共享额度提示、关闭演示访客与注册入口。
- `CaseLinkedReports.tsx`、`PatientReportsPage.tsx`：缺少报告中心时引导到既有合成附件；`ChatPage.tsx`：普通响应无待回答会话时恢复输入。
- `scripts/prepare_interview_demo.py`：专用账号与合成资料的幂等准备和停用；`backend/tests/test_interview_demo*.py` 及 `conftest.py`：隔离业务数据库并验证权限、重试、额度及恢复绑定。
