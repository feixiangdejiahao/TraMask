# 组合测试研究与实验记录

最新设计见[程序分析辅助的组合测试推理](method_design.md)，最新固定配置见[2026-09-29本轮独立评价](relation_search_v3_evaluation.md)。统一新请求v3完成17例两轮，确认16/17，N05尚未取得合格目标见证；没有实现全部目标或验证issue resolution rate。修改后图、去重等负结果与主实验分开保存，不从不同配置挑选结果拼成17/17。

程序分析恢复测试、绑定、调用与断言依赖，构造候选并为局部预期推理提供源码。当前生成、运行反馈、模型预期修订与独立评价已连接；新writer反馈仍未集成在线搜索。2026-09-30已完成独立的有限oracle模板配对实验：相同50成员的完整正确预期为template20/50、expanded24/50，总token略增，没有新增目标检出。局部helper原型恢复8处调用绑定，新增期望参数端口为0。二者不改变冻结16/17主臂结果。此前[关系形状设计](relation_search_method.md)、[旧检查点](relation_search_checkpoint_20260929.md)与[判别上下文方案](distinguishing_context_method.md)保留历史，其旧成绩不能代替当前结果。[17条trajectory重审](trajectory_logic_20260928/README.md)和[STARS阅读](stars_abstraction_review.md)保留研究依据。

- [当前方法与能力边界](method_design.md)
- [本轮结果与消融](relation_search_v3_evaluation.md)、[oracle探索的实际贡献](oracle_exploration_contributions_20260929.md)
- [修改后依赖图](modified_observation_impact_v1.md)、[精确材料去重负结果](exact_oracle_material_v1.md)
- [有限oracle模板与配对评价](finite_oracle_template_critical_review_20260930.md)、[局部helper绑定原型](local_helper_evidence_20260930.md)
- [本轮五小时报告](relational_gap_timebox_20260928.md)：17 个已见 trial 的进展、逐例缺口、误报与泛化限制。
- [第六批独立评价](relational_gap_batch6_evaluation.md)：确认 N02、N07、N10，共 3/17。
- [第七批独立评价](relational_gap_batch7_evaluation.md)：完整源断言恢复消融确认 P2、N02、N07、N10，共 4/17，仍漏检 13/17。
- [第五批评价](relational_gap_batch5_evaluation.md)及[完整原断言恢复消融协议](relational_gap_v7_ablation_protocol.md)。
- [新增十条轨迹](expanded_trials_20260926/README.md)与[关系特征及论文依据](expanded_trials_20260926/abstraction.md)。
- [原七例人工分析](manual_case_analysis.md)及[人工标注](manual_annotations.json)。
- [2026 文献依据](literature_2026.md)。

第七批是评价后提出的统一断言恢复消融，结果单独报告。17 个 trial 对应 14 个 task，都是已见开发集；生成失败、测试失败、正确目标检出不能混为一谈。当前尚未穷尽评价误报，也没有 issue resolution rate 提升证据。

历史方法与负结果保留如下，不能与当前指标混用：

- [动作、观察与小期望变换](archive/method_design_action_observation_20260929.md)及[实验结果](semantic_transport_results.md)。
- [观察前沿检索](observation_frontier_method.md)、[检索实验](observation_frontier_experiment.md)及[事前约定](observation_frontier_plan.md)；检索命中不等于正确组合。
- [历史检索实验](anchor_retrieval_experiment.md)：旧完整方法双 Hit@10 为 0/7。
- [A 的适用性审查](anchor_applicability_audit.md)。
- [关系残差历史方案](archive/method_design_v2_residual.md)及[最初工程方案](archive/method_design_v1.md)。

按用户授权，必要的 issue、候选代码、已有验证及静态证据可发送到 `.env` 指定的 provider，当前模型为 `deepseek-v4-flash`。隐藏 verifier、参考补丁及封存评价标签不进入生成或模型请求。第七批恢复消融没有新增模型请求。
