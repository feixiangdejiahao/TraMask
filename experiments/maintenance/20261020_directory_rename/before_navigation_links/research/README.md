# 研究记录与历史材料

本目录保存观察分析、方法讨论和历史记录。读取 pilot 的结果时，先看[统一实验入口](../experiments/pilots/README.md)。按任务查找时，使用[跨轮任务索引](../experiments/pilots/tasks.tsv)。

## 目录分工

| 位置 | 用途 |
|---|---|
| `<研究名>_<日期>/` | 保存该轮分析、讨论及引用材料。 |
| [`history/`](history/README.md) | 整理前 355 个入口的分类索引。 |
| [`../experiments/`](../experiments/index.html) | 按主题查看实验设置和分析。 |
| [`../results/`](../results/README.md) | 按同名主题存放实际输出。 |
| [`../prototypes/`](../prototypes/README.md) | 历史原型代码。 |
| [`../docs/`](../docs/README.md) | 可阅读的研究报告。 |
| 本目录已有的 JSON、子目录和兼容链接 | 历史记录。内容保留；旧地址由路径映射解释。 |

新研究记录放入独立的主题目录。实验执行产物放在 `results/<主题>/`。`experiments/<同名主题>/results/` 指向同一位置。名称和读取入口见[实验管理说明](../experiments/README.md)。

## 接续研究时先看

1. [主要 pilot](../experiments/pilots/README.md)：确认实验设置、判断标准和当前评价版本。
2. [2026-10-19 独立审查](independent_review_20261019/independent_report.html)：问题抽象、方法建议和待做 pilot。建议不等于已验证效果。
3. [30 项任务的轨迹与程序关系分析](../docs/augmentation_trajectory_program_study30_20261010.html)：原始观察和分析范围。
4. [T08 统计修订](../docs/augmentation_t08_statistics_revision_20261010.html)：解释旧报告中 23 项目标与修订后 22 项目标的区别。
5. [全部报告](../docs/README.md)和[历史材料索引](history/README.md)：按需继续读取。

## 材料与结论

记录分析时，引用原始文件，并注明对应版本。历史结论不因目录整理而获得新的证据支持。验证缺口、原 patch 的错误、补测成功和修复后 resolution rate 分别记录。

## 本次整理

较早的一轮只调整研究入口。其[整理前说明](../experiments/maintenance/20261020_research_layout/before/research_README.md)、[文件清单](../experiments/maintenance/20261020_research_layout/before_inventory.json)和[校验结果](../experiments/maintenance/20261020_research_layout/verification.json)保留。

本次进一步修改了实验主题、结果目录和历史原型代码名称。见 [命名规范](../experiments/NAMING.md)、[旧路径映射](../results/path_map.tsv)和[目录迁移检查](../experiments/maintenance/20261020_directory_rename/verification.json)。原始记录内容保留。
