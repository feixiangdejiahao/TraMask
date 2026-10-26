# contract v6 独立模型重抽样

本轮对 P1–P3 使用了三次新的模型响应，随后统一生成并评价七个 pilot；没有按 case 挑选旧、新输出中的较优者。P1–P3 的新、旧 `request.json` 逐字节相同，模型均为 `gpt-6-astra`，三个新响应 ID 均不同，三个生成 predicate 的源码也均不同。原缓存为 `v6_retry`，新缓存为 `v6_repeat`。

以下为 SHA256 前 12 位；完整哈希、响应 ID、准入 ID 交并集及原始 usage 保存于 [contract_v6_model_repeat.json](experiments/contract_v6_model_repeat.json)。

| Case | 相同 request SHA | 旧 → 新 predicate SHA | 旧 → 新准入数 | 交集 / 并集 | Jaccard |
|---|---|---|---:|---:|---:|
| P1 | `1b26a6d9fedd` | `e186fae09a11` → `30e964be3d6b` | 98 → 98 | 98 / 98 | 1.0000 |
| P2 | `6494f7186fbf` | `1dbbe3c5accc` → `c00f10f8e052` | 90 → 90 | 90 / 90 | 1.0000 |
| P3 | `f1170a6998c8` | `26100f0b2cb3` → `bcef7d689bac` | 21 → 22 | 21 / 22 | 0.9545 |

三个被准入判断的 proposal 集合也分别相同，规模为 128、128、80。P3 唯一增加的义务是 `transport_79aefced27a59a5e`：把 `ESC[61:43;5u` 的 key representation 改为 `ESC[0:43;5:1u`，检查既有 `ctrl+plus` alias membership。该新增义务在候选和参考上均通过；所有共同义务的双侧状态、全部控制状态和报警集合保持不变。准入程序文本不同而行为接近，不代表模型输出完全可复现。

P1–P3 分别启动新的 candidate/reference Docker 执行，共六次。P4–P7 的 manifest 和所有生成文件与已复现版本逐字节相同，因此显式复用了先前执行；来源、哈希和理由记录于 `results/combination_testing/contract_v6_model_repeat/execution_reuse.json`。统一结果为：

| 指标 | 原 v6 | 独立重抽样 |
|---|---:|---:|
| 观察到的组合义务 | 263 | 264 |
| 控制 | 168 | 168 |
| Candidate alerts | 49 | 49 |
| Reference alerts | 3 | 3 |
| 已知目标检出 | 7/7 | 7/7 |
| 原始参考控制失败 | 9 | 9 |
| 受来源控制阻断的组合 | 22 | 22 |
| 缺失结果 / 执行错误 / oracle 前提错误 | 0 / 0 / 0 | 0 / 0 / 0 |

分 case 的 candidate/reference 报警仍分别为 P1 21/2、P2 1/1、P3 3/0、P4 4/0、P5 11/0、P6 1/0、P7 8/0。来源控制失败和阻断义务完整保留，没有通过删除失败样本改善结果。[独立语义审计](contract_v6_model_repeat_oracle_audit.md)确认旧报警及依据不变，新增项的契约支持仍待确认；不能仅凭双方通过就判定 oracle 正确。

这次新增模型调用为 **3 次**，共 **27,200 tokens**：输入 15,268、输出 11,932，服务报告的 cached input 为 15,259。原 v6 对应三次请求为 25,992 tokens。新请求各自耗时之和为 309.030 秒，不是并行请求的墙钟总耗时。服务返回了 token/billing usage，但没有货币金额或约定单价，因此实际 API 费用记录为 **未知，不是零**。测试生成和 Docker 执行阶段没有追加模型调用。

这是一轮相同请求下的独立重抽样，证明本次观察中目标检出与报警集合稳定，同时揭示了准入集合的一项变化。它不能估计一般模型随机性、未见案例泛化能力或任意重抽样下的失败概率。
