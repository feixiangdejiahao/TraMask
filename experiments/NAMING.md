# 实验目录命名

本分支的主题为 `behavioral_masking`、`failure_analysis` 和 `benchmark_datasets`。

运行目录使用 `YYYYMMDD_<研究描述>[_nNN]_rNN`。既有运行沿用当前名称。实际输出位于 `results/<主题>/<运行名>/`，设置、分析及入口位于 `experiments/<主题>/`。

`experiments/<主题>/results/` 与 `experiments/pilots/` 中的链接是读取别名，同一材料只计一次。主要 Pilot 登记于 `pilot_catalog.json`，结果目录登记于 `runs.json`，逐任务入口登记于 `pilots/tasks.tsv`。

研究记录放在 `research/<研究名>_<日期>/`。保留既有证据内容；新的分析和执行使用新记录。历史地址通过 `results/path_map.json` 解析。
