# 保留的 replay 与执行代码

原入口仍在 `scripts/run_context_recovery_pilot1.py`；本目录保存本轮代码快照和 19 项本地回归检查。原始 30 秒动作期限保留；replay 结果通过独立的提交前源码状态校验后才能用于测试。

复用时显式提供新运行目录、cohort-local S 编号和中性checkpoint目录：

```sh
.venv/bin/python scripts/run_context_recovery_pilot1.py replay --run RESULTS_RUN --screen-id S001 --checkpoint-index experiments/behavioral_masking/replay_code/checkpoints_20261026_confirmed_gaps.json
.venv/bin/python scripts/run_context_recovery_pilot1.py validate --run RESULTS_RUN --screen-id S001
.venv/bin/python scripts/run_context_recovery_pilot1.py execute --plan PLAN_JSON --out NEW_OUTPUT_DIRECTORY
```

每次输出目录必须全新。输入清单使用完整base commit；原任务仅给短SHA时，保留原始配置并用原镜像Git唯一解析，记录来源。缓存只提供状态，不提供旧实验结论。
