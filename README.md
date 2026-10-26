# TraMask 与组合验证缺口

本分支保留 211 条 DeepSWE 失败轨迹的组合缺口分析，以及 TraMask Pilot。完整清理前快照位于 `evidence-restart-20261004` 分支。

- [TraMask 论文](TraMask_Behavioral_Masking.pdf)
- [211 条轨迹：组合缺口与 evaluation 归因](docs/20261022_deepswe_failure_analysis_n211.html)
- [Pilot 1：88 条已确认组合缺口轨迹](experiments/pilots/20261025_confirmed_gaps_pilot1_n88_r01/README.md)
- [前轮 Pilot 1：10 个任务](experiments/pilots/20261025_context_recovery_pilot1_r01/README.md)
- [手工分析与独立复审](research/README.md)
- [实验及结果索引](experiments/README.md)
- [保留的 replay 代码和 checkpoint 索引](experiments/behavioral_masking/replay_code/)

原始轨迹、Verifier 结果及执行输出位于 `results/`；共用输入位于 `results/benchmark_datasets/`。历史路径通过 [path_map.tsv](results/path_map.tsv) 解析。后续实验新建运行目录，保留已有运行内容。
