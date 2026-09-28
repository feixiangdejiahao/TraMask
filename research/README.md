# 组合测试研究与实验记录

当前研究单位是带观察的关系 `(q, ρ)`：程序从已有验证恢复输入、对象和操作关系，构造新见证，并检查已有或受限修订的观察。实际实现仍有多个有界关系域，尚未实现统一完备的关系求解。

- [当前方法与能力边界](relational_gap_method_v2.md)
- [本轮五小时报告](relational_gap_timebox_20260928.md)：17 个已见 trial 的进展、逐例缺口、误报与泛化限制。
- [第六批独立评价](relational_gap_batch6_evaluation.md)：确认 N02、N07、N10，共 3/17。
- [第七批独立评价](relational_gap_batch7_evaluation.md)：完整源断言恢复消融确认 P2、N02、N07、N10，共 4/17，仍漏检 13/17。
- [第五批评价](relational_gap_batch5_evaluation.md)及[完整原断言恢复消融协议](relational_gap_v7_ablation_protocol.md)。
- [新增十条轨迹](expanded_trials_20260926/README.md)与[关系特征及论文依据](expanded_trials_20260926/abstraction.md)。
- [原七例人工分析](manual_case_analysis.md)及[人工标注](manual_annotations.json)。
- [2026 文献依据](literature_2026.md)。

第七批是评价后提出的统一断言恢复消融，结果单独报告。17 个 trial 对应 14 个 task，都是已见开发集；生成失败、测试失败、正确目标检出不能混为一谈。当前尚未穷尽评价误报，也没有 issue resolution rate 提升证据。

历史方法与负结果保留如下，不能与当前指标混用：

- [动作、观察与小期望变换](method_design.md)及[实验结果](semantic_transport_results.md)。
- [观察前沿检索](observation_frontier_method.md)、[检索实验](observation_frontier_experiment.md)及[事前约定](observation_frontier_plan.md)；检索命中不等于正确组合。
- [历史检索实验](anchor_retrieval_experiment.md)：旧完整方法双 Hit@10 为 0/7。
- [A 的适用性审查](anchor_applicability_audit.md)。
- [关系残差历史方案](archive/method_design_v2_residual.md)及[最初工程方案](archive/method_design_v1.md)。

按用户授权，必要的 issue、候选代码、已有验证及静态证据可发送到 `.env` 指定的 provider，当前模型为 `deepseek-v4-flash`。隐藏 verifier、参考补丁及封存评价标签不进入生成或模型请求。第七批恢复消融没有新增模型请求。
