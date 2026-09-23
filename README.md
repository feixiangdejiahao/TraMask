**观察前沿：本地 pilot 测试入口检索**

输入候选仓库、candidate patch 和 agent trajectory，输出已有测试及其断言的排名、源码位置和依赖证据。当前算法围绕一个抽象：在同一测试中，优先选取依赖足迹处于前沿的观察，再按测试分配断言预算。没有模型调用、代码上传或被测仓库执行。

七个 pilot 的 **Test Hit@10 = 1、Assertion Hit@10 = 1**。目标断言排名为 **5、4、5、5、2、3、1**。这些是四个 issue 家族中的方法发现样本，不能当作未见数据验证。当前完成的是 A 的检索，没有实现组合测试生成或 issue resolution 实验。

方法与局限见 [method_design.md](research/method_design.md)，逐例、消融和版本记录见 [实验报告](research/observation_frontier_experiment.md)。旧算法的负结果保留在 [历史报告](research/anchor_retrieval_experiment.md)。

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

`experiment --cases P1 P2` 选择子集；`--repository-only` 去掉历史脚本。授权记录见 [execution_policy.json](configs/execution_policy.json)。模型代码上传仍禁用；实现不读取 `.env`。

**核心实现**

| 文件 | 功能 |
|---|---|
| [frontier.py](anchor_retrieval/frontier.py) | 实际观察识别、值依赖足迹、前沿偏序、参数化期望区分数、按测试轮换 |
| [graph.py](anchor_retrieval/graph.py) | 局部定义—使用、控制依赖、保守状态顺序 |
| [index.py](anchor_retrieval/index.py) | 符号解析、字段来源、有限调用图、解析输入位置 |
| [syntax.py](anchor_retrieval/syntax.py) | Python/Go/TypeScript/TSX 解析、测试清单、trajectory 脚本提取 |
| [retrieve.py](anchor_retrieval/retrieve.py) | 组合分析步骤，输出排名、源码摘录和供体证据 |
| [evaluate.py](anchor_retrieval/evaluate.py) | 独立读取标签，计算 Test/Assertion Hit@k 与 MRR |

`full` 是当前观察前沿方法。比较项包括 `legacy_keywords`、`legacy_full`，以及去掉前沿、期望多样性、按测试轮换的三项消融。旧的 `no_input_gaps` / `no_diversity` 继续保留用于对照历史方法。

**结果与版本**

完整复核输出位于 [frontier_final](results/anchor_retrieval/frontier_final/report.md)。首次达标运行位于 [frontier_v2](results/anchor_retrieval/frontier_v2/report.md)，去掉历史脚本的验证位于 [frontier_v2_repository_only](results/anchor_retrieval/frontier_v2_repository_only/report.md)。

- `P*.json`：全部断言、前沿事实、依赖链、输入/供体及各方法排名。
- `P*.selected_tests.json`：当前方法前 20 个不同测试的源码摘录。
- `P*.baseline_selected_tests.json`：关键词基线对应摘录。
- `evaluation.json`、`ranks.csv`、`report.md`：评价结果。
- `manifest.json`、`implementation_snapshot/`：Git 提交、实现哈希、运行时间和源码快照。
- `audit.json`：输入、标签、代码哈希及记录扰动核验。

Git 保存代码、方法报告和 [精简实验数据](research/experiments)。标签 `retrieval-v0.1-baseline` 保存旧实现；`retrieval-v0.2` 标记本轮完成版本。venv、原始数据、仓库副本、密钥和大体积原始结果被 `.gitignore` 排除。

**分析边界**

足迹包含关系不是断言逻辑蕴含关系，后续计算可能屏蔽错误。局部值依赖较明确，跨过程调用、字段来源、动态分派仍有保守近似；没有完整的堆、闭包或 Tengo guest-language 分析。

源码摘录仍依赖原仓库的 imports、fixtures 和 helpers，不是独立可执行测试。历史脚本不重放。P6/P7 只评价旧测试入口，命中不意味着已有可继承的组合 oracle。38 个回归检查和扰动验证约束具体分析行为，没有消除小样本开发偏差。
