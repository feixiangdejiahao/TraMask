> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../../research/archive/README_pilot.md) · [旧路径映射](../../../../results/path_map.tsv)

**上下文提升：遗漏组合测试的检索、构造与执行原型**

输入候选仓库、candidate patch、已有测试和 agent trajectory，先用观察前沿检索断言，再把观察提升到新的路径表示、捕获/克隆、递归动作或协议输入上下文。程序生成测试及比较基准，冻结后在隔离 Docker 中执行。协议语义可使用少量模型辅助；模型不能读取参考补丁、隐藏 verifier 或手工目标。

七个 pilot 的检索 **Test Hit@10 = 7/7、Assertion Hit@10 = 7/7**，断言排名为 **5、4、5、5、2、3、1**。组合生成是独立实验，不能以检索命中代替缺陷检出。七例来自四个 issue 家族，均为已分析的发现集；当前尚未测量 issue resolution rate 提升。

组合实验 `contract_v6` 生成 263 个检查及 168 个控制，检出 **7/7 个已知目标缺陷**。49 条候选报警经独立审计未发现错误 oracle；3 条参考报警有 issue 依据，仍原样保留。固定缓存全量重放结果一致；重新调用模型的一轮实验也保持 7/7 和相同报警集合，但多出一条双方通过、语义关系尚未独立确认的测试。这不证明所有组合都无误报或漏报。

方法见 [method_design.md](../method_design.md)，最终数据与边界见 [组合实验报告](../combination_generation_experiment.md)，失败版本见 [开发记录](../context_lifting_execution_notes.md)。检索消融见 [检索报告](../observation_frontier_experiment.md)，旧算法负结果见 [历史报告](../anchor_retrieval_experiment.md)。

**运行**

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -W ignore::SyntaxWarning -m anchor_retrieval.experiment --output results/anchor_retrieval/reproduction
.venv/bin/python -m anchor_retrieval.evaluate --results results/anchor_retrieval/reproduction
.venv/bin/python scripts/audit_frontier.py --results results/anchor_retrieval/reproduction
```

单个仓库不需要目标标签：

```bash
.venv/bin/python -W ignore::SyntaxWarning -m anchor_retrieval.retrieve \
  --repo data/cases/P2/repository --patch data/cases/P2/model.patch \
  --language python --trajectory data/cases/P2/trajectory.json \
  --output results/anchor_retrieval/single.json
```

检索 `experiment --cases P1 P2` 选择子集；`--repository-only` 去掉历史脚本。检索本身不调用模型。用户已授权向 `.env` 指定 provider 发送 issue、候选代码、已有测试和静态证据；策略见 [execution_policy.json](../../../../configs/execution_policy.json)。`.env` 的 `base_url` 与 `api_key` 仅由显式模型请求入口读取，凭据不进入证据或 Git。

组合实验分为三个可分别重放的阶段，输出目录必须未存在：

```bash
# 可选模型阶段；每个协议 case 一次请求，保存可执行保持条件
.venv/bin/python -m combination_testing.contracts --case P1 \
  --model gpt-6-astra --max-tokens 10000 --output results/my_contracts/P1
# 对 P2/P3 使用相同命令；P4–P7 的结构适配器不需要模型

# 使用冻结条件生成全部七例，不在本阶段请求模型
.venv/bin/python -m combination_testing.experiment \
  --protocol-mode contract --contracts results/my_contracts --output results/my_run

# 分别运行每个 case，示例为 P1
.venv/bin/python -m combination_testing.runner results/my_run/P1 \
  --output results/my_run/P1_execution --program pair
.venv/bin/python -m combination_testing.evaluate \
  --artifacts results/my_run --output results/my_run/evaluation.json
```

离线复现最终结果时，跳过模型请求，把生成命令中的 `--contracts` 设为 [research/frozen_contracts/v6](../../../../research/frozen_contracts/README.md)。Git 中同时保存独立重抽样缓存及未修改的原始请求/响应。

Docker 必须可访问，镜像和 harness 已在本地准备。`pair` 只由评价器装入参考补丁；候选告警独立计算。`empirical`、`guarded` 是保留的失败基线，`screened` 是有限 ID 准入分支，不能将这些选项视为已经可靠的默认检测器。

**核心实现**

| 文件 | 功能 |
|---|---|
| [frontier.py](../../../../anchor_retrieval/frontier.py) | 实际观察识别、值依赖足迹、前沿偏序、参数化期望区分数、按测试轮换 |
| [graph.py](../../../../anchor_retrieval/graph.py) | 局部定义—使用、控制依赖、保守状态顺序 |
| [index.py](../../../../anchor_retrieval/index.py) | 符号解析、字段来源、有限调用图、解析输入位置 |
| [syntax.py](../../../../anchor_retrieval/syntax.py) | Python/Go/TypeScript/TSX 解析、测试清单、trajectory 脚本提取 |
| [retrieve.py](../../../../anchor_retrieval/retrieve.py) | 组合分析步骤，输出排名、源码摘录和供体证据 |
| [evaluate.py](../../../../anchor_retrieval/evaluate.py) | 独立读取标签，计算 Test/Assertion Hit@k 与 MRR |
| [paths.py](../../../../combination_testing/paths.py)、[structural.py](../../../../combination_testing/structural.py) | 保持绑定的路径改写、host/guest、clone/fresh、递归/展开比较 |
| [protocol.py](../../../../combination_testing/protocol.py)、[contracts.py](../../../../combination_testing/contracts.py) | 协议坐标与原断言提取、受限保持条件解释、组合构造 |
| [runner.py](../../../../combination_testing/runner.py)、[evaluate.py](../../../../combination_testing/evaluate.py) | 冻结校验、隔离执行、控制组、目标检出及报警计数 |

`full` 是当前观察前沿方法。比较项包括 `legacy_keywords`、`legacy_full`，以及去掉前沿、期望多样性、按测试轮换的三项消融。旧的 `no_input_gaps` / `no_diversity` 继续保留用于对照历史方法。

**结果与版本**

完整复核输出位于 [frontier_final](../../../../results/initial_test_combinations/patch_related_test_retrieval/observation_frontier_summary/report.md)。首次达标运行位于 [frontier_v2](../../../../results/initial_test_combinations/patch_related_test_retrieval/observation_frontier_v02/report.md)，去掉历史脚本的验证位于 [frontier_v2_repository_only](../../../../results/initial_test_combinations/patch_related_test_retrieval/observation_frontier_v02_repository_only/report.md)。

- `P*.json`：全部断言、前沿事实、依赖链、输入/供体及各方法排名。
- `P*.selected_tests.json`：当前方法前 20 个不同测试的源码摘录。
- `P*.baseline_selected_tests.json`：关键词基线对应摘录。
- `evaluation.json`、`ranks.csv`、`report.md`：评价结果。
- `manifest.json`、`implementation_snapshot/`：Git 提交、实现哈希、运行时间和源码快照。
- `audit.json`：输入、标签、代码哈希及记录扰动核验。

Git 保存代码、方法报告、[精简实验数据](../../../../research/experiments)及[模型冻结缓存](../../../../research/frozen_contracts/README.md)。标签 `retrieval-v0.1-baseline`、`retrieval-v0.2` 保留检索阶段；`combination-v0.1-pilot` 标记本轮组合原型。venv、原始数据、仓库副本、密钥和大体积执行日志被 `.gitignore` 排除。

**分析边界**

足迹包含关系不是断言逻辑蕴含关系，后续计算可能屏蔽错误。局部值依赖较明确，跨过程调用、字段来源、动态分派仍有保守近似；没有完整的堆、闭包或 Tengo guest-language 分析。

检索摘录本身依赖原仓库的 imports、fixtures 和 helpers；组合适配器只支持能够重建的有限形状。P6/P7 的 oracle 来自新增配对观察及有限展开，不直接继承旧测试的弱断言。历史脚本提取不等于完整 trajectory 重放。synthetic 检查、校准和冻结重放约束具体行为，没有消除小样本开发偏差。
