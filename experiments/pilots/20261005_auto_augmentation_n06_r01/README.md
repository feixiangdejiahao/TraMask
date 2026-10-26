# 自动提取与测试补强

统一名称：`20261005_auto_augmentation_n06_r01`。本目录只提供读取入口。原始数据位于 [results/trajectory_test_augmentation/20261005_auto_augmentation_n06_r01](../../../results/trajectory_test_augmentation/20261005_auto_augmentation_n06_r01)。

6 个案例；源码组与源码加 trajectory 组；每组 3 次尝试。

自动提取、缺口判断与测试生成；主实验和诊断补跑分列。

## 读取顺序

1. [实验报告](../../reports/docs/20261005_automatic_augmentation_pilot_n06.html)：先了解设置和评价范围。
2. [current_summary.json](current_summary.json)：读取当前统计。
3. [protocol.json](protocol.json)：核对设置、预算和输入边界。
4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。
5. [artifacts/](artifacts/)：查看完整原始目录。

## 文件对应关系

| 本目录名称 | 原始文件 |
|---|---|
| `protocol.json` | [research/automatic_augmentation_pilot_protocol_20261005.json](../../../research/automatic_augmentation_pilot_protocol_20261005.json) |
| `current_summary.json` | [research/automatic_augmentation_pilot_results_20261005.json](../../../research/automatic_augmentation_pilot_results_20261005.json) |
| `review.json` | [research/automatic_augmentation_judgment_audit_20261005.json](../../../research/automatic_augmentation_judgment_audit_20261005.json) |
| `case_list.json` | [results/trajectory_test_augmentation/20261005_auto_augmentation_n06_r01/prepared.json](../../../results/trajectory_test_augmentation/20261005_auto_augmentation_n06_r01/prepared.json) |

`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。这些校验值只核对材料版本，不证明实验结论。

## 相关材料

- [诊断补跑汇总](../../../research/automatic_augmentation_diagnostics_results_20261005.json)
- [输入和输出修复后的材料](../../../results/trajectory_test_augmentation/20261005_auto_augmentation_n06_r01/io_repair_v2)

## 阅读时区分

- 早期验证缺口口径不等于后来按原 patch 与 gold 差异定义的修复相关缺口。
- review.json 是缺口判断审阅。测试执行与其他审阅见汇总中的来源。
- 这些 pilot 没有测量修复后的 resolution rate。
- 静态语义判断与动态差分执行按原始记录分别读取。

任务命名空间：`early_development`。本索引包含 6 个案例。不同命名空间中的短 ID 不应直接合并。
