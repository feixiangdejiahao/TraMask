# Pilot 实验读取入口

按轮次读取设置、当前评价和原始输出。此表不重新计算或合并成功率。按任务查询见 [tasks.tsv](tasks.tsv)。

| 统一目录名 | 实验 | 案例数 |
|---|---|---|
| [20261025_confirmed_gaps_pilot1_n88_r01](20261025_confirmed_gaps_pilot1_n88_r01/README.md) | Pilot 1：88条已确认组合缺口轨迹的上下文修复 | 88 |
| [20261025_context_recovery_pilot1_r01](20261025_context_recovery_pilot1_r01/README.md) | Pilot 1：Context-only Repair | 10 |
| [20261005_manual_context_n08_r02](20261005_manual_context_n08_r02/README.md) | 手选材料与 trajectory 对照 | 8 |
| [20261005_auto_augmentation_n06_r01](20261005_auto_augmentation_n06_r01/README.md) | 自动提取与测试补强 | 6 |
| [20261007_relation_v1_n30_r01](20261007_relation_v1_n30_r01/README.md) | 关系方法 v1：30 项检测与补测 | 30 |
| [20261008_input_diagnosis_n06_r01](20261008_input_diagnosis_n06_r01/README.md) | 六任务输入材料与执行反馈诊断 | 6 |
| [20261008_relation_v2_n30_r01](20261008_relation_v2_n30_r01/README.md) | 关系方法 v2：30 项检测与补测 | 30 |
| [20261009_relation_v3_detection_n30_r01](20261009_relation_v3_detection_n30_r01/README.md) | 关系方法 v3：30 项仅检测 | 30 |
| [20261009_program_guidance_n08_r02](20261009_program_guidance_n08_r02/README.md) | 八任务程序分析引导对照 | 8 |
| [20261010_trajectory_guidance_n08_r02](20261010_trajectory_guidance_n08_r02/README.md) | 八任务 trajectory 与程序计算对照 | 8 |
| [20261016_validation_context_n06_r01](20261016_validation_context_n06_r01/README.md) | 六任务原验证范围引导搜索 | 6 |
| [20261016_validation_evolution_n12_r03](20261016_validation_evolution_n12_r03/README.md) | 十二任务验证改动与观察反馈 | 12 |

## 观察研究与统计修订

这些材料帮助解释 pilot，不是新的算法效果实验。

- [211 个 trial 的组合验证缺口分析（独立中英双语）](../reports/docs/20261022_deepswe_failure_analysis_n211.html)：全部逐案审查，88 条直接支持、30 条有条件支持。独立 HTML 可离线阅读并切换语言；内嵌 issue、patch、evaluation/validation 对照和修复解释。未重跑修复，实际收益未知。 [数据](../../research/deepswe_counterfactual_review_20261021/summary.json)。
- [211 条失败记录的旧覆盖审查（冻结）](../../results/failure_analysis/20261021_counterfactual_gap_n211_r01/inputs/before_report/docs/deepswe_failure_manual_20261006.html)：历史覆盖口径，不要求关联实际 evaluation 失败；当前归因请看 2026-10-21 重审。 [数据](../../research/deepswe_failure_manual_20261006/completion_audit.json)。
- [单关系与多关系缺口统计](../reports/docs/archive/20261007_combination_relation_census_n211.html)：264 是历史覆盖缺口条目数，不是当前 evaluation 相关缺口数。原关系编码冻结，不是新算法效果实验。 [数据](../../research/combination_relation_census_20261007/census.json)。
- [30 项任务的 trajectory 与程序关系分析](../reports/docs/20261010_trajectory_program_analysis_n30.html)：原始观察与相关片段审读，不是新一轮检测成功率。 [数据](../../research/trajectory_program_search30_20261010/summary.json)。
- [T08 统计口径修订](../reports/docs/20261010_behavioral_gap_evaluation_revision_t08.html)：修订已有输出的评价，不是新生成或新检测实验。 [数据](../../research/t08_statistics_revision_20261010/summary.json)。

## 当前评价的选择

30 项 v1/v2/v3 实验从各自的 `active_evaluation.json` 读取当前口径。旧结果继续保留。v3 的原预算统计与追加判断统计分开。

12 项实验的入口使用 `combined_summary.json`，包含四个主设置及第五个补充设置。两份逐项审阅分别保留。

早期 P/N 案例与后期 T01–T30 使用不同命名空间。任务数量、目标数量、输出数量和命名测试数量也使用不同分母。

正式运行中出现的格式失败和未定结果仍属于该轮的原始记录。总目录只把有停止记录的尝试标为停用，不能据此删除不利结果。

完整目录见 [实验总览](../README.md)。
