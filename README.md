**本地 pilot 测试入口检索原型**

输入候选仓库、candidate patch 和 agent trajectory，输出带源码位置、依赖证据、供体候选和排名的测试断言。实现不调用模型，不读取 `.env`，也不执行 trajectory 中的命令。目标是评价已有测试 A 的检索；没有实现组合测试生成或 issue resolution 实验。

最新完整运行与评价位于 [results/anchor_retrieval/final](results/anchor_retrieval/final/report.md)。目标标签在运行前由既有人工分析固定；检索器不读取标签。七个 pilot 属于四个 issue 家族，是方法发现集。

**运行**

在本目录中使用已安装的 venv：

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -W ignore::SyntaxWarning -m anchor_retrieval.experiment --output results/anchor_retrieval/reproduction
.venv/bin/python -m anchor_retrieval.evaluate --results results/anchor_retrieval/reproduction
```

单例检索不需要 target-test 标签或人工特征：

```bash
.venv/bin/python -W ignore::SyntaxWarning -m anchor_retrieval.retrieve \
  --repo data/cases/P2/repository \
  --patch data/cases/P2/model.patch \
  --language python \
  --trajectory data/cases/P2/trajectory.json \
  --output results/anchor_retrieval/single.json
```

`experiment --cases P1 P2` 可以选择子集；`--repository-only` 用于去掉历史脚本的比较。默认同时保留仓库和可解析的临时验证。执行授权记录见 [execution_policy.json](configs/execution_policy.json)，模型代码上传仍禁用。

**实现的分析**

| 文件 | 功能 |
|---|---|
| [syntax.py](anchor_retrieval/syntax.py) | Python/Go/TypeScript/TSX 解析、测试及参数行清点、trajectory heredoc 提取、作用域内去重 |
| [graph.py](anchor_retrieval/graph.py) | 断言观察提取、局部定义—使用和控制依赖、分支合流、保守状态顺序 |
| [index.py](anchor_retrieval/index.py) | 导入/receiver/继承解析、有限调用展开、字段写入切片、正则捕获组及 match 参数传播 |
| [retrieve.py](anchor_retrieval/retrieve.py) | 断言对 patch 的影响查询、输入倒排索引、取值差供体检索、观察位置轮换排序 |
| [experiment.py](anchor_retrieval/experiment.py) | 运行七例、记录版本哈希与时间、保存实现快照及源码摘录 |
| [evaluate.py](anchor_retrieval/evaluate.py) | 单独读取人工标签，计算测试和断言排名、Hit@k、MRR |

测试内先构建轻量依赖图，生产函数按需展开并缓存。同一字段的构造参数与正则捕获组对应也缓存复用；没有建立任意两份完整测试之间的笛卡尔积。目前尚未实现完整的跨过程 SDG、精确 points-to、堆状态切片或 guest-language 分析。调用名回退会标为候选，不当作精确符号解析。

P2 中，分析能够通过构造函数参数、match 实参/形参以及正则捕获组，把 `Key.character` 的输入依赖连接到关联文本。Go 字符串中的 Tengo 程序目前仍是字符串输入，没有恢复其 capture/alias 语义。TypeScript 已区分运行时断言与 `.test-d.ts`，但没有完整恢复执行闭包的捕获对象。

**排序和评价口径**

`full` 固定使用一个字典序优先级：非错误状态检查、字段写入证据、有供体取值差、默认取值差数量、取值差数量、受影响符号数量、调用解析强度、较小的 setup/slice。数量分别截断为 4/8/4，再按源码位置稳定打破平局。最后按观察位置轮流取候选，同一位置先取不同测试的代表。这个规则在首次 pilot 评价前确定；后续修复没有按目标排名修改这些权重或顺序。

同时输出三个比较项：

- `no_input_gaps`：去掉取值差优先级。
- `no_diversity`：去掉观察位置轮换。
- `legacy_keywords`：在相同断言清单上应用旧关键词规则：改动测试 +200、改动文件 +100、trajectory 来源 +15，再加入调用名与 patch 标识符的交集计数。这是旧规则在新清单上的比较项，不是原旧脚本的逐字复现。

Hit@k 的预算是排名前 k 个测试函数或前 k 个断言，分别计算。P4/P6 标签包含事前标注的多个可接受断言位置，取最早命中。未标注其他测试的相关性，因此不将其都算作 false positive，不报告 precision。P6/P7 只评价旧测试入口，命中不等于已有合适 oracle。

**输出**

- `P*.json`：所有断言、局部 setup 行、生产影响链、字段证据、输入/供体及四种排名。
- `P*.selected_tests.json`：`full` 前 20 个不同测试的原始源码摘录。
- `P*.baseline_selected_tests.json`：关键词基线前 20 个不同测试的原始源码摘录。
- `evaluation.json`、`ranks.csv`、`report.md`：逐例与汇总评价。
- `manifest.json`、`implementation_snapshot/`：运行时间、实现哈希和当次代码快照。

源码摘录仍依赖原仓库的 imports、fixtures 和 helpers，不是独立生成的可运行测试。历史脚本按最终候选重新静态分析，保留 step；没有重放，历史通过状态不转移到最终候选。语法恢复错误和调用展开截断都有计数，不能据未检索到某个测试就证明组合不存在。

设计与人工证据见 [research/README.md](research/README.md)；实际实验分析见 [anchor_retrieval_experiment.md](research/anchor_retrieval_experiment.md)。
