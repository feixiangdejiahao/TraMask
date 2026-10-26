# 目录和文件命名规范

目录名使用小写英文和下划线。名称说明内容或用途。日期、版本和案例数只使用已知事实。

## 三类目录

| 位置 | 统一称呼 | 保存内容 |
|---|---|---|
| `prototypes/` | 历史原型代码 | 旧算法实现及演示。原名为 `experimental/`。 |
| `experiments/` | 实验管理 | 设置、分析、报告入口和实验索引。 |
| `results/` | 实验结果 | 输入副本、模型输出、生成测试、执行记录和评价。 |

`experiments/<主题>/` 与 `results/<主题>/` 使用相同的主题名。前者的 `results/` 是指向后者的单个链接。数据只有一份。

```text
prototypes/statement_aligned_test_analogy_v03/   # 历史实现
experiments/test_analogy_generation/            # 设置与分析
results/test_analogy_generation/
  statement_aligned_test_analogy_v03/           # 对应历史结果

experiments/behavioral_gap_augmentation/        # 设置与分析
results/behavioral_gap_augmentation/
  20261007_relation_v1_n30_r01/                  # 一轮 pilot
experiments/pilots/20261007_relation_v1_n30_r01/ # 该轮读取入口
```

一个主题可以包含多个方法版本。一个原型也可以供多个实验复用。主题关系不表示代码与运行一一对应。主题清单保存在 [directory_layout.json](directory_layout.json)。

## 运行目录

新 pilot 使用 `YYYYMMDD_<研究内容>_n<案例数>_r<运行版本>`。例如 `20261016_validation_evolution_n12_r03`。`n12` 表示 12 个案例。`r03` 表示第三个运行版本，不表示第三次独立重复。独立重复次数写入协议。

没有案例数的检查使用 `YYYYMMDD_<用途>_check_rNN`。准备运行使用 `_preparationNN`。已停止的技术尝试使用 `_stopped`，并保存停止原因。不能只因成绩差而把正式运行改为已停止。

历史实验缺少日期时，使用 `<方法名>_vNN`。没有版本信息时，只保留方法名。不要补造日期或次数。早期 `P1` 等短案例目录改为 `p01_<项目>_<问题>`，同时保留内部原始案例 ID。

批次使用 `batch_01`。明确的阶段版本使用 `candidate_screening_v01` 或 `evaluation_v01`。不要用独立的 `v1`、`run1`、`final` 或 `tmp` 表示一轮新实验。

## 文件

新运行使用下面的固定名称。某项不适用时，不创建空文件。

| 名称 | 用途 |
|---|---|
| `README.md` | 设置、范围、状态和阅读顺序 |
| `protocol.json` | 输入边界、方法、预算、重复次数和版本 |
| `cases.json` | 案例清单 |
| `inputs/` | 实际使用的输入 |
| `runs/<case_id>/` | 每个案例的输出；独立重复另设 `repeat_01/` |
| `request.json`、`response.json` | 模型请求与原始响应 |
| `execution.json`、`stdout.log`、`stderr.log` | 执行命令、状态和输出 |
| `evaluation/<评价版本>/summary.json` | 该版统计 |
| `evaluation/<评价版本>/review.json` | 逐项审阅 |
| `active_evaluation.json` | 当前采用的评价文件及校验值 |

主要 pilot 的读取入口统一使用 `protocol.json`、`case_list.json`、`current_summary.json`、`review.json`、`tasks.tsv` 和 `artifacts/`。这些名称可以链接历史文件。它们不创建新实验，也不覆盖原评价。

现有运行内部的日志、源码、测试名、内容哈希文件和 JSON 字段保留原样。第三方仓库保留自己的目录结构。目录规范不要求重写这些证据。

## 旧路径

[path_map.tsv](../results/path_map.tsv) 提供旧路径到新路径的对应关系。[path_map.json](../results/path_map.json) 提供相同的机器可读数据。结果根目录只保留新名称。

```bash
python3 scripts/result_paths.py results/generic_v3/batch1
python3 scripts/result_paths.py experimental/generic_v3/generate.py
```

Python 分析脚本可调用 `scripts.result_paths.canonical_path(old_path)`。它按最长旧路径前缀转换地址，也支持仓库内的绝对路径。它不改写原始记录。

历史执行脚本可能仍保存旧默认参数或绝对路径。重新使用时，先转换路径，并写入新的运行目录。冻结协议中的源码校验值对应原实现。不能通过改写旧凭据来续写实验。

报告的原文保留。当前导航使用 `experiments/reports/` 中的阅读副本。副本只增加提示并更新链接。正文中的旧路径仍可用映射工具查询。

文档名使用日期、主题和文档类型。当前文档与归档文档的规则见 [docs/README.md](../docs/README.md)。归档原因记录在 `docs/catalog.json`。
