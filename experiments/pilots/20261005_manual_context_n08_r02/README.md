# 手选材料与 trajectory 对照

统一名称：`20261005_manual_context_n08_r02`。本目录只提供读取入口。原始数据位于 [results/trajectory_test_augmentation/20261005_manual_context_n08_r02](../../../results/trajectory_test_augmentation/20261005_manual_context_n08_r02)。

提取部分检查 17 条开发轨迹。生成部分使用 8 个手选案例，比较有无 trajectory 材料。

材料提取与测试生成；采用当时的验证缺口及错误检出口径。

## 读取顺序

1. [实验报告](../../reports/docs/20261005_manual_context_pilot_n08.html)：先了解设置和评价范围。
2. [current_summary.json](current_summary.json)：读取当前统计。
3. [protocol.json](protocol.json)：核对设置、预算和输入边界。
4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。
5. [artifacts/](artifacts/)：查看完整原始目录。

## 文件对应关系

| 本目录名称 | 原始文件 |
|---|---|
| `protocol.json` | [research/trajectory_gap_pilot_protocol_20261005.json](../../../research/trajectory_gap_pilot_protocol_20261005.json) |
| `current_summary.json` | [research/trajectory_gap_pilot_results_20261005.json](../../../research/trajectory_gap_pilot_results_20261005.json) |
| `case_list.json` | [results/trajectory_test_augmentation/20261005_manual_context_n08_r02/generation_v2/prepared.json](../../../results/trajectory_test_augmentation/20261005_manual_context_n08_r02/generation_v2/prepared.json) |

`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。这些校验值只核对材料版本，不证明实验结论。

## 相关材料

- [提取材料逐项检查](../../../research/trajectory_gap_pilot_extraction_manual_evaluation_20261005.json)
- [完成及修正记录](../../../research/trajectory_gap_pilot_closeout_20261005.json)

## 阅读时区分

- n08 指生成部分的 8 个案例。它不表示提取部分的规模。
- 主运行、格式修复和执行修复保留在各自目录。不能当作独立重复后合并统计。
- 这些 pilot 没有测量修复后的 resolution rate。
- 静态语义判断与动态差分执行按原始记录分别读取。

任务命名空间：`early_development`。本索引包含 8 个案例。不同命名空间中的短 ID 不应直接合并。
