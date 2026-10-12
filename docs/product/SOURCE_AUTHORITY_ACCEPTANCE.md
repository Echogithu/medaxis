# 第六阶段：官方出处与漏证据修复验收

**2026-10-09最新状态：再次加载修复后，引用展示与保存链路通过；问诊完整性和医学支持未通过。** 真实HTTP生成10个片段来源（3篇文档），页面29个正文引用均有目标，刷新后10个卡片、全文和URL一致。29条支持关系全部待核对；首轮未补问却有缺失信息，不能称整体验收通过。阶段7已建立52题原文支持测试集，资产验证通过，生产基线尚未运行，见[下一阶段入口](D:/CAI-Projects/medaxis/docs/product/EVIDENCE_SUPPORT_EVALUATION.md)。详情见[本次验收与前后对照](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/restart-http-v3/REPORT.md)。以下保留历史状态。

本地代码和实际Docker检索对照已完成；4个官方URL已提交数据库。**2026-10-08用户重启后代理真实验收未通过**：5次HTTP检索及R31/R34通过；普通腹泻报告的10个来源片段、36个正文引用链接保存刷新后保留，但儿童肺炎咨询路由显示完成却没有回复/报告/引用。阶段7未启动。演示保护仍关闭、额度原值未重置。

[本次真实验收报告与截图](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/acceptance-live-v1/REPORT.md)记录通过项、失败项、病例ID、实际query、原始结果与复验方法。来源存在不等于支持结论：本次35条支持关系均待核对，成人病例使用儿童指南，未证明临床正确。

**失败后的修复进展：** 已修复consultation绕过问诊/检索/保存流程及空输出假成功，并调整前端结束状态。后端69项、前端93项及TypeScript检查exit0；Docker新进程真实复验生成10个来源，保存报告在页面刷新重开仍保留10卡片及18正文引用，10个完整摘录逐条匹配。**常驻后端仍需操作者重启后验收新问诊，阶段7未开始**。完整前后对照、截图与复验步骤统一见[修复报告](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/empty-success-repair-v1/REPORT.md)；17条支持关系仍待核对，不等于医学准确性通过。

## 如何查看

1. [对比报告](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/REPORT.md)：查看结论、失败分支和逐题变化。
2. [旧45题真实结果](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/old45-final/results.json)与[新20题真实结果](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/validation20-final/results.json)：搜索R31/R34/H17/H18/H19；`groups.before`是阶段5，`groups.after`是阶段6，`serialized_sources`是实际引用字段。
3. [官方核验清单](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/source-authority-manifest.json)、[补录提交回执](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/url-apply/database/results.json)、[新增冻结问题](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/validation-frozen-v1/QUESTIONS.md)。
4. [自动复核命令](D:/CAI-Projects/medaxis/evals/source-authority/README.md)、[验证记录](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/verification-final.json)、[阶段记录](D:/AI-Command-Center/docs/commander/task-traces/2026-10-08-source-authority/CHECKPOINTS.md)。

## 已证实与未解决

| 项目 | 阶段5→阶段6 | 验收含义 |
|---|---|---|
| 官方URL | 0/4→4/4 | 新检索返回对应官方原文链接，不伪造网址 |
| 旧40道正例完整证据 | 36/40→38/40 | R31、R34改善；R20、R32仍缺金标证据 |
| 旧5道无答案题错误候选 | 0/5→0/5 | 固定回归通过 |
| 新16道正例完整证据 | 16/16→16/16 | 未证实新增覆盖收益 |
| 新4道无答案题错误候选 | 3/4→3/4 | 明显缺口；不能称拒答可靠 |

新20题来自同一语料，非盲测、医学gold未专业审核、限定词未完整标注；只证明固定原文检索表现，不证明诊断正确。R26首个证据排名1→2；新H08为4→5，完整覆盖保留。来源链接补齐与算法收益分开计算。

## 页面怎么验收

1. 在项目目录由操作者重启后端加载阶段6代码：`docker compose restart backend`。刷新页面。无需重建前端；本轮前端未改。health200只证明存活，不能证明算法加载。
2. 使用测试账号新建问诊，围绕R31/R34所涉情景填写信息并完成追问。生成**新报告**后展开“参考资料与说明”，应有实际来源编号、标题、完整摘录、原文位置；肺炎支原体指南的“打开来源”应跳到国家卫生健康委2025年版PDF。再抽查腹泻2020、流感2025、NICE NG143来源，标题与版次对应。
3. 查看原文片段：补充前后文时保留原命中片段、起止位置、文档/片段ID；数值、限定条件不能因预览整理丢失。若正文未使用某来源，仍能查看来源，但不能显示为已支持该结论。
4. 保存再重开新报告：核对来源编号、链接、摘录和正文引用仍在。之前保存且URL为空的旧报告不会自动补链，本轮没有批量修改历史报告。
5. R31/R34要记录实际工具query和sources；问诊agent改写query或开启外部搜索可能产生不同结果，不能把页面一例当作固定65题的复现。用README命令复核固定成绩，内部/外部来源分别核对。
6. 将H17/H18/H19作为**已知失败观察项**，确认实际来源是否回答了支架规格、晶体公式、长期生物制剂治疗。目前纯内部回归仍误召回，不应勾选“拒答通过”；下一阶段需要专业标注及新的冻结样本。

[手动验收单](D:/CAI-Projects/medaxis/.claude/manual-test-source-authority.md)保存截图、实际query、报告ID和通过/失败明细。阶段6页面已实际执行验收但未整体通过，不继承阶段5的用户验收状态。

## 回退与下一阶段

回退须由操作者决定；按[恢复说明](D:/CAI-Projects/medaxis/evals/source-authority/README.md)仅撤本轮代码增量、条件恢复4条旧URL，不覆盖脏工作区和历史引用修复。原值/源码快照及失败结果均保留。

下一阶段优先检查“原文是否回答了问题要求的具体内容”，而非只看疾病名、连续短语或相似度；本阶段不继续拿已暴露的新20题调参。报告中每条医学判断的支持关系与金标需要专业审核，不能用检索覆盖率替代。
