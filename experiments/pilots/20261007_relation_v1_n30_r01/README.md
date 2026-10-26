# 关系方法 v1：30 项检测与补测

统一名称：`20261007_relation_v1_n30_r01`。本目录只提供读取入口。原始数据位于 [results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01)。

30 个 trial；自动提取、模型检测和测试生成；后续按补丁差异重新评价。

修复相关的检测与补测。当前固定目标使用 T08 修订后的 v5。

## 读取顺序

1. [实验报告](../../reports/docs/archive/20261008_benchmark_guided_gap_targets_n30.html)：先了解设置和评价范围。
2. [current_summary.json](current_summary.json)：读取当前统计。
3. [protocol.json](protocol.json)：核对设置、预算和输入边界。
4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。
5. [artifacts/](artifacts/)：查看完整原始目录。

## 文件对应关系

| 本目录名称 | 原始文件 |
|---|---|
| `protocol.json` | [results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/protocol.json](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/protocol.json) |
| `active_evaluation.json` | [results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/active_evaluation.json](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/active_evaluation.json) |
| `current_summary.json` | [results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/summary.json](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/summary.json) |
| `review.json` | [results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/review.json](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/review.json) |
| `reference_targets.json` | [results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/combined_targets.json](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/combined_targets.json) |
| `case_list.json` | [results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/cases.json](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/cases.json) |

`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。这些校验值只核对材料版本，不证明实验结论。

## 相关材料

- [当前口径：T08 修订说明](../../reports/docs/20261010_behavioral_gap_evaluation_revision_t08.html)
- [原样差分执行与静态判断](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/gold_comparison_v1/summary.json)
- [当前漏检诊断](../../../results/behavioral_gap_augmentation/20261007_relation_v1_n30_r01/benchmark_reverse_v5/diagnosis_summary.json)

## 阅读时区分

- 原运行根目录的 summary.json 是早期口径。先读本入口的 current_summary.json。
- 当前固定目标共 22 项。原报告的 23 项和旧预标注的 41 项不能混作同一分母。
- review.json 检查从失败与补丁差异推导的目标。原方法输出和动态记录仍在 artifacts/ 中。
- 这些 pilot 没有测量修复后的 resolution rate。
- 静态语义判断与动态差分执行按原始记录分别读取。

任务命名空间：`deepswe_pilot30`。本索引包含 30 个案例。不同命名空间中的短 ID 不应直接合并。
