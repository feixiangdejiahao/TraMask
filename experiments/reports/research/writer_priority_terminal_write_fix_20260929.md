> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/writer_priority_terminal_write_fix_20260929.md) · [旧路径映射](../../../results/path_map.tsv)

# Writer priority：直接写入路径的通用修复

本修复接在封存 commit `0b8c556` 的 [generality 审查](writer_priority_generality_audit_20260929.md) 之后。该 commit 保存了5个结构测试及当时的负行为，包括“writer 内联后失去优先级”。没有修改此前封存的分析、执行结果或 frozen worktree。

## 修改

原实现只从调用路径的边收集异常前驱。操作方法直接写字段时，路径没有调用边，于是即使写入之前有显式 raise，也不会得到优先级。

现在 [`assertion_write_origin.py`](../../../prototypes/assertion_write_origin.py) 对具体 writer 复用现有 `_bypass_sites(module, method, node)`，记录该写入之前的语法 may-exit 位置；[`exception_write_priority.py`](../../../prototypes/exception_write_priority.py) 将这些终端 writer 前驱与原调用边证据一起检查。相同逻辑适用于直接写入及辅助方法中的写入，不检查仓库/API/字段名称，没有增加构造模板或模型步骤。

它仍是 **may 分析**：语法前驱可以不可达，异常类型和 q 可达性尚未证明；同一方法里的不同 writer 也没有完整 reaching-definition 区分。这个修复消除了已发现的直接 writer 缺口，不证明对任意程序重构完全不变。`try/except` 等框架适配边界以及动态分派边界保持原样。

## 回归

原等价性测试现在要求两种版本都得到优先级：

```text
apply: 可能raise → amount += 3
apply: 可能raise → commit: amount += 3
```

两者原 control 均通过，组合测试均在未修改的原断言失败。另增加直接及辅助两种 finally 控制：异常发生时写入仍完成，generated 原断言通过，静态分析均不提升优先级。

相关测试合计 **79 passed**，包含此次结构测试、既有 priority/集成、静态分析、实际写入观察、源 q 映射和本地 phase 执行回归。保留的死 raise、动态方法覆盖及 `try/except` 测试仍刻画未解决的边界，没有将它们改成不存在的问题。

## 固定8个池的源级比较

使用原 `candidate_inventory_v1` 的全部8个 Python 池和全部768个候选，源码与候选池 SHA 均与旧排序一致。重新计算 census 和 priority，没有读取目标/verdict，没有新 Docker 或模型调用。之后分别将新旧顺序交给相同的公平调度器，预算固定8。

| case | 池大小 | 原有优先证据候选 | 修复后 | 预算8选择变化 |
|---|---:|---:|---:|---|
| N01 | 93 | 15 | 15 | 无 |
| N02 | 195 | 136 | 136 | 无 |
| N03 | 103 | 0 | 0 | 无 |
| N04 | 48 | 0 | 0 | 无 |
| P1 | 90 | 0 | 0 | 无 |
| P2 | 89 | 0 | 0 | 无 |
| P3 | 90 | 0 | 0 | 无 |
| P4 | 60 | 0 | 0 | 无 |

8/8个池的完整排序及选中候选 ID 均不变。151个原已支持候选的解释证据有所增加，例如补充终端 writer 的前驱，或增加同一候选内另一个字段的 writer 路径；由于排序只用 boolean，这些增加没有改变顺序。这个结果不构成新的检错率提升，也无需重新解释此前固定预算执行实验的结果。

独立版本的材料：

- [新 census](../../../results/program_relation_search/program_relation_search_20260929/assertion_write_origin_census_terminal_v1/protocol.json)
- [新 priority](../../../results/program_relation_search/program_relation_search_20260929/exception_write_priority_terminal_v1/protocol.json)
- [逐候选及预算8比较](../../../results/program_relation_search/program_relation_search_20260929/writer_priority_terminal_comparison_v1/comparison.json)
- [比较汇总](../../../results/program_relation_search/program_relation_search_20260929/writer_priority_terminal_comparison_v1/summary.json)

修复的价值是减少一个可复现的结构依赖，而不是为了使现有 pilot 数字变好。后续若要扩大异常控制流或写入图的支持范围，应单独规定范围并做新的实验。
