> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/semantic_edit_transport_fix_20260929.md) · [旧路径映射](../../../results/path_map.tsv)

# 保证模型修订的断言实际进入执行

本轮独立评价在 fresh v2 的 N04 发现一个实现问题：记录中的三个 oracle 已改为拒绝非法写入并检查回滚，实际发射的测试仍保留成功写入的旧断言。旧测试运行 PASS 不能说明新 oracle 通过。

## 原因与通用修复

组合候选保存两份编辑视图：`edits` 是即将物化的编辑，`program_edits` 是插桩前的快照。模型在 `edits` 追加期望修改后，旧插桩代码无条件取 `program_edits`，因此丢失了新增修改。

现在未插桩候选以 `edits` 为准；重复插桩时才恢复原快照，并合并随后追加的期望修改。已经包含探针前缀的断言仍使用快照中的纯断言，避免重复插入探针。输入、调用和期望都不因测试名称或案例 ID 而特殊处理。

首个修复为 commit `0d0bcac`。进一步独立审查发现，先插桩、再做语义修订的 API 调用顺序也可能丢失新期望，现已补上这一顺序的回归。当前相关测试 **45 passed**，其中12项通过真实 clone、probe 和 Python 执行，交叉检查：新回复/缓存重放、正确/错误被测实现，以及语义修订先后与探针位于断言边界的情况。原控制通过；正确实现通过新断言，错误实现失败，重复插桩仅产生一次事件。

## 实际实验影响

四个统一 campaign 当时已有的128个语义修订中，raw→instrumented 编辑审计发现125个保留、3个丢失，丢失均位于 fresh v2 的 N04 round 1。这个审计阶段本身不证明最终原生执行结果。[审计 v2](../../../results/program_relation_search/program_relation_search_20260929/evaluation/semantic_edit_transport_audit_v2.json)纠正了 v1 的 case/round 路径索引，原始材料保留。

用新代码重新发射并执行原 N04 round 1 全部8个候选，没有请求模型，也没有按评价标签筛选候选。三个 oracle 的拒绝写入断言均实际进入执行，并在当前实现返回成功时失败。其中两条的全部来源控制通过、完整 oracle 独立确认成立；另一条有额外 donor control 失败，仍不算合格检出。

这是修复后的补充运行，不回填 frozen fresh v2 的统一成绩。进一步的调用顺序修复对这8个候选的完整插桩产物逐项一致，因此不重复运行相同材料。

- [独立执行评价](../../../results/program_relation_search/program_relation_search_20260929/evaluation/semantic_emission_fix_v1/checkpoint_01.json)
- [完整 oracle 依据](../../../results/program_relation_search/program_relation_search_20260929/evaluation/semantic_emission_fix_v1/oracle_validity_review_01.json)
- [后续修复材料等价性](../../../results/program_relation_search/program_relation_search_20260929/evaluation/semantic_emission_fix_v1/post_review_equivalence.json)

修复确保“声明生成的测试”和“实际运行的测试”一致；它不证明模型预期本身正确，也不增加核心搜索抽象的创新性。
