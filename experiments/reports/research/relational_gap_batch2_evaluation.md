> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_batch2_evaluation.md) · [旧路径映射](../../../results/path_map.tsv)

# Relational gap batch2：独立评价

本轮完整跑完 17 个 trial。固定目标 test 的静态召回为 **17/17**，真正生成正确组合并以通过的原测试为对照、触发对应目标缺陷为 **1/17（N10）**。其余 16 个目标仍未检出，不能把大量测试失败当成成功。

| 指标 | batch1 | batch2 |
|---|---:|---:|
| 固定目标 test 静态召回 | 15/17 | 17/17 |
| 独立确认目标缺陷检出 | 0/17 | 1/17 |
| 模型请求成功 | 34/34 | 34/34 |
| 整体协议接受的响应 | 9/34 | 34/34 |
| 获准候选 | 192 | 830 |
| 模型 token 总量 | 2,693,066 | 921,657 |

batch2 的 8,444 个冻结静态候选中，830 个获准；822 个有执行索引，582 个实际观察到对应测试结果。8 个获准候选未成功物化，其余未观察到结果的情况包括编译、收集或运行阻塞。获准候选仍覆盖固定目标 parent 的 14/17，实际观察到该 parent 衍生测试结果的仅 10/17。

评价明确拆开：静态选到原测试、候选确实包含目标组合、断言正确、原测试对照通过、生成测试失败、失败确属目标缺陷。N10 六项均有证据；`all_17_targets_proven` 为 false。

## N10 的成功证据

程序沿调用链 `ZodSchemer.parser(options) → itemZodParser(schema, options)` 找到字段默认值 `mode = 'put'`。它把已有 requiredIf 测试中的 `zod.parser({ mode: 'put' })` 变成 `zod.parser({})`，保留缺少条件必填字段时应抛出 `ZodError` 的原断言。无需手写目标输入或修改候选代码。

候选 `32dd7661b8b920895cff7c62` 实际失败：`expected function to throw an error, but it didn't`。同一 manifest 中的原测试对照 `gc_control_24dc1e3767c92c60f06d7c35` 通过。因此这不是恢复脚本错误、其他断言失败或错误 oracle。

证据：`batch2_emitted/N10/group_003/manifest.json`、对应生成文件、`batch2_runs/N10/group_003/normalized.json`；完整判断冻结在 `batch2_reviews_audited.json` 与 `batch2_evaluation.json`。

## 逐例结果

| Trial | 获准候选 | 观察到结果 | 获准中含目标 parent | 确认目标缺陷 |
|---|---:|---:|---|---|
| P1 | 58 | 58 | 否 | 否 |
| P2 | 30 | 30 | 是 | 否 |
| P3 | 43 | 43 | 是 | 否 |
| P4 | 28 | 26 | 是 | 否 |
| P5 | 36 | 10 | 否 | 否 |
| P6 | 41 | 29 | 是 | 否 |
| P7 | 61 | 55 | 是 | 否 |
| N01 | 64 | 27 | 是 | 否 |
| N02 | 52 | 37 | 是 | 否 |
| N03 | 60 | 55 | 是 | 否 |
| N04 | 62 | 62 | 是 | 否 |
| N05 | 50 | 44 | 是 | 否 |
| N06 | 58 | 0 | 是 | 否 |
| N07 | 52 | 0 | 是 | 否 |
| N08 | 19 | 14 | 否 | 否 |
| N09 | 64 | 54 | 是 | 否 |
| N10 | 52 | 38 | 是 | 是 |

## 误报与无效运行

323 个候选观察到测试失败；其中 272 个对应的原测试对照通过。独立逐例组合审查确认 1 个目标缺陷；另外抽查确认 4 个错误 oracle，267 个通过对照的失败尚未证明 oracle 正确，保留 unknown。这不是精确率统计，也不能用 4 比上一轮的 6 小来声称误报改善：两轮接受集合不同，而且只精查了部分非目标失败。

- P1 `q_8301e007b73f59fa6a996516`：Input is changed from a release sequence to Kitty 65;4u, whose omitted event type defaults to press. Retaining expected phase release is incorrect; generated output press is the correct behavior.
- P3 `q_517c4f5a13700a6c2d54bf84`：Explicit Key phase changes repeat to press while the selected assertion retains is_press is False. A press event must have is_press True.
- P3 `q_991881ef03cd64f53b636f0e`：The modifiers list now explicitly contains shift while the selected assertion retains shift is False. The observed True is correct.
- P3 `q_6760d017082cbe493e0bd21e`：The sequence changes from modifier code 2 (Shift) to modifier code 1 (none), while the selected expected modifiers remains (shift,). The observed empty tuple is correct.

编译/收集问题单独排除：N07 恢复的 Go 文件把空白标识符 `_` 重命名为普通变量，且部分版本重复定义测试；P5 原子化后出现未使用局部变量、运行无限循环；N05 出现 bool/string 选项类型替换；N06 候选把 Go nil 替成整数等，导致测试组编译失败。Python 历史脚本也有模块级断言失败、子进程改变目录后无法导入源码、历史版本不兼容等问题。所有这些都未计作缺陷检出。

生成器从未读取 target_census、手写 evaluator probe 或参考补丁。目标 identity 仅按源文件 provenance、明确的历史重命名和 script wrapper 映射匹配；没有通过名字猜测消除差异。运行对照只能匹配同一 execution manifest 中声明的 control。

## 复核命令

```bash
.venv/bin/python scripts/evaluate_relational_gap.py evaluate \
  --batch-root results/relational_gap_20260928/batch2 \
  --additional-batch-root results/relational_gap_20260928/batch2_retry \
  --emitted-root results/relational_gap_20260928/batch2_emitted \
  --reviews results/relational_gap_20260928/batch2_reviews_audited.json \
  --output /tmp/relational-gap-batch2-recheck.json
```
