# 新40组评测：冻结资产与固定量尺

阶段入口：`.ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/REPORT-T1.md`。
正式资产：该目录的`frozen-v2/`；`draft-v1/`是被审核拒绝的旧草稿，禁止用于实验。

从MedAxis根目录执行：

```powershell
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/build_resume_eval.py --verify-only
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/test_resume_eval.py
```

第一条应输出`PASS_DRAFT_ASSETS_ONLY`、40组、32可回答/8无答案、开发24/留出16、108候选、旧范围重叠0及跨集合来源0。这里的DRAFT指医学标签未经专业审核，不表示真实模型已完成评测。第二条当前为12项测试OK（T1存档版本为9项），失败注入子进程退出码全部非0。测试使用人为fixture，其中完美预测由gold构造，只证明评分规则，不是模型效果。

`inputs-development.json`供开发实验读取，`inputs-holdout.json`仅在方案锁定后读取。执行器不得读取`gold.json`、`QUESTIONS.md`、`review.csv`或`prior-exposure.json`；离线评分器可以读取。留出是未用于调优的同语料测试，专业审核0，不能声称独立医学盲测。

离线复算未来真实观测：

```powershell
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/resume_eval_score.py --assets .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/frozen-v2 --split development --observations <实际观测JSON路径>
```

观测协议为`resume-eval-observations-v1`：顶层`protocol/split/input_sha256/rows`。每行含`id/status/retrieved_sources/candidates/ranked_ids/elapsed_ms/usage/error_type`，具体校验见评分器。检索来源投影为`document_id/start/end/quote`；候选为`id/label/retain/score`。原始模型输出、prompt、实际源码与调用证据另行保存在实验目录，并由运行验证器核对，不能只提交人为填写的观测JSON冒充真实执行。

指标口径：

- Hit@5/10：前K条来源与任一必要原文范围重叠；命中一个数值不等于回答完整。
- 标注证据Recall@5/10：每组已标注的必要原文主张中，前K条来源完整覆盖的比例；不是穷尽整库相关chunk的Recall。
- 必要主张覆盖：所有已标注主张均完整覆盖，包含其数值、条件和否定。整段证据完整覆盖另外计算；不能把两者混用。
- MRR@5/10：前K条中首次命中必要范围的倒数；另有全返回列表MRR诊断。
- 无答案误召回率：库内无支持的题仍返回资料的比例。有无答案执行错误时该值为null，并给出包含错误的门禁失败率；超时不能算成功拒答。
- 候选Accuracy、三类P/R/F1和Macro-F1：完整/部分/不回答三类；unknown保留在分母且停止扩量。
- 候选nDCG：完整/部分/不回答等级2/1/0，增益为`2^等级-1`。K为每题候选数量2至4，不冒充真实检索@10。
- 误删完整或部分、误保留无关、错误、真实token与耗时分开统计；usage缺失为null，不当作0。

冻结文件或构建规格变化会使复算拒绝；旧版本用存档源码核对。保留旧草稿和失败审核，不覆盖旧资产。尚无本批模型基线、优化提升、报告引用或临床成绩。

## T2四方案运行与验收

本Goal目录当前`experiment-plan-v2/plan.json`预注册96项开发任务，先6组 × 四方案=24次，再继承结果并补72次。`CALL_PLAN.md`说明新增额度；用户未授权前不能调用付费模型。`preflight-v3/`为包含共用额度账本版本的零调用Docker只读预检。v1计划和v2预检作为旧证据保留，源码指纹变化后不再用于新调用。

离线控制测试及准备材料核对：

```powershell
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/test_resume_experiment.py
backend/.venv/Scripts/python.exe -B -X utf8 .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/verify_t2_preparation.py
```

第一条当前10项隔离fixture测试、9种真实子进程失败注入，模型调用0；新增对话/embedding共用累计账本和未授权embedding拒绝。第二条验证源码、冻结输入、四份提示词、预注册请求体和只读预检记录；不会调用Docker或模型。后续新增实验脚本/规则改动需新建预检和计划版本，不能沿用旧key。

授权文件只能根据明确的人类回复落盘，含`status/source/message_reference/max_diagnosis_http_requests/scope`，可附`max_embedding_http_requests`，缺失表示embedding额度0；两类请求共用本Goal账本，不得每个实验重置额度。不能由“同意继续”推断无限额度。以下为后续入口，尚未执行付费步骤：

```powershell
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_experiment.py smoke --plan .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/experiment-plan-v2 --authorization <本Goal真实授权JSON> --output <新的Goal子目录>
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_experiment_verify.py --mode smoke --plan .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/experiment-plan-v2 --run <上一步目录> --output <新的离线评分JSON>
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_experiment.py development --plan .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/experiment-plan-v2 --authorization <同一授权JSON> --parent <已核验烟测目录> --output <新的Goal子目录>
```

运行器仅传开发问题、候选原文和核验出处，不传gold；原文SHA和坐标与当前数据库核对；发送前/收到响应后/解析结束后分别flush，未知请求不重发。执行使用只读事务，保护设置保持原值。模型当前为deepseek-flash；当前服务实际请求不发送temperature，禁止声称固定温度0；SDK重试0，最多4096输出tokens/次。

独立验证器重新解析原始响应，核对HTTP记录、源码/评分器快照、预注册消息、usage和逐题日志。任一缺失、unknown或错误停止扩量；分类错题保留并记badcase。6组烟测明确使用子集分母，不能写成24组全集成绩。

这一步评测的是**给定候选的判断和排序**，`metric_scope=given_candidates_only`，所有检索指标必须为null。真实检索Recall@K需要后续实际工具检索另跑；不得把候选顺序当真实召回记录。

## 实际关键词回退消融

`keyword-context-v1/`保存开发24组实际RAG关键词回退（向量和重排被主动禁用），比较原始chunk与原文邻接补全。模型/HTTP均0。运行入口resume_keyword.py只传开发问题和文档身份；不读gold。离线核验resume_keyword_verify.py检查实际输入、源码快照、逐题坐标与原文再评分。复算已保存结果无需Docker：

```powershell
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_keyword_verify.py --run .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/keyword-context-v1
```

该实验不包含语义召回、来源覆盖筛选或生成报告，不能解释成现有完整生产链路成绩。候选误召回不等于最终误答。指标及失败查询见本Goal的REPORT-T2-KEYWORD.md。

## 真实查询向量的准备与验收

当前`embedding-preflight-v2/`为真实Docker零HTTP预检；当前配置text-embedding-3-small，1536维、125块，与四份指南已有向量一致。快照同时绑定每块ID、位置、内容SHA及全部存储向量的语料指纹，不能以分块数量相同代替内容未变。`embedding-preflight-v1/`是门禁修订前记录，保留而不用于新调用。

`embedding-plan-v1/`冻结开发24个查询、生产脱敏后的实际请求体、SDK默认base64编码、业务/评测源码和模型/语料快照；最多一次批量HTTP。新增向量额度仍待明确人类答复，本轮没有生成真实查询向量，也没有新的语义检索成绩。

从项目根复核，无模型费用：

```powershell
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/test_resume_embedding.py
backend/.venv/Scripts/python.exe -B -X utf8 .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/verify_embedding_preparation.py
```

测试当前9项，含8种CLI非零故障注入，fixture只验证工具。第二条核对真实预检、完整计划及源码快照，预期PASS_EMBEDDING_PREPARATION_ONLY、实际HTTP0、计划上限1、retrieval_metrics=null。

付费入口仅在明确授权并落盘后使用，以下步骤尚未执行：

```powershell
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_embedding.py collect --plan .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/embedding-plan-v1 --authorization <本Goal明确包含embedding额度的真实授权JSON> --output <新的Goal子目录>
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_embedding_verify.py collect --run <上一步目录> --plan .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/embedding-plan-v1 --output <新的核验JSON>
```

发送前将授权/共用账本预留/计划关联存档；SDK重试0，不自动重试或重发未知请求。核验24个原始向量的索引/维度/有限非零值、原生usage、base64解码与生产SDK结果一致。缺少原生usage不补0；向量非法时仍保留可确认用量。网络超时不证明Docker子进程已退出，需用checkpoint中的pid及batch_key核对，再处理，不能直接补发。此入口仅提供真实向量；实际混合检索、固定K评分和效果比较另行执行，不能以向量已生成声称召回提升。

## 同题三路检索与上下文消融

新增resume_retrieval.py/runtime/verify：开发24题分别跑关键词、生产语义核心、生产混合search；每路保存原始片段/邻接补全，固定top10并离线评分@5/10。真实向量须先通过resume_embedding_verify.verify_collect的供应商响应、SDK解码、授权及账本核验，人工向量不能直接进入运行器。执行禁止新增HTTP、LLM、重排及外部搜索，不读gold/保留输入；仅评分器读取开发金标。

`retrieval-preflight-v2/`是实际数据库与生产核心的技术自匹配探针：用库内现有向量验证语义/混合/上下文链路，**不是24题真实语义评测**，retrieval_metrics=null。v1保留为门禁修订前历史版本，不用于新验收。

无费用复核：

```powershell
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/test_resume_retrieval.py
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_retrieval_verify.py --run .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/retrieval-preflight-v2
```

预期6测试OK、5种真实CLI故障注入exit1；技术预检PASS_REAL_RETRIEVAL_PIPELINE_PREFLIGHT_ONLY、额外HTTP0、检索/临床指标null。正式运行尚未执行，入口如下；必须提供已经独立核验的真实开发向量目录：

```powershell
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_retrieval.py run --preflight .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/embedding-preflight-v2 --vectors <真实向量运行目录> --vector-plan .ai/tasks/2026-10-09-evidence-support/resume-evaluation-goal/embedding-plan-v1 --output <新的Goal子目录>
backend/.venv/Scripts/python.exe -B -X utf8 evals/evidence-support/resume_retrieval_verify.py --run <上一步目录> --output <新的离线检索评分JSON>
```

正式核验要求72条唯一完整结果（24×3），独立重算余弦和纯语义top10、原文坐标、上下文窗口、真实语料向量指纹、逐题checkpoint及各分支计数。使用缓存向量后的检索时间单列，一次批量embedding的原生usage只计一次，不将消融解释为完整生产报告成绩。正式选型及改善标准见本Goal的EXPERIMENT_CRITERIA.md；真实响应未到位前不能填新的提升率。
