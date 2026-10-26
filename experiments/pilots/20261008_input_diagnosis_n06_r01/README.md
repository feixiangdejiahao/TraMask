# 六任务输入材料与执行反馈诊断

统一名称：`20261008_input_diagnosis_n06_r01`。本目录只提供读取入口。原始数据位于 [results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01](../../../results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01)。

T10、T13、T17、T20、T24、T28；比较原输入、人工材料、程序条件和执行反馈四组。C/D 共用首轮。

诊断材料和反馈的作用；包含人工选材。

## 读取顺序

1. [实验报告](../../reports/docs/20261008_input_evidence_diagnosis_n06.html)：先了解设置和评价范围。
2. [current_summary.json](current_summary.json)：读取当前统计。
3. [protocol.json](protocol.json)：核对设置、预算和输入边界。
4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。
5. [artifacts/](artifacts/)：查看完整原始目录。

## 文件对应关系

| 本目录名称 | 原始文件 |
|---|---|
| `protocol.json` | [results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/protocol.json](../../../results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/protocol.json) |
| `current_summary.json` | [results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/summary.json](../../../results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/summary.json) |
| `review.json` | [results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/review.json](../../../results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/review.json) |
| `case_list.json` | [results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/cases.json](../../../results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/cases.json) |

`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。这些校验值只核对材料版本，不证明实验结论。

## 相关材料

- [输入材料差异](../../../results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/material_comparison.json)
- [输出预算补跑](../../../results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/budget_recovery)
- [候选问题修订](../../../results/behavioral_gap_augmentation/20261008_input_diagnosis_n06_r01/neutral_candidate_amendment.json)

## 阅读时区分

- 这轮是诊断对照，不能直接当作全自动算法的端到端效果。
- 这些 pilot 没有测量修复后的 resolution rate。
- 静态语义判断与动态差分执行按原始记录分别读取。

任务命名空间：`deepswe_pilot30`。本索引包含 6 个案例。不同命名空间中的短 ID 不应直接合并。
