# 遗漏组合测试：带观察的关系见证

当前原型以 `(q, ρ)` 为研究单位：`q` 是已有测试的观察，`ρ` 是输入、对象或操作之间的关系。程序恢复验证代码、提出关系见证并物化测试；模型只补充受限的局部期望表达式。关系构造、期望正确和真实缺陷检出分别评价，当前实现仍是有界关系域的组合，尚不是统一完备的关系求解器。模型为 **`deepseek-v4-flash`**，使用 `.env` 中已授权的 provider。

**最好完整配置检出 4/17 个 trial：P2、N02、N07、N10，仍漏检 13/17。** 第六批为 3/17，第七批统一恢复完整源断言后重新运行全部 17 例，确认上述 4 例。17 个 trial 对应 14 个不同 task，都是已见开发集。全部检出的目标尚未达到，误报尚未穷尽标注，也没有 issue resolution rate 提升证据。

- [当前方法与实现边界](research/relational_gap_method_v2.md)
- [本轮五小时结果与逐例缺口](research/relational_gap_timebox_20260928.md)
- [第七批独立评价](research/relational_gap_batch7_evaluation.md)、[第六批评价](research/relational_gap_batch6_evaluation.md)与[第五批评价](research/relational_gap_batch5_evaluation.md)
- [新增十条轨迹与组合特征](research/expanded_trials_20260926/README.md)
- [完整原断言恢复消融协议](research/relational_gap_v7_ablation_protocol.md)

旧领域算子原型曾达到七个 pilot 的 7/7，但算子在已知缺陷后设计，存在过拟合，不能作为当前方法的结果。旧文档与运行方式已[归档](research/archive/README_pilot.md)，代码标签为 `combination-v0.1-pilot`。以下保留先前方法的研究记录：

- [前一方法：动作、观察与小期望变换](research/method_design.md)
- [前一方法实验与失败记录](research/semantic_transport_results.md)
- [前一方法独立评价约定](research/semantic_composition_evaluation_plan.md)
- [历史类比方格基线](research/method_design_analogy_baseline.md)
- [前一方法五小时实验记录](research/semantic_transport_timebox_report.md)
- [上一轮五小时实验交付与保留基线](research/timeboxed_experiment_report.md)
- [跨版本实验、失败与模型成本](research/generic_generation_cross_version_results.md)
- [实验评价约定](research/generic_generation_evaluation_plan.md)与[版本选择规则](research/generic_version_selection.md)
- [观察前沿检索](research/observation_frontier_method.md)及[独立检索结果](research/observation_frontier_experiment.md)

检索命中、生成数量、执行失败、有效缺陷检出是不同指标；没有生成候选也不等于零误报的可靠检测器。目前没有测量 issue resolution rate 的提升。

## 运行

本地 `.venv`、依赖、Docker 镜像和 harness 已准备。单元测试默认禁止真实网络请求：

```bash
.venv/bin/python -m pytest tests -q
```

当前静态生成入口为 `scripts/run_relational_gap.py`，执行入口为 `scripts/execute_relational_gap_v6.py`；断言恢复消融使用 `scripts/prepare_relational_gap_ablation.py` 和无模型调用的 `scripts/execute_relational_gap_v7.py`。参数与冻结边界见上述报告和执行协议。已有结果可只读复核：

```bash
.venv/bin/python scripts/evaluate_relational_gap.py evaluate \
  --batch-root results/relational_gap_20260928/batch6 \
  --emitted-root results/relational_gap_20260928/batch6_emitted \
  --reviews results/relational_gap_20260928/batch6_reviews_audited.json \
  --output /tmp/relational-gap-batch6-recheck.json
```

下列命令属于历史动作组合方法。入口 `scripts/run_semantic_transport.py` 先从已有 source-only preparation 构造候选；模型补全与执行分开：

```bash
.venv/bin/python scripts/run_semantic_transport.py prepare \
  --case P1 --source-prepared results/semantic_transport_inputs/batch1/pilot/P1 \
  --output results/my_transport/P1
for round_id in r1 r2; do
  .venv/bin/python scripts/run_semantic_transport.py complete \
    --case P1 --output results/my_transport/P1 --rerun-id "$round_id"
done
for round_id in r1 r2; do
  .venv/bin/python scripts/run_semantic_transport.py freeze \
    --case P1 --output results/my_transport/P1 --rerun-id "$round_id"
done
# 独立评审并封存 oracle 后，再分别 run --program candidate。
```

prepare 默认使用标准配置。显式添加 `--completion-profile reasoned_32k` 可使用预先登记的推理预算对照；它保持程序候选与语义消息不变，仅调整输出上限和推理设置。配置、请求及缓存均按轮冻结。

source-only preparation 可由下面通用 CLI 的 `prepare --generator context` 建立。下面保留整测试类比基线运行示例；各输出目录必须是新目录：

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

另有一个独立的[检索＋模型生成对照](research/llm_generation_baseline_plan.md)：统一向模型展示冻结检索的前十个父测试，每轮最多提出三个完整测试体。它允许模型自由构造动作与断言，与历史类比候选筛选、当前动作与观察组合具有不同能力和预算，结果单独报告。已有冻结输入时可运行：

```bash
.venv/bin/python scripts/run_llm_generation_baseline.py prepare \
  --case P1 --source-prepared results/generic_observation_priority/batch2/pilot/P1 \
  --output results/my_llm/P1

for round_id in r1 r2; do
  .venv/bin/python scripts/run_llm_generation_baseline.py generate \
    --case P1 --output results/my_llm/P1 --rerun-id "$round_id"
done
for round_id in r1 r2; do
  .venv/bin/python scripts/run_llm_generation_baseline.py freeze \
    --case P1 --output results/my_llm/P1 --rerun-id "$round_id"
  .venv/bin/python scripts/run_llm_generation_baseline.py run \
    --case P1 --output results/my_llm/P1 --rerun-id "$round_id"
done
```

该对照同样不依据执行结果修正代码或 expected。机械校验通过、测试失败和有效缺陷仍须分别记录；完整断言及输入适用性需要独立审计。

## 代码与边界

| 位置 | 作用 |
|---|---|
| `relational_gap/` | 当前关系坐标、有限单元、源见证构造、观察选择及恢复消融 |
| `scripts/run_relational_gap.py` | 当前静态准备入口 |
| `scripts/execute_relational_gap_v6.py`、`execute_relational_gap_v7.py` | 源假设和模型变体执行、无模型断言恢复消融 |
| `experimental/semantic_transport/` | 先前动作上下文搜索、小期望表达式及冻结接口；部分工具仍被复用 |
| `experimental/observation_projection.py` | 源观察切片迁移工具 |
| `scripts/run_semantic_transport.py` | 先前动作组合方法入口 |
| `anchor_retrieval/` | 断言识别、定义—使用与可能状态依赖、相关测试排序 |
| `generic_composition/` | 源码语法项、测试语料、固定候选筛选、物化与执行接口 |
| `experimental/generic_v2/analogy.py` | 历史源码类比与重构等式 |
| `experimental/generic_v3/`、`generic_v5/` | 历史语句对齐及组合表示变体 |
| `experimental/assertion_instances_v2/` | 带词法环境的 helper 断言实例 |
| `experimental/assertion_windows/` | 断言和依赖定义的连续窗口，以及独立的字符串表示消融 |
| `experimental/observation_priority/` | 观察对象和程序依赖引导的排序 |
| `scripts/run_generic_experiment.py` | prepare、admit、freeze、run、summarize |

依赖关系表示可能影响，不证明断言保持。语法来源可重构，也不证明语义有效；别名、状态效应、闭包以及嵌入字符串中的程序仍可能超出分析能力。所有适用性失败、模型失败、编译失败、未知报警和成本均需保留。

Git 管理代码、方法说明与评价脚本；venv、仓库副本、密钥和大日志由 `.gitignore` 排除。完整本地实验产物保存在 `results/`，每批均记录版本、输入、代码快照与执行账本。
