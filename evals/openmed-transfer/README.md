# OpenMed 思路的中文离线迁移实验

本目录保留两轮独立实验：第一轮比较 MedAxis 当前业务函数与 **OpenMed-inspired 中文规则原型**；第二轮实际运行 OpenMed 2.5.0 和固定 revision 的官方中文 PII 模型，见 [SDK_RESULTS.md](SDK_RESULTS.md)。下面正文描述第一轮；第一轮候选未调用 OpenMed SDK、NER、PII 模型或 NLI，不能证明模型效果。两轮均为合成样例组件实验，不代表真实病历效果或临床准确率。

## 范围与输入

- `catalog.json` 是唯一题集真源：24 个手工合成场景，12 development / 12 evaluation。评估组也被实现者看过，不是盲测；不得用本轮分数宣称泛化提升。
- 给定原文提及位置，评估 dominant assertion status；不评实体提取能力或各断言轴的独立准确率。
- 姓名、手机号、证件号、病历号、邮箱、地址均为人工合成测试值，不来自患者。
- 引用题评估指定来源是否支持完整陈述；来源 ID 存在与语义支持分别记账。
- 无数据库、网络模型或图片调用；不读取 `.env`，不使用 backend 的 pytest 数据库 fixture。

## 基线和候选

`run_eval.py` 通过文件加载真实 `build_package`，局部跳过 ORM 包初始化；包内导入的患者回答和科室规则仍是工作区真实源码。引用基线真实调用 `build_knowledge_citations` / `attach_knowledge_citations`。结果记录这些文件、候选、runner 的 SHA256。

基线 `reported` 映射到 `needs_review`，**不**解释为患者当前阳性。基线没有文本去标识组件，隐私对照为原文直通；这不是运行了生产上传或检测全部生产网络出口。

候选复用基线准备包，附加分句语境、等长遮蔽和原文精确引用门禁；不会修改准备包。候选只看 `input` 与基线输出，不接收 gold。原文字符偏移按 Python Unicode code point 计算，不是 UTF-16/字节偏移。

原文精确引用门禁只用于抽取式陈述：错误改写、半句截取和正确意译都可能转 `review`。`review` 表示证据不足，不表示内容为假。

参考机制：[断言状态](https://github.com/maziyarpanahi/openmed/blob/master/openmed/clinical/grounding/assertion_grounding.py)、[brief 门禁](https://github.com/maziyarpanahi/openmed/blob/master/openmed/clinical/brief.py)。仅参考设计思路，未复制上游源码。研究日期：2026-09-30；链接指向可变化的 master，不作为运行依赖。

## 运行

在 MedAxis 根目录执行；使用现有 backend venv，无新增依赖。

```powershell
$env:PYTHONIOENCODING='utf-8'
& .\backend\.venv\Scripts\python.exe -m unittest discover -s evals/openmed-transfer -p test_eval.py -v
& .\backend\.venv\Scripts\python.exe evals/openmed-transfer/run_eval.py --check
& .\backend\.venv\Scripts\python.exe evals/openmed-transfer/run_eval.py --smoke --output .ai/tasks/2026-09-30-openmed-transfer/smoke-rerun.json
& .\backend\.venv\Scripts\python.exe evals/openmed-transfer/run_eval.py --output .ai/tasks/2026-09-30-openmed-transfer/full-rerun.json
```

Smoke 固定 D01/D03/D06/D07/D08，覆盖引用、否定、家属、未知、矛盾和脱敏。先确认评分器能区分正确、错误、缺失及过度遮蔽，再运行 smoke/full。

退出码 0 仅表示题集和输出执行契约成立；候选质量失败仍保留在成绩单。复跑不要覆盖带日期的历史结果。

## 指标口径

| 指标 | 口径 / 限制 |
|---|---|
| 隐私 recall / precision | 字符位置级；星号遮蔽的 gold PII 字符数 / gold 或实际遮蔽字符数；非星号改写为契约错误，不评实体类型准确率 |
| 受保护信息保持 | 手工标注的数值、单位和持续时间片段保持数 / 总片段数 |
| 断言准确率 | 正确 dominant status / 给定提及总数；同时报告 needs_review 和错误阳性/否认 |
| 引用支持 precision | 被接纳且有支持的陈述 / 全部被接纳陈述 |
| 正确陈述接纳 recall | 接纳的正确陈述 / 所有正确陈述；拒绝一切不能获得高 recall |
| 原话历史保持 | 当前准备包保留完整回答历史的案例数；不是候选新增收益 |
| 延迟 | 单次本地调用，候选计入复制基线包；调用顺序固定，不作为性能 benchmark |

空分母使用 null；缺失、重复、越界输出是 contract error。没有输出不算正确，遮蔽标签与实际文本变化不一致也失败。

## 本轮结论

复核后逐例结果：[2026-09-30-rules-v1-reviewed.json](results/2026-09-30-rules-v1-reviewed.json)。[初次结果](results/2026-09-30-rules-v1.json)保留用于追溯。解释与迁移裁决：[RESULTS.md](RESULTS.md)。

本目录没有生产调用方。停用时停止执行实验命令即可，无业务配置或持久化需要回滚。
