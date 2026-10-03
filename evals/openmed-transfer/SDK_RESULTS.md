# 真实 OpenMed 2.5.0 中文实测

结论：**HOLD，不直接接入 MedAxis。** 这是一次真实 SDK 和官方中文模型的组件实验，执行完成不代表质量达标。SDK 增加隐私识别覆盖，也误删病情信息；原生中文语境规则不能覆盖 MedAxis 的未知、矛盾回答语义。

## 实测对象与边界

- 安装真实 `openmed==2.5.0`，依赖冻结在 [sdk-requirements.txt](sdk-requirements.txt)。独立 Python 3.12.14 环境位于 `.ai/tasks/2026-09-30-openmed-transfer/openmed-venv`；未改变生产依赖。
- 官方模型：[OpenMed-PII-Chinese-BigMed-Large-560M-v1](https://huggingface.co/OpenMed/OpenMed-PII-Chinese-BigMed-Large-560M-v1/tree/5cf65bca4760d6efbea015a65b9cf9116aa3519c)，revision `5cf65bca4760d6efbea015a65b9cf9116aa3519c`，权重 2,235,723,416 字节。模型卡标记 Apache-2.0。
- 权重 SHA256：`4c17740551646c9f4e8c1de63e3118ef35e59376654f00010cd8f2b97193e87d`。下载脚本验证官方 LFS 哈希，推理前重新验证本地完整 manifest。SDK 自身另提示缺少 `.openmed-integrity.json`；本实验未伪造 SDK 的完整性声明，采用独立 SHA256 证据。
- 语境：真实 `assert_context(language="zh")` → SDK 自带 `ClinicalAssertion` / `assertion_grounding_status`。输入已有提及位置，不测 NER；没有叠加第一轮中文规则或 MedAxis 未知/矛盾护栏。
- 隐私：真实 `extract_pii(lang="zh", confidence_threshold=0.5, preserve_whitespace=True, use_smart_merging=True)`；这是 SDK 模型与内置识别/合并链路的结果，不能归因于纯模型。保持默认临床保护开关。**未直接评分 native `deidentify`**：适配器只把检测到的原文位置转换为等长星号，以复用第一轮评分器；不修补或扩大 SDK 识别结果。
- 使用原封不动的 [24 条合成题集](catalog.json)，12 development / 12 evaluation，均非盲测、未经临床人员审核。没有真实患者数据、图片、数据库或生产调用。
- 模型下载需联网；推理进程启用 offline 环境与 local-only 配置，同时禁止 socket connect/connect_ex。实测 `network_attempts=[]`。这仅证明本实验进程的 Python socket 连接未发生，不是生产网络出口审计。
- NLI、brief、NER 为 `NOT_RUN`，没有将本地替代逻辑或已有准备包保留能力计成 SDK 收益。

## 冻结参数下的结果

逐例证据：[2026-09-30-openmed-sdk-2.5.0.json](results/2026-09-30-openmed-sdk-2.5.0.json)。退出码 0 表示数据/偏移/输出契约成立，**不表示隐私或临床质量通过**。

| 指标 | 第一轮中文规则原型 | 实际 SDK 链路 |
|---|---:|---:|
| 给定提及的断言状态正确 | 27/28 | 19/28（67.86%） |
| 遮蔽 gold 隐私字符 | 89/101 | 92/101（91.09%） |
| 漏遮隐私字符 | 12 | 9 |
| 误遮非隐私字符 | 0 | 23 |
| 数值、单位、持续时间片段保持 | 14/14 | 6/14（42.86%） |
| 指定引用语义支持 | 仅精确抽取门禁 | 未运行 NLI/brief |

全量语境输出中，5 个非当前肯定的提及被判 `present`，3 个不应直接否认的提及被判 `refuted`，另 1 个当前症状被判既往。不能将 MedAxis 待审核基线与这些预测的分数差异解读成临床准确率提升。

evaluation 分组：断言 12/16；隐私字符 28/37（75.68%）；误遮 14 字符；受保护片段保持 3/8。全量平均比这个分组更乐观，但两组都不是泛化验证。

CPU 全量调用的隐私链路中位数约 37.1 ms；此次模型加载约 4.8 s。首次 smoke 加载约 24.4 s，含导入等冷启动差异。短文本、单机、固定调用顺序，不能当作部署性能或内存容量评估。

## 关键失败及迁移取舍

| 样例 | 实际输出/问题 | 对 MedAxis 的含义 |
|---|---|---|
| D03 / E02 | 母亲糖尿病、父亲哮喘判为患者 `present` | 必须保留主体边界，不能自动写入患者当前病史 |
| D06 / D12 | “不清楚是否有药物过敏”“不记得哪天开始”判为 `refuted` | 不能覆盖现有未知事实语义 |
| D07 | 多轮发热矛盾按本条否认处理 | SDK 单条文本不理解历史矛盾；不能替换准备包协调机制 |
| E03 | 当前“咳嗽”受前半句既往肺炎影响，判 `historical` | 需核验中文语境作用范围 |
| D08 | “3天”和体温“39”输出 AGE，被遮蔽 | AGE 类识别需区分年龄、病程和测量数值 |
| E07 | “李晓雨今天咳嗽3天”整体输出 LASTNAME | 找到姓名同时吞掉症状；不能只看隐私召回率 |
| E09 | “合成市示例路99号”漏遮，病程“2天”被遮 | 既有泄漏又有病情损失 |
| D10 | 实验室描述中还有误遮，标注的两个检验值虽保持 | 14 个保护片段并未覆盖全部临床内容，不能据此宣称病情无损 |

可学习的是**多轴断言、原文偏移、来源/证据门禁、隐私识别与临床信息保护同时评估的工程机制**。本次失败说明 SDK 默认中文实现不能直接替代 MedAxis 业务语义，也不能以“91% 隐私召回”作为上传前安全保证。

后续如进入改进，应先独立冻结未见中文测试集、明确隐私类型与保留标准、保留未知/矛盾护栏，再实验主体识别、范围切分和 AGE/姓名误检保护。每项同时比较泄漏与病情损失。本轮没有调阈值凑分，没有实现生产适配。

## 验证与复跑

在 MedAxis 根目录执行，已有实验环境和校验模型是前置条件：

```powershell
$py = '.ai/tasks/2026-09-30-openmed-transfer/openmed-venv/Scripts/python.exe'
& $py -m unittest discover -s evals/openmed-transfer -p 'test*.py' -v
& $py evals/openmed-transfer/run_sdk_eval.py --context-only --smoke --output .ai/tasks/2026-09-30-openmed-transfer/context-rerun.json
& $py evals/openmed-transfer/run_sdk_eval.py --smoke --output .ai/tasks/2026-09-30-openmed-transfer/model-smoke-rerun.json
& $py evals/openmed-transfer/run_sdk_eval.py --output .ai/tasks/2026-09-30-openmed-transfer/sdk-full-rerun.json
& $py .ai/tasks/2026-09-30-openmed-transfer/check_artifacts.py
```

实际已执行：19 项单元测试、5 例 context smoke、24 例 context full、5 例 model smoke、24 例 SDK full，均 exit 0。独立人工语义/临床复核仍未执行，见 `.claude/manual-test-openmed-transfer.md`。下载首次提前 EOF 导致大小断言失败；续传后全部资产校验成功。环境和模型在忽略的任务目录中，约 2.25 GB 模型资产及另计依赖/cache；未自动清理。

收尾 artifact 检查 exit 0：新旧源码哈希匹配，24 例 SDK 重评分和分组汇总一致，未运行能力标记明确。两个子代理独立只读审查未在等待窗口内收敛，催收后中断；不记为审查通过。主线程自审 SDK 调用/协议转换、结果归因、泄漏与误删计量，当前没有已知执行契约错误；专业语义与泛化验证仍为未验证。

停用只需停止运行实验命令，没有生产接线、配置或持久化需要回滚。历史结果保留，不覆盖第一轮。[第一轮结果](RESULTS.md)只代表手写规则实验。
