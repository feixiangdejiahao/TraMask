历史记录：本文件保留旧算法的负结果。当前观察前沿算法与 7/7 结果见 [最新实验报告](observation_frontier_experiment.md)。

**测试 A 检索：实现与七例本地实验**

日期：2026-09-23。结论：**七例的目标测试及目标断言都被提取进清单，但修改后的完整排序没有将任何一例的目标测试排入前 10。关键词基线的 Test Hit@10 是 7/7。当前实验不支持把依赖、输入取值差与观察位置轮换直接作为有效的 A 排序方法。**

原始机器结果见 [report.md](../results/anchor_retrieval/final/report.md)、[evaluation.json](../results/anchor_retrieval/final/evaluation.json)、[ranks.csv](../results/anchor_retrieval/final/ranks.csv)。实现、运行方式及分析边界见 [项目 README](../README.md)。本次只执行分析器及其回归测试，不执行被测仓库或 replay，不调用模型。

**1. 实现与评价分离**

检索器只读取候选仓库、candidate patch 和 trajectory 工具参数，不读取 handbook、人工 target 标签、隐藏 verifier 或参考补丁。Python/Go/TypeScript 使用本地 Tree-sitter；Python 字面量和参数化使用 AST。分析结果由代码计算，没有模型生成的语义标签。

实现包括断言上下文提取、局部定义—使用和控制依赖、保守状态顺序、导入/receiver/继承解析、有限调用展开、字段写入切片、正则捕获组与 match 实参/形参传播、供体输入倒排索引和四种排序。历史脚本不执行，也不把历史通过当作最终候选通过。

目标标签在首次 pilot 检索前按上一轮手工审查写入 [anchor_targets.json](../configs/anchor_targets.json)，由独立 evaluator 在检索结束后读取。没有要求算法预先知道 `character`、`phase` 等目标观察。七例均是已经人工阅读的方法发现集，不能称为未见过数据上的验证。

分别评价：

- **测试函数排名：** 按候选顺序对 test 去重后，目标函数第一次出现的位置。
- **断言排名：** 目标断言在全部候选断言中的位置；不能以找到大函数代替找到正确断言。
- P4/P6 的多个可接受断言位置在实验前已列出，取首次命中；其他 case 各固定一个断言位置。
- P6/P7 是已有测试入口的检索目标，命中不代表已经获得检测内部共享或 pipeline 遗漏的 oracle。

其他测试是否有用没有穷尽标注，因此不将它们统统当作 false positive，不报告 precision。报告 Hit@k 和 MRR，k 为 1、5、10、20、50、100。

**2. 最终结果**

| Case | 测试定义数，含历史脚本 | 完整方法：测试排名 | 完整方法：断言排名 | 关键词基线：测试排名 | 关键词基线：断言排名 |
|---|---:|---:|---:|---:|---:|
| P1 | 2,059 | 16 | 534 | 5 | 11 |
| P2 | 2,071 | 128 | 190 | 4 | 16 |
| P3 | 2,062 | 182 | 331 | 5 | 38 |
| P4 | 1,096 | 168 | 332 | 5 | 15 |
| P5 | 198 | 15 | 168 | 2 | 15 |
| P6 | 245 | 24 | 47 | 3 | 6 |
| P7 | 4,575 | 22 | 119 | 1 | 1 |

每例的目标断言在原始清单中都存在。P7 的统计包含原始测试定义，排序前排除了 1,406 个类型测试单元；表中的数量不能解读为全部可执行 runtime tests。参数化函数没有按参数行膨胀成多个测试定义。

| 方法 | Test Hit@10 | Assertion Hit@10 | Test MRR |
|---|---:|---:|---:|
| 完整：依赖 + 输入取值差 + 观察位置轮换 | 0/7 | 0/7 | 0.0336 |
| 去掉输入取值差优先级 | 4/7 | 1/7 | 0.1157 |
| 去掉观察位置轮换 | 2/7 | 1/7 | 0.0733 |
| 关键词基线 | 7/7 | 2/7 | 0.3833 |

关键词基线是在相同新版断言清单上应用旧排序规则，包含改动测试/文件优先级；不是原旧脚本所有行为的逐字重现。四种方法使用相同候选源与同一套标签。这里只比较检索效果，没有单独测量一个完全不做依赖分析的基线运行时间。

七例累计内部分析计时为 **98.88 秒**，单例约 10.35–18.20 秒；不含结果 JSON 序列化写盘等开销。实现通过 **24 项本地回归测试**。已校验七份结果的候选 ID、排名唯一性、运行代码哈希和实现快照。

**3. 为什么没有准确优先选出 A**

**观察位置轮换会把好候选排得很靠后。** P2 的目标是 parser 的 `character is None`。程序分析确实恢复了 `Key.character` 的依赖，并将输入投影到关联文本所在的正则捕获组；供体索引找到了 text-only 测试的非空值。目标断言在自己的 `Key.character` 组中排第 2，但总共有 188 个观察组，每组依次取一个候选，使它落到全局第 190。移除轮换后，同一目标测试升至第 4、断言升至第 7。这是排序机制的问题，不是“完全没提取到 A”。组内位置是事后诊断，未作为 oracle-informed 的自动成功率使用。

**输入取值差不是可靠的 A 优先级。** 去掉该优先级，Test Hit@10 从 0/7 升到 4/7。P2 的输入差不仅包括关联文本，也包括 key code、alternate code 和 modifier。不同输入能够影响观察值，并不能证明原断言在改变它们后仍应成立；变化多的测试可能只是行为本来就应变化。当前实现没有从 issue 恢复 oracle 适用条件，也没有把这种适用性加入排序，因而“新取值很多”容易淹没真正有用的 anchor。

**依赖范围仍然过宽，而且包含未解析部分。** 例如 P2 的 4,530 个断言中，1,365 个进入受改动影响的候选范围，并没有自动缩成先前手工示例中的 6 个 parser 字段断言。影响查询使用有限调用图及保守状态依赖；有界展开的截断、函数名回退、缺少完整 heap/closure 分析会损害区分能力。输出明确记录这些状态，不能把它们称为已经完成的精确跨过程切片。

**实验中的目标恰好都位于 agent 新增/修改的测试。** 关键词基线借助这一强先验把七个目标函数全部排到前 5，但其中只有两例的目标断言进入前 10。这表明“找到相关大测试”和“从中找出可继承的 A”仍是不同问题，也说明目前没有证据认为复杂依赖排序优于简单的 patch 优先策略。

**P6/P7 的 oracle 缺口不因入口命中而消失。** P6 的 clone 测试仍主要观察外部隔离；P7 的 readonly 仍是运行时恒等 action。本次没有生成共享 cell 的 write→read 观察，也没有生成非恒等转换的递归期望。不能用入口检索率代替 combination-test 有效性或 issue resolution rate。

逐例诊断和 P2 供体证据保存在 [diagnostics.json](../results/anchor_retrieval/final/diagnostics.json)。

**4. 迭代记录与复现材料**

首次运行先修复了 Python 参数化集合的 JSON 导出问题。之后保留了以下轮次，排序元组、截断值、观察位置轮换规则和 target 标签没有按命中结果修改：

| 轮次 | 状态 | 主要修复或发现 |
|---|---|---|
| [run1](../results/anchor_retrieval/run1/report.md) | 七例完成，完整 Test Hit@10 = 0/7 | 发现同形测试跨文件错误去重、继承调用和字段类型信息不足 |
| [run2](../results/anchor_retrieval/run2/report.md) | 七例完成，完整 Test Hit@10 = 0/7 | 修复上述问题；发现旧 trajectory 生产定义污染解析及 helper 输入传递不足 |
| [run3 manifest](../results/anchor_retrieval/run3/manifest.json) | P1–P6 完成，P7 导出失败 | 修复版本可见性、helper/match 参数传播与 TS assertion helper；遇到 JS 孤立 UTF-16 surrogate 导出问题 |
| [final](../results/anchor_retrieval/final/report.md) | 七例完成，完整 Test Hit@10 = 0/7 | 修复 Unicode 导出、Python builtin 同名误绑定、合成参数节点错误跨度 |

新增回归测试用小型独立程序复现这些分析问题，没有写“某个 pilot 必须排第几”的测试。由于实现修复参考了发现集中的失败，这仍然是原型开发过程，不能作为独立泛化证据。

最终运行的 [manifest](../results/anchor_retrieval/final/manifest.json) 记录代码哈希；[实现快照](../results/anchor_retrieval/final/implementation_snapshot/retrieve.py) 与当前代码一致；[环境记录](../results/anchor_retrieval/final/environment.json) 给出 Python/解析器版本。

每例均已自动导出两份前 20 个测试的完整函数源码摘录，例如：

- [P2 完整方法选择](../results/anchor_retrieval/final/P2.selected_tests.json) 与 [P2 基线选择](../results/anchor_retrieval/final/P2.baseline_selected_tests.json)。完整方法前 20 中没有目标函数，基线第 4 个是目标函数。
- 其他 case 使用同目录下的 `P1`–`P7` 对应文件；这些摘录在读取评价标签之前生成。

**5. 方法结论**

当前实现能够恢复部分有意义的依赖及供体关系，尤其是 P2 的字段—解析组—输入链，但完整排序未实现“快速找到 A”的目标。应保留这个负结果，不继续用手工挑出的示例支持检索有效性的主张。

这组发现集支持的务实做法是先用简单的 patch 优先策略检索相关测试，再研究如何选择其中真正可迁移的断言以及关联输入。依赖分析的独立价值需要在这一强基线上验证。不能把更换排序规则、添加模型生成的 oracle，或人工补出 P6/P7 的观察，混入本次已完成的结果。
