# 十二任务验证改动与观察反馈

统一名称：`20261016_validation_evolution_n12_r03`。本目录只提供读取入口。原始数据位于 [results/validation_history_augmentation/20261016_validation_evolution_n12_r03](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03)。

12 个任务；4 个主设置和 observation_view 补充设置；各重复 2 次，共 120 次任务运行。

检测与补测；按候选数量分列；区分动态差分与静态语义依据。

## 读取顺序

1. [实验报告](../../reports/docs/20261016_validation_history_pilot_n12.html)：先了解设置和评价范围。
2. [current_summary.json](current_summary.json)：读取当前统计。
3. [protocol.json](protocol.json)：核对设置、预算和输入边界。
4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。
5. [artifacts/](artifacts/)：查看完整原始目录。

## 文件对应关系

| 本目录名称 | 原始文件 |
|---|---|
| `protocol.json` | [results/validation_history_augmentation/20261016_validation_evolution_n12_r03/protocol.json](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/protocol.json) |
| `supplement_review.json` | [results/validation_history_augmentation/20261016_validation_evolution_n12_r03/observation_view/evaluation/review.json](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/observation_view/evaluation/review.json) |
| `active_evaluation.json` | [results/validation_history_augmentation/20261016_validation_evolution_n12_r03/active_evaluation.json](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/active_evaluation.json) |
| `current_summary.json` | [results/validation_history_augmentation/20261016_validation_evolution_n12_r03/evaluation/combined_summary.json](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/evaluation/combined_summary.json) |
| `review.json` | [results/validation_history_augmentation/20261016_validation_evolution_n12_r03/evaluation/review.json](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/evaluation/review.json) |
| `case_list.json` | [results/validation_history_augmentation/20261016_validation_evolution_n12_r03/cases.json](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/cases.json) |

`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。这些校验值只核对材料版本，不证明实验结论。

## 相关材料

- [补充设置协议](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/observation_view/protocol.json)
- [仅四个主设置的统计](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/evaluation/summary.json)
- [完整性检查](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/evaluation/completion_audit.json)
- [调用和费用记录](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r03/evaluation/accounting.json)
- [v1 停止原因](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r01_stopped/stopped.json)
- [v2 停止原因](../../../results/validation_history_augmentation/20261016_validation_evolution_n12_r02_stopped/stopped.json)

## 阅读时区分

- current_summary.json 指向 combined_summary.json，包含第五个补充设置。
- review.json 覆盖四个主设置；supplement_review.json 覆盖第五个设置。
- v1、v2 是停用尝试。不可并入 v3 的正式成功率。费用核算按原报告另列。
- 这些 pilot 没有测量修复后的 resolution rate。
- 静态语义判断与动态差分执行按原始记录分别读取。

任务命名空间：`deepswe_pilot30`。本索引包含 12 个案例。不同命名空间中的短 ID 不应直接合并。
