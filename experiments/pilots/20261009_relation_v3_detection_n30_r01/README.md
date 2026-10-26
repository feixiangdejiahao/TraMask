# 关系方法 v3：30 项仅检测

统一名称：`20261009_relation_v3_detection_n30_r01`。本目录只提供读取入口。原始数据位于 [results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01](../../../results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01)。

30 个 trial；改进候选条件、测试查询与材料表达；原预算和追加判断分别记录。

只检测缺口；没有生成或执行新补测。

## 读取顺序

1. [实验报告](../../reports/docs/archive/20261009_behavioral_gap_detection_v03_n30.html)：先了解设置和评价范围。
2. [current_summary.json](current_summary.json)：读取当前统计。
3. [protocol.json](protocol.json)：核对设置、预算和输入边界。
4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。
5. [artifacts/](artifacts/)：查看完整原始目录。

## 文件对应关系

| 本目录名称 | 原始文件 |
|---|---|
| `protocol.json` | [results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/protocol.json](../../../results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/protocol.json) |
| `review.json` | [results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/evaluation/t08_oracle_reclassification_v1/evaluation/target_review.json](../../../results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/evaluation/t08_oracle_reclassification_v1/evaluation/target_review.json) |
| `supplement_summary.json` | [results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/evaluation/t08_oracle_reclassification_v1/decision_recovery_v1/summary.json](../../../results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/evaluation/t08_oracle_reclassification_v1/decision_recovery_v1/summary.json) |
| `active_evaluation.json` | [results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/active_evaluation.json](../../../results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/active_evaluation.json) |
| `current_summary.json` | [results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/evaluation/t08_oracle_reclassification_v1/summary.json](../../../results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/evaluation/t08_oracle_reclassification_v1/summary.json) |
| `reference_targets.json` | [results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/combined_targets.json](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/combined_targets.json) |
| `case_list.json` | [results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/cases.json](../../../results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/cases.json) |

`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。这些校验值只核对材料版本，不证明实验结论。

## 相关材料

- [当前口径：T08 修订说明](../../reports/docs/20261010_behavioral_gap_evaluation_revision_t08.html)
- [当前漏检分类](../../../results/behavioral_gap_augmentation/20261009_relation_v3_detection_n30_r01/evaluation/t08_oracle_reclassification_v1/diagnosis_v1/summary.json)

## 阅读时区分

- current_summary.json 对应原预算；supplement_summary.json 对应追加判断。不能合并为相同预算的结果。
- 这些 pilot 没有测量修复后的 resolution rate。
- 静态语义判断与动态差分执行按原始记录分别读取。

任务命名空间：`deepswe_pilot30`。本索引包含 30 个案例。不同命名空间中的短 ID 不应直接合并。
