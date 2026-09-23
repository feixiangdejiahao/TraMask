# contract v6 完整复现

使用当前统一 `combination_testing.experiment` 和已经冻结的 `results/combination_contracts/v6_retry` 缓存，在 `results/combination_testing/contract_v6_reproduction` 重新生成全部七个 pilot。七个 case 的 manifest 和测试源码均与 `contract_v6` **逐字节相同**；两轮保存的全部 Python 实现哈希也相同。

随后从新产物启动 14 次全新、无网络 Docker 执行，分别运行每个 case 的 candidate/reference，最多同时运行三个 case。使用当前 evaluator 重新评价两轮结果后，所有 case 的义务 ID、控制 ID 及状态、candidate/reference 测试状态、报警集合、目标匹配与完整评价行均相同，没有运行基础设施错误。旧的冻结产物和执行结果没有修改。

| Case | Candidate alerts | Reference alerts | 已知目标匹配 | 与原实验一致 |
|---|---:|---:|---|---|
| P1 | 21 | 2 | 是 | 是 |
| P2 | 1 | 1 | 是 | 是 |
| P3 | 3 | 0 | 是 | 是 |
| P4 | 4 | 0 | 是 | 是 |
| P5 | 11 | 0 | 是 | 是 |
| P6 | 1 | 0 | 是 | 是 |
| P7 | 8 | 0 | 是 | 是 |

合计观察到 263 个组合义务和 168 个控制，candidate alerts 为 49，reference alerts 为 3。参考实现另有 9 个原始控制失败；它们与组合报警分别统计。该复现证明冻结实现和执行结果稳定，**不把稳定性等同于 oracle 正确性，也不把三条 reference alerts 自动解释为真实误报**；其语义判断仍以独立 oracle 审计为准。

本次只复用缓存，没有新模型调用、模型 token 或模型 API 费用；14 次本地执行属于复现审计成本，不属于新模型推断实验。详细文件哈希、逐项一致性检查、报警 ID 和执行时间见 [contract_v6_reproduction.json](experiments/contract_v6_reproduction.json)。
