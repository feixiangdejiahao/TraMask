# 遗漏组合测试：源码类比原型

从已有测试的输入、准备步骤和断言中学习变化，用 `A : B :: C : D` 构造尚未出现的组合测试。程序负责源码提取、绑定、对应关系及代码生成；模型只对固定候选作语义筛选。当前模型为 **`deepseek-v4-flash`**，通过 `.env` 中的 provider 调用。

**当前通用版本尚未确认检出七个 pilot 中的目标缺陷。** 旧领域算子原型曾达到 7/7，但算子是在已知这些缺陷之后设计的，存在过拟合，不能作为通用方法的结果。旧文档与运行方式已[归档](research/archive/README_pilot.md)，代码标签为 `combination-v0.1-pilot`。

- [当前方法：测试类比方格](research/method_design.md)
- [跨版本实验、失败与模型成本](research/generic_generation_cross_version_results.md)
- [实验评价约定](research/generic_generation_evaluation_plan.md)与[版本选择规则](research/generic_version_selection.md)
- [观察前沿检索](research/observation_frontier_method.md)及[独立检索结果](research/observation_frontier_experiment.md)

检索命中、生成数量、执行失败、有效缺陷检出是不同指标；没有生成候选也不等于零误报的可靠检测器。目前没有测量 issue resolution rate 的提升。

## 运行

本地 `.venv`、依赖、Docker 镜像和 harness 已准备。单元测试默认禁止真实网络请求：

```bash
.venv/bin/python -m pytest tests -q
```

下面用整测试类比基线演示 CLI；这不表示它已被证实有效。每个输出目录仅用于一个 case，必须是新目录：

```bash
.venv/bin/python scripts/run_generic_experiment.py prepare \
  --generator analogy-views --registry pilot --case P1 \
  --model deepseek-v4-flash --output results/my_generic/P1

# 只有 admit 联系模型；两轮各最多发固定的一次请求，不按结果挑选或重试。
for round_id in r1 r2; do
  .venv/bin/python scripts/run_generic_experiment.py admit \
    --case P1 --output results/my_generic/P1 --rerun-id "$round_id" \
    --model deepseek-v4-flash
  .venv/bin/python scripts/run_generic_experiment.py freeze \
    --case P1 --output results/my_generic/P1 --rerun-id "$round_id"
  .venv/bin/python scripts/run_generic_experiment.py run \
    --case P1 --output results/my_generic/P1 --rerun-id "$round_id"
done

.venv/bin/python scripts/run_generic_experiment.py summarize \
  --case P1 --output results/my_generic/P1
```

无模型的直接生成对照使用 `freeze`、`run` 的 `--direct-baseline`。`prepare` 保存算法快照和输入哈希；冻结后代码或输入发生变化会被拒绝，不能用新代码覆盖旧实验。模型没有返回有效选择时，该轮保留为协议失败，不能当作主动拒绝全部候选。

模型请求仅包含已授权的 issue、候选代码、来源测试及静态证据；生成与模型阶段不读取参考补丁、隐藏 verifier、封存评价真值或执行结果。参考运行只用于冻结后的独立评价。密钥不进入请求证据或 Git，策略见 [execution_policy.json](configs/execution_policy.json)。

## 代码与边界

| 位置 | 作用 |
|---|---|
| `anchor_retrieval/` | 断言识别、定义—使用与可能状态依赖、相关测试排序 |
| `generic_composition/` | 源码语法项、测试语料、固定候选筛选、物化与执行接口 |
| `experimental/generic_v2/analogy.py` | 源码类比与重构等式 |
| `experimental/generic_v3/`、`generic_v5/` | 语句对齐及组合表示变体 |
| `experimental/assertion_instances_v2/` | 带词法环境的 helper 断言实例 |
| `experimental/assertion_windows/` | 断言和依赖定义的连续窗口，以及独立的字符串表示消融 |
| `experimental/observation_priority/` | 观察对象和程序依赖引导的排序 |
| `scripts/run_generic_experiment.py` | prepare、admit、freeze、run、summarize |

依赖关系表示可能影响，不证明断言保持。语法来源可重构，也不证明语义有效；别名、状态效应、闭包以及嵌入字符串中的程序仍可能超出分析能力。所有适用性失败、模型失败、编译失败、未知报警和成本均需保留。

Git 管理代码、方法说明与评价脚本；venv、仓库副本、密钥和大日志由 `.gitignore` 排除。完整本地实验产物保存在 `results/`，每批均记录版本、输入、代码快照与执行账本。
