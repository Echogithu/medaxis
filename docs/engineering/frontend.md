# 前端参考

> 静态源码索引，核对日期：**2026-09-24**。本轮没有启动浏览器或运行前端测试。

## 技术与入口

- React 19、TypeScript 6、Vite 8、MUI 9；依赖和脚本见 [package.json](../../frontend/package.json)。
- 启动入口为 [main.tsx](../../frontend/src/main.tsx)，应用路由与角色守卫集中在 [App.tsx](../../frontend/src/App.tsx)。
- Vite 开发服务器默认端口为 3000，/api 代理到 http://localhost:8000；配置见 [vite.config.ts](../../frontend/vite.config.ts)。
- API 客户端默认使用 /api/v1，可由 VITE_API_BASE 覆盖；访客/登录 token 与角色状态使用 localStorage。

## 页面与角色路由

| 范围 | 页面入口 |
|---|---|
| 公共 | 首页、登录、注册、聊天 |
| 患者 | 健康档案、随访、提醒 |
| 医生 | 工作台、病例列表、病例详情 |
| 管理员 | 仪表盘、用户/医生、模型供应商、系统配置、知识库审核、审计、通知与邮件 |

未登录访问受保护页面会转到登录页；角色不匹配时会按前端守卫跳转。前端守卫只影响页面路由，后端仍需独立执行 API 授权。

## API 客户端与问诊状态

- 前后端 API 客户端按 agent、patient、doctor、admin、documents 等模块划分，索引位于 [frontend/src/api](../../frontend/src/api)。
- 主要问诊事件通过 SSE 处理；[agent.ts](../../frontend/src/api/agent.ts) 包含可复用的 SSE 解析器、问诊续答和诊后对话客户端。
- 聊天历史保存在当前浏览器 localStorage，按用户或访客身份分区。它不等于跨设备同步，也不能在清除浏览器数据后恢复。
- 诊断后追问走独立会话接口；不要与首次问诊和回答问诊卡的路径混为一谈。
- 文档 API 客户端有独立基础路径；VITE_API_BASE 自定义值不会覆盖所有文档上传请求。

## 文件处理

前端有两种不同上传调用：

1. 医学报告上传到 /api/v1/documents/upload，前端轮询解析结果，再将解析内容关联到问诊会话。
2. 病例附件使用独立的 /api/v1/upload/upload 路径。

已完成上传的报告可按任务 ID 恢复轮询；尚未完成上传的文件仍需重新选择。解析任务状态目前保存在后端进程内存中，前端刷新能力不能替代后端任务持久化。

## 测试与检查

~~~sh
cd frontend
npm test
npm run build
npm run lint
~~~

Node 单测使用 Node 测试运行器；浏览器回归脚本使用模拟 API/SSE，需要 Playwright 和 Edge。脚本默认打开 127.0.0.1:3001，而 Vite 默认使用 3000；启动时可显式指定端口：

在第一个终端启动 Vite：

~~~sh
cd frontend
npm run dev -- --host 127.0.0.1 --port 3001
~~~

Vite 启动后，在另一个终端运行浏览器回归：

~~~sh
cd frontend
python tests/chat_history_browser.py
~~~

package.json 当前没有独立 typecheck 脚本。PRD 记录了前次审查时 TypeScript 检查失败；当前错误数和状态需在依赖可用时重新运行检查，不能将历史结果当成本轮测试结果。
