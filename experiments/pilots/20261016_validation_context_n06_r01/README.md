# 六任务原验证范围引导搜索

统一名称：`20261016_validation_context_n06_r01`。本目录只提供读取入口。原始数据位于 [results/validation_context_augmentation/20261016_validation_context_n06_r01](../../../results/validation_context_augmentation/20261016_validation_context_n06_r01)。

6 个任务；源码、历史、原验证范围、无执行反馈四组；各重复 2 次，共 48 份正式输出。

缺口检测与补测；区分动态差分与静态语义依据。

## 读取顺序

1. [实验报告](../../reports/docs/20261016_validation_context_pilot_n06.html)：先了解设置和评价范围。
2. [current_summary.json](current_summary.json)：读取当前统计。
3. [protocol.json](protocol.json)：核对设置、预算和输入边界。
4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。
5. [artifacts/](artifacts/)：查看完整原始目录。

## 文件对应关系

| 本目录名称 | 原始文件 |
|---|---|
| `protocol.json` | [results/validation_context_augmentation/20261016_validation_context_n06_r01/protocol.json](../../../results/validation_context_augmentation/20261016_validation_context_n06_r01/protocol.json) |
| `current_summary.json` | [results/validation_context_augmentation/20261016_validation_context_n06_r01/evaluation/summary.json](../../../results/validation_context_augmentation/20261016_validation_context_n06_r01/evaluation/summary.json) |
| `review.json` | [results/validation_context_augmentation/20261016_validation_context_n06_r01/evaluation/review.json](../../../results/validation_context_augmentation/20261016_validation_context_n06_r01/evaluation/review.json) |
| `case_list.json` | [results/validation_context_augmentation/20261016_validation_context_n06_r01/cases.json](../../../results/validation_context_augmentation/20261016_validation_context_n06_r01/cases.json) |

`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。这些校验值只核对材料版本，不证明实验结论。

## 相关材料

- [完成情况](../../../results/validation_context_augmentation/20261016_validation_context_n06_r01/evaluation/completion.json)
- [目录查询修复复测](../../../results/validation_context_augmentation/20261016_validation_context_n06_r01/query_recovery)

## 阅读时区分

- 查询修复复测与正式 48 份输出分开。
- 这些 pilot 没有测量修复后的 resolution rate。
- 静态语义判断与动态差分执行按原始记录分别读取。

任务命名空间：`deepswe_pilot30`。本索引包含 6 个案例。不同命名空间中的短 ID 不应直接合并。
