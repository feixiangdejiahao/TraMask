# 八任务 trajectory 与程序计算对照

统一名称：`20261010_trajectory_guidance_n08_r02`。本目录只提供读取入口。原始数据位于 [results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02](../../../results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02)。

8 个任务；代码材料、历史材料、模型行为计划、程序计算四组；各重复 2 次，共 64 次检测。

仅检测和静态审阅；没有生成或执行新补测。

## 读取顺序

1. [实验报告](../../reports/docs/20261010_trajectory_guidance_pilot_n08.html)：先了解设置和评价范围。
2. [current_summary.json](current_summary.json)：读取当前统计。
3. [protocol.json](protocol.json)：核对设置、预算和输入边界。
4. [tasks.tsv](tasks.tsv)：按任务查找输入、输出和评价。
5. [artifacts/](artifacts/)：查看完整原始目录。

## 文件对应关系

| 本目录名称 | 原始文件 |
|---|---|
| `protocol.json` | [results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/protocol.json](../../../results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/protocol.json) |
| `current_summary.json` | [results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/evaluation/summary.json](../../../results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/evaluation/summary.json) |
| `review.json` | [results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/evaluation/semantic_review.json](../../../results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/evaluation/semantic_review.json) |
| `case_list.json` | [results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/cases.json](../../../results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/cases.json) |

`manifest.json` 记录本入口的路径映射和所引用文件的 SHA-256。这些校验值只核对材料版本，不证明实验结论。

## 相关材料

- [输入绑定检查](../../../results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/evaluation/binding_format_review.json)
- [材料提取检查](../../../results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r02/evaluation/extraction_review.json)
- [已停止的 v1 技术尝试](../../../results/behavioral_gap_augmentation/20261010_trajectory_guidance_n08_r01_stopped/preflight_closeout.json)

## 阅读时区分

- preparation1、preparation2 只保存准备材料。v1 因接口格式问题停止。主结果使用 v2。
- 这些 pilot 没有测量修复后的 resolution rate。
- 静态语义判断与动态差分执行按原始记录分别读取。

任务命名空间：`deepswe_pilot30`。本索引包含 8 个案例。不同命名空间中的短 ID 不应直接合并。
