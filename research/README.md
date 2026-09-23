**组合测试研究与当前实现**

当前核心抽象是 **观察前沿**：按断言观察值的依赖足迹建立偏序，在有限预算内优先选择组合行为的观察入口。七个发现集 pilot 上，Test Hit@10 和 Assertion Hit@10 均达到 1；当前只完成已有 A 的检索，没有实现组合测试生成或 issue resolution 评价。

- [方法设计](method_design.md)：核心抽象、算法、P3 示例、论文依据和局限。
- [最新实验报告](observation_frontier_experiment.md)：逐例排名、消融、稳定性核验和 Git 版本。
- [事前约定及修订记录](observation_frontier_plan.md)：两轮开发的假设、证据和修复。
- [精简实验数据](experiments)：受 Git 管理的评价摘要。
- [历史检索实验](anchor_retrieval_experiment.md)：旧完整方法双 Hit@10 为 0/7 的负结果。
- [逐例人工分析](manual_case_analysis.md)及[人工标注](manual_annotations.json)：场景、oracle 缺口、依赖关系与组合问题。
- [A 的适用性审查](anchor_applicability_audit.md)：为什么 P6/P7 的旧测试入口不等于已有可继承 oracle。
- [2026 文献依据](literature_2026.md)：MR-Coupler 等论文 insight 与研究贡献边界。
- [历史关系残差方案](archive/method_design_v2_residual.md)及[最初工程方案](archive/method_design_v1.md)：保留设计演变，均不是当前排序实现。

全部分析本地执行，没有代码外发。七例已经用于方法发现，后续需要冻结算法并在未见 issue 上验证，不能把当前 7/7 解释为已证明泛化。
