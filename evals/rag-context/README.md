# chunk元信息与上下文实验

当前是**实验候选，未接入问诊**。完整覆盖改善，但新增无答案候选R42，不能默认上线。

在项目根目录用`backend/.venv/Scripts/python.exe`执行：

```powershell
# 复核已经保存的最终45题三组成绩和原文位置
backend/.venv/Scripts/python.exe evals/rag-context/verify.py .ai/tasks/2026-10-08-rag-context/full-final
# 验收器必须拒绝缺题、伪造摘录、成绩、隐藏回退和网络尝试
backend/.venv/Scripts/python.exe -m unittest discover -s evals/rag-context -p test_verify.py -v
# 新重放输出必须使用一个不存在的目录，不覆盖历史
backend/.venv/Scripts/python.exe evals/rag-context/replay.py --output .ai/tasks/2026-10-08-rag-context/acceptance-new
backend/.venv/Scripts/python.exe evals/rag-context/verify.py .ai/tasks/2026-10-08-rag-context/acceptance-new
```

`replay.py`复用阶段3实际召回ID、阶段2冻结原文，不调用Embedding/RAG搜索/数据库/模型。不改变金标和评分器，硬禁止httpx请求，800组必须逐题复现归档。三组分别隔离预算收益与邻接关系收益；排序仍用当前无供应商时的词匹配降级。

`inspect_metadata.py --output <新目录>`在本地Docker测试数据库只读核对Document/DocumentChunk，检查原文及窗口范围；非新的RAG或API效果测试。不读取患者、不写库。需Docker访问权限。

测试、原始结果、失败分支和执行源码在`.ai/tasks/2026-10-08-rag-context/`，文件被项目Git忽略，仍保留在本地；它们不是已发布数据集，也不能假设其他机器有这些资产。验收器反例测试依赖本地已冻结阶段2/3/4记录。

查看`docs/product/RAG_CONTEXT_ACCEPTANCE.md`了解本阶段验收边界及手工步骤。官方来源缺失不能由上下文算法解决。
