> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../../research/expanded_trials_20260926/root_cases.md) · [旧路径映射](../../../../results/path_map.tsv)

# 独立筛查：跨接口与其他候选

## SQLite-utils：bulk UPDATE × 违反持久化 invariant

- Trial：[sqlite-utils-safe-import-checkpo__LraMgba](https://deepswe.datacurve.ai/data/v1.1/trials/sqlite-utils-safe-import-checkpo__LraMgba)。官方元数据 `model=deepseek-v4-flash`, `outcome=fail`，task=`sqlite-utils-safe-import-checkpoints`。原七例之外的新任务。
- 需求：`insert/upsert/bulk --safe-mode` 只有提交成功才退出0；失败要恢复完整前状态，bulk必须支持UPDATE。来源是该trial的 `instruction.md`。
- 真实验证 A：trajectory step **228** 的最终综合脚本创建持久化 `COUNT(*) = 1` invariant；safe insert第一行成功，插入第二行时断言 `r.exit_code != 0`、表仍只有一行。
- 真实验证 B：同一脚本调用 `bulk ... update t set name = :name where id = :id ... --safe-mode`，把名字one改成X；断言exit0、实际name变为X。此操作不改变COUNT，invariant即使完全不执行也会通过。该step输出 `ALL FINAL CHECKS PASSED`、returncode0。步骤229及之后还有常规pytest回归。
- 缺口：**bulk入口的写操作必须使某个已注册invariant为假**，并检查拒绝与回滚。验证A提供失败预期，B提供bulk UPDATE入口，但两者没有在同一操作及相关字段上联合。不能只用“调用过bulk，也注册过invariant”判定已覆盖。
- 候选代码根因：`model.patch:637`，bulk调用 `db._safe_operation(_bulk_execute, strict=False, table=None)`；`model.patch:1089–1090`，`_safe_operation` 仅当 `table is not None` 才调用 `validate_import_invariants`。因此bulk分支保留checkpoint却跳过validation。
- 公开失败：`[f2p] tests.test_safe_bulk_import.test_bulk_safe_mode_with_update`。先把age改为31/26成功；注册 `SELECT COUNT(*) = 0 FROM users WHERE age < 18` 后再UPDATE age=15，期望非零退出，实际exit0。失败发生在exit断言，因此官方此项尚未继续检查回滚；不能声称日志已证明全部后置状态。
- 最小判别方案：沿用bulk UPDATE脚本，令更新字段与invariant读取字段一致；输入跨过阈值，检查exit!=0及原行值保持。源失败用例与当前issue可独立给出“拒绝”的期望，无需从错误实现录制expected。
- 程序事实：两个接口都进入 `_safe_operation`，但bulk传入None改变下游guard；验证中的COUNT对name更新不敏感。这是**入口路径改变检查可达性 + 输入未激活观察差异**，不是普通语法拼接问题。
- 证据强度：公开历史轨迹通过、公开verifier失败、候选控制流及本轮真实CLI重放一致。其他三个官方失败涉及opaque invariant ID的表示/CLI兼容，不能把本条缺口说成trial唯一原因。
- 本地：[完整证据摘录](../../../../results/benchmark_datasets/expanded_trial_dataset_20260926/trials/sqlite-utils-safe-import-checkpo__LraMgba/selected_evidence.json)、[候选补丁](../../../../results/benchmark_datasets/expanded_trial_dataset_20260926/trials/sqlite-utils-safe-import-checkpo__LraMgba/model.patch)、[下载来源与哈希](../../../../results/benchmark_datasets/expanded_trial_dataset_20260926/trials/sqlite-utils-safe-import-checkpo__LraMgba/acquisition.json)。

本轮从 GitHub 下载指定基线 `8d74ffc93292c604d5827e2b44fffedca0c28c19`，只应用候选补丁，建立独立 Python 3.10 venv，调用真实 Click CLI；没有应用公开 verifier 或参考补丁。四格使用各自全新DB及同一个 age>=18 invariant：insert合法数据成功；insert非法数据拒绝并回滚；bulk合法UPDATE成功；**bulk非法UPDATE返回0，age实际变成15，事后验证invariant=false**。前三个对照通过，最后一个判别失败。这里“未回滚”由本轮直接测得，区别于公开测试提前停止后的未知状态。这不是官方镜像/完整suite重放。

代码：[replay_sqlite_combination.py](../../../../scripts/replay_sqlite_combination.py)。[结果](../../../../results/benchmark_datasets/expanded_trial_dataset_20260926/trials/sqlite-utils-safe-import-checkpo__LraMgba/local_replay/result.json)和[环境、输入、补丁哈希](../../../../results/benchmark_datasets/expanded_trial_dataset_20260926/trials/sqlite-utils-safe-import-checkpo__LraMgba/local_replay/manifest.json)可复核。

## 当前排除/待定记录

| Trial | 决定 | 依据 |
|---|---|---|
| bandit-incremental-cache-control__AcyMbR8 | 排除核心missing-combination | step42已运行warm-cache + JSON，检查stdout字节数为0；step43明确把空stdout解释为正确。公开失败要求可解析的JSON空results。这是已执行组合的规格/期望理解问题。 |
| numba-stencil-boundary-modes__5hUkBtb | 排除核心missing-combination | step178已执行大偏移reflect并与自己定义的周期反射期望比较通过；公开需求却规定反射后仍越界时使用cval。这是错误参考计算，不可写成未组合reflect与大偏移。 |
| vulture-persistent-analysis-cach__QU4PHK4 | 暂不纳入 | 公开失败主要为扫描函数monkeypatch签名与新增cache_key不兼容，以及部分测试未出报告；尚无足够A/B独立验证→组合遗漏的证据。 |
| kombu-single-active-consumer-pri__poiufFM | 暂不纳入 | 唯一失败为non-SAC状态返回dict或None的契约差异；尚不能证明是组合验证缺口。 |
| psd-tools-blend-range-api__E8P7EN6 | 排除核心missing-combination | 主要失败为is_default实现成方法而verifier当布尔属性读取；属于接口表示差异，不能由失败名称推成组合缺口。 |
| aiomonitor-task-snapshots-diff__LofJ5Nc | 暂不纳入 | 公开失败是/api/snapshot/list与save路由404；尚无组合原因证据。 |

这些反例用于检验抽象边界，不计入十条正例。
