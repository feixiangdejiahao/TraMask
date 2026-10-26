# 实验结果总览

先读 [11 轮主要 pilot](pilots/README.md)。按任务查找时，使用 [跨轮任务索引](pilots/tasks.tsv)。例如，筛选 `case_id=T13` 可以找到该任务在不同轮次中的输入、输出和评价文件。

查看全部历史结果时，打开 [全部结果目录](INVENTORY.md) 或 [可搜索索引](index.html)。索引按真实路径去重。一个目录的多个符号链接只对应一份数据。

## 目录分工

| 位置 | 内容 |
|---|---|
| `pilots/<统一名称>/` | 主要 pilot 的标准读取入口。包含说明、文件映射和任务索引。 |
| `<主题>/results/` | 指向 `results/<同名主题>/` 的单个链接。 |
| `<主题>/research/` | 方案、分析、协议和历史记录。 |
| `../results/<主题>/<运行名>/` | 实验结果的实际存放位置。 |
| `../prototypes/` | 历史原型代码。 |
| `../research/` | 观察研究、方法讨论和分析记录。 |
| `reports/` | 本地链接已更新的报告阅读副本。原文仍在原归档位置。 |
| `maintenance/` | 整理前的备份、路径清单和检查记录。 |

## 统一命名

完整规则见 [目录和文件命名规范](NAMING.md)。主题名称在 `experiments/` 与 `results/` 中一致。主要 pilot 使用 `YYYYMMDD_<研究内容>_n<案例数>_r<运行版本>`。例如：

```text
pilots/20261016_validation_evolution_n12_r03/
```

日期沿用实验的日期标识。`n12` 表示 12 个案例。`r03` 对应原运行目录的第三版，不表示第三次模型重复。算法版本写在主题中，例如 `relation_v2`。索引中的名称不修改历史协议里的版本标识。

每个 pilot 入口使用以下名称。某轮没有对应材料时，不创建该文件。

| 名称 | 含义 |
|---|---|
| `README.md` | 实验设置、评价范围、相关补跑及阅读顺序。 |
| `manifest.json` | 原目录、报告、文件映射和引用文件的哈希。 |
| `protocol.json` | 该轮原始实验协议。 |
| `case_list.json` | 原始案例清单；早期实验可能指向包含案例的 `prepared.json`。 |
| `current_summary.json` | 当前采用的统计文件。 |
| `review.json` | 对应的逐项审阅；具体范围见该轮说明。 |
| `active_evaluation.json` | 原实验保存的当前评价指针。 |
| `supplement_summary.json` / `supplement_review.json` | 追加判断或补充设置的结果。 |
| `tasks.tsv` | 按任务查找各类材料。表中路径相对仓库根目录。 |
| `artifacts/` | 完整原始目录。 |

JSON 入口和 `artifacts/` 是符号链接，不是副本。不要通过这些入口修改冻结材料。报告入口指向 `reports/` 中的阅读副本。本地链接已更新，原报告内容保持不变。

## 区分运行类型与评价版本

目录清单分为主要 pilot、已停止的技术尝试、输入准备、实现检查和历史支撑材料。只有存在停止记录时，清单才将运行标为已停止。正式运行中的失败输出仍保留在该轮结果中。

30 项 v1、v2、v3 实验的当前评价来自各自的 `active_evaluation.json`。其中固定目标已按 T08 修订。旧的 23 项、旧预标注的 41 项和当前 22 项不能混用。

v3 检测的原预算与追加判断分开。12 项实验的合并汇总包含第五个补充设置。主设置审阅和补充设置审阅分别提供。

跨实验比较时，先核对案例集合、判断标准、预算和重复次数。缺口检测、测试生成、动态差分和 resolution rate 是不同结果。目录整理不重新判定这些结果。

## 查找和读取

`runs.json` 和 `runs.tsv` 覆盖结果根目录及已知准备检查目录。它们不把每个任务子目录都计为一轮实验。完整子目录保留在原始输出中。

`pilots/tasks.tsv` 提供跨轮任务索引。`namespace` 区分早期 P/N 案例和后期 T01–T30。`artifacts` 包含同一案例的多个目录，以分号分隔。`summary`、`review` 是所在轮次的汇总入口，不是单个任务的成绩。

可以在仓库根目录执行：

```bash
# 查看 T13 在各轮实验中的位置。
python3 - <<'PY'
import csv
from pathlib import Path
with Path("experiments/pilots/tasks.tsv").open() as stream:
    for row in csv.DictReader(stream, delimiter="\t"):
        if row["namespace"] == "deepswe_pilot30" and row["case_id"] == "T13":
            print(row["pilot_id"], row["artifacts"], row["review"], sep="\n")
PY

# 重建索引。只读实验数据，不调用模型或执行测试。
python3 scripts/build_experiment_index.py

# 检查引用材料、当前评价凭据和索引是否一致。
python3 scripts/build_experiment_index.py --check
```

## 新增实验

新运行放在 `results/<主题>/<运行名>/`。通过 `experiments/<同名主题>/results/` 访问的是同一位置。运行名采用上述格式。每轮使用新目录。协议放在 `protocol.json`，案例清单放在 `cases.json`，评价放在 `evaluation/`。

新设置、技术重启和评价修订分别记录。不要覆盖原输出。出现新的当前评价时，更新该运行的 `active_evaluation.json`，并保留原评价。

主要 pilot 在 `pilot_catalog.json` 登记设置、实际目录、报告和相关材料。登记后运行索引脚本。脚本扫描同名主题的结果，并按真实位置去重。新增主题在 `directory_layout.json` 的 `topics` 中登记。

`legacy_catalog_20261007.json` 保留 2026-10-07 的 421 项历史归档映射。当前读取入口使用 `runs.json` 和 `pilot_catalog.json`。不要在旧迁移清单中补写新实验。

## 整理记录

本次统一了主题名、运行名和历史原型代码名，并移动了实际结果。旧根目录名不再保留。旧路径见 [映射表](../results/path_map.tsv)，核验见 [目录迁移检查](maintenance/20261020_directory_rename/verification.json)。

前一轮只建立读取入口，其记录保存在 [前一轮检查](maintenance/20261020_result_layout/verification.json)。本次没有重新评分、调用模型或重跑 benchmark。
