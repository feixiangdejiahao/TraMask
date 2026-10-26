# Pilot 1：Context-only Repair

按固定顺序纳入 10 个独立任务，手工对齐 Agent Test 与实际失败的 Verifier Test，迁移 setup 条件，再执行错误 patch / 官方参考实现对照。

[报告](../../../results/behavioral_masking/20261025_context_recovery_pilot1_r01/report.html) · [结果数据](../../../results/behavioral_masking/20261025_context_recovery_pilot1_r01/report_data.json) · [筛选台账](../../../results/behavioral_masking/20261025_context_recovery_pilot1_r01/screening_ledger.json) · [协议](../../../results/behavioral_masking/20261025_context_recovery_pilot1_r01/protocol.json) · [两线程复核](../../../results/behavioral_masking/20261025_context_recovery_pilot1_r01/reviews/)

[复用 replay 与执行入口](../../../scripts/run_context_recovery_pilot1.py) · [保留的 replay 代码](../../behavioral_masking/replay_code/)
