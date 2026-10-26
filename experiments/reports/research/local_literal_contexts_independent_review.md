> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/local_literal_contexts_independent_review.md) · [旧路径映射](../../../results/path_map.tsv)

# 局部字符串变换独立审查

2026-09-24，只读审查 `experimental/local_literal_contexts.py` 及其五个单元测试。没有依据 pilot 目标修改生成代码，没有模型请求、被测程序执行或参考/隐藏材料访问。五个现有测试通过。

新增 [独立静态 toy](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/local_literal_review_v1/probe.py) 只把合成源码交给 corpus 构建与生成器，源码本身不执行。[结果](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/local_literal_review_v1/probe_result.json) 包含实际受审模块 SHA，避免后续修复覆盖证据。

## 需要修正或明确的两处边界

1. **调用端口未必已解析。** `generate` 直接按 `engine.slot_key` 分组；后者允许 `canonical=None` 的 `unknown_receiver_or_symbol`，退回文件路径和调用拼写。toy 中两个 source test 在 `obj=make_a()` 后调用 `obj.consume`，recipient 则在 `obj=make_b()` 后调用同名方法，两个工厂返回不同类。生成器仍给 recipient 迁入规则，记录的端口只是 `test_ports.py::obj.consume`。该候选可以明确称“未解析的同名端口语法假设”，但不能由此声称三个调用已经解析到同一 API。若算法要求已解析 API，应检查 resolution，不能只检查分组键相等。
2. **token 上限晚于相似度计算。** `learn` 拒绝超过 256 tokens 的值，但 `generate` 的 nearest 排序先对全部源值计算 `SequenceMatcher.ratio`，之后才调用 `learn`。toy 在 `max_attempts=1` 时，六次 similarity 调用收到超限串，最终零 transfer attempts、零产物。该证据不声称已经发生实际超时；它证明 transfer-attempt 预算不约束此前的相似度工作。可在排序前缓存/检查 token 长度，并单独限制规则学习工作量。

## 保留的正确边界

局部位置唯一、原例可重构和标点锚定是机械条件。它们不证明字段角色、有效语法、对象关系或 oracle 保持；当前 `semantic_status=unique_local_syntactic_match_only` 的措辞正确。插入 token 是源后例的固定 token，并不自动把其中与源前例相同的名字重新绑定到 recipient；这是表示能力与假设范围，不应误称为普遍的参数化变换证明。

现有测试已验证不同外围表示的局部编辑、重复锚点拒绝、过大/多片段变更拒绝、确定性与不修改 corpus、transfer-attempt 预算。上述新增风险涉及端口分辨率和预算之前的工作量，未使用任何 pilot 失败答案。

## 修复后原 toy 复核

根代理增加 producer 来源区分和相似度计算前的 token/char 上限后，独立评价者原样复制并重跑同一个 probe，没有增加或改变 toy 输入。两份 probe 的 SHA 均为 `587498d5113e131da7c6ecd7f1f7e9e8dd7fc1cecb45f13b369d125ab818bc18`。

| 检查 | 首次结果 | 修复后结果 |
|---|---:|---:|
| 不同工厂 receiver 间的同名端口迁移 | 1 | 0 |
| 481/485/485-token 三串在拒绝前进入相似度计算 | 6 次 | 0 次 |
| 超限串的实际 transfer attempts | 0 | 0 |

首次受审模块 SHA：`ae2f227908928d8aad7e730a4adb79b111cb8ea3801782e5fa541adac2fa4d89`。修复后受审 SHA：`3638e065c3249466636869d715109824ec759714770c513f1b28b168eda8c669`。新 [原样 probe](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/local_literal_review_v2/probe.py) 与 [结果](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/local_literal_review_v2/probe_result.json) 另存，旧文件保持不变。

这两个具体反例已不再复现。producer 来源仍是近似身份依据，并不证明运行时 receiver 类型、别名或语义相同；此次复核不把它扩大成完备的调用解析证明。没有重跑任何 pilot，也没有模型或参考访问。
