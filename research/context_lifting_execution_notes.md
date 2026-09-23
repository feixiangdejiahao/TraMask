# 上下文提升：执行与评价记录

2026-09-23。本记录保留局部 v1、guarded v2、关系契约分支与 screening v1–v3 的正负结果；不是最终方法的结论。原始产物与日志位于 `results/combination_testing/`；可版本管理的计数、产物哈希和目标归因样例见 [execution_observations.json](experiments/context_lifting_execution_observations.json)。这些结果没有证明普遍的零误报、零漏报或 issue resolution rate 提升。

## 执行单位与证据

生成器先冻结测试源码、命令和逐文件 SHA-256。`runner.py` 在两个全新的容器中执行同一产物：原始 base commit 加候选补丁，以及同一 base 加独立参考补丁。每次记录 Docker image ID、实际 base commit、补丁哈希、产物哈希和逐测试结果。容器禁用网络，不在运行中安装依赖。参考补丁仅由 evaluator 读取，不能成为生成输入。

pytest 的测试体失败与 setup/collection 错误分开；Go 编译失败、缺失报告、全局异常和超时不会成为缺陷证据。生成器显式报告的单个无效构造也不算缺陷，但不抹除其他有效测试。候选测试抛出运行时异常、参考测试正常通过，可以构成行为差异；不强制所有缺陷必须表现为 `AssertionError`。

原始 seed、未提升程序和恒等转换是控制组。某组合声明依赖的控制必须通过，才允许该组合产生告警。控制失败单独保留，不计为新生成组合的误报；也不因无关控制失败而删去已有有效证据。四类镜像的独立 harness smoke 均验证了“正确断言两边通过、故意错误断言两边失败”的分类。

## 指标定义

- **生成义务数**：生成器提出的组合检查数量，不包括明确标注的原始/恒等控制。Go 的部分义务运行时展开，另报观察到的义务数。
- **实际执行数**：组合得到 pass/fail 结果的数量。skip、无效前提、编译错误、超时和未执行分别统计，不能算通过。
- **Candidate alerts**：候选实现上的组合失败，且其声明的控制通过、运行没有全局错误。计算时不查看参考结果。
- **Reference alerts**：完全相同规则作用于参考实现；不能通过事后删除参考失败测试，使该数归零。
- **Differential witnesses**：上述候选告警中，同一组合及必要控制在参考实现上通过的数量。差异仍需要输入与 oracle 的独立语义依据。
- **Issue-contradicted differential witnesses**：满足差分条件、但其 oracle 与明确需求冲突的证据数。这些证据应被独立语义审计否决，不能因参考通过而记为真缺陷。
- **Known-target recall**：有至少一个证据匹配事先记录的 pilot 缺陷机制的 case 数 / 7。发现同一 case 的另一个差异，不能抵消已知目标的漏报。
- **控制失败、无效构造与静态不支持**：分别统计。它们解释方法的适用范围，不能并入真阴性。

参考实现告警率如需报告，分母必须明确是“在参考实现执行并满足控制条件的生成义务”或“已评价参考实现数”。它不是未知总体上的 FPR；参考补丁也不是数学意义上的正确性证明。现有原始 seed 在参考上有失败，进一步说明不能把参考状态默认为完全正确。

## 早期协议推断的负结果

下表全部排除了原始 seed 控制。v1 旧 manifest 未列出完整 controls 数组；评价器利用冻结的 generated IDs 与精确 seed count 恢复分区，没有修改测试。旧粗略统计因此需要更正。

| 分支 | Case | 生成义务 | Candidate alerts | Reference alerts | 差分证据 | 已知目标匹配 |
|---|---|---:|---:|---:|---:|---|
| v1 最小函数依赖 | P1 | 2227 | 481 | 50 | 448 | 是，64 条 |
| v1 最小函数依赖 | P2 | 1684 | 36 | 47 | 3 | 是，1 条 |
| v1 最小函数依赖 | P3 | 1499 | 502 | 503 | 1 | 否 |
| guarded v2 | P1 | 2214 | 463 | 32 | 416 | 是，64 条 |
| guarded v2 | P2 | 1670 | 5 | 16 | 0 | 否 |
| guarded v2 | P3 | 1496 | 124 | 124 | 0 | 否 |

有限样本上的最小函数依赖无法保证新组合保持 oracle。增加现有输出条件作为 guard 虽减少部分错误，还可能屏蔽真正需要测试的交互：P2 的目标差异在 guarded v2 中消失。不能只汇报告警数下降而忽略漏报增加。guarded v2 的 skip 也明显存在：P3 候选跳过 957 条、参考跳过 869 条；两边跳过数量不同，不能将其当成一致通过。

v1 P3 的唯一差分证据是 `ESC[0;5:1;97u` 的 `character` 差异，**不是 shifted alias 目标**。因此 v1 即使七个 case 都存在某种差异，已知 pilot 目标仍只覆盖 6/7。

P1/P2/P3 原始 seed 在参考上的失败数分别是 4/3/2；它们不属于新组合告警。对应的原始报告总失败数 54/50/505 应拆成生成失败 50/47/503 加 seed 失败 4/3/2，不能混称生成误报。

## 结构变换与关系契约

| 分支/Case | 有效组合执行数 | Candidate alerts | Reference alerts | 已知目标匹配 | 控制/限制 |
|---|---:|---:|---:|---|---|
| 路径 v1 / P4 | 4 | 4 | 0 | 是 | 2 个原始控制均通过 |
| 结构 v1 / P5 | 14 | 7 | 0 | 是 | 另有 3 个无效构造 |
| 结构 v1 / P6 | 18 | 1 | 0 | 是 | 另有 2 个无效构造 |
| 结构 v2 / P5 | 20 | 11 | 0 | 是 | 20 个未提升控制均通过 |
| 结构 v2 / P6 | 22 | 1 | 0 | 是 | 22 个未提升控制均通过 |
| 结构 v2 / P7 | 8 | 8 | 0 | 是 | 8 个恒等控制均通过 |
| 契约关系 v1 / P3 | 1 | 1 | 0 | 是 | 依赖的 5 个 seed 控制通过 |

P5 将同一脚本提升为返回含 callable 的复合 scope 的工厂，比较 host/guest 执行；候选发生异常而独立路径及参考通过。P6 的 cloned writer 更新后，配对 observer 仍读到旧值，而原实例状态保持不变，符合“内部共享丢失”的目标。P7 非恒等 donor 在有限展开上执行，在递归解析上丢失；恒等控制通过。

P3 契约分支从 API 文档提取表示角色，从已有 modifier 断言确定唯一 bit，再运输既有 alias membership。其 oracle 显式依赖“表示吸收已包含的修饰操作”这一契约解释，不声称由一个正例自动证明。候选只产生带冗余修饰的 alias，参考接受运输后的断言。该产物还执行了 31 个原始 seed，其中参考失败 2 个；这两项不在新义务的 5 个依赖控制中，故既不伪装成组合误报，也不隐去。

## 有限 proposal 语义准入：screening v1–v3

这里的版本与前文协议 FD 的 v1/guarded v2 是不同分支。准入模型只能选择自动构造的具体 proposal ID，不能改 expected、测试体或执行命令。版本归因以 `results/combination_screening/<version>/<case>/request.json` 和 manifest 为准，不以持续修改的当前 `screening.py` 为准。[准入记录快照](experiments/screening_admission_observations.json)保留 9 个 manifest 的路径、SHA256、请求哈希与状态。

screening v1 使用 `deepseek-v4-flash`，请求只带 issue、sources 与 proposals；P1/P2 分别发送 128 个，P3 发送 89 个。冻结后执行的结果如下：

| Case | 批准/执行组合 | Candidate alerts | Reference alerts | 差分证据 | 已知目标匹配 | issue 否决差分 |
|---|---:|---:|---:|---:|---:|---:|
| P1 | 112 | 47 | 15 | 19 | 9 | 1 |
| P2 | 128 | 35 | 15 | 2 | 1 | 1 |
| P3 | 20 | 8 | 1 | 1 | 0 | 1 |
| 合计 | 260 | 90 | 31 | 22 | 10 | 3 |

已知目标检出为协议子集 **2/3**。31 条参考报警进一步分为：改变 phase 却保留旧 phase 12 条，改变 metadata 输入却保留旧值 9 条，改变 modifier 字符语义 3 条，改变 associated text 仍保留旧字符 2 条，丢失 text-only 前提 3 条，以及参考与 issue 支持的 oracle 冲突 2 条。前四类的输入可有效，错误在不变量；不能都叫“无效输入”。P2 批准全部 128 条，说明有限 ID 输出本身不能保证语义准入正确。

另有 **3 条候选失败/参考通过**也被 issue 否决：P1/P2 c0032、P3 c0017 删除最后一个非 shift modifier，却保留 `character=None`；issue 明确要求 shift-only printable 的字符为 A，候选的 A 符合要求。这三个 source control 在两边均通过，仍不能挽救错误 oracle。故 P3 的唯一差分不是 alias 目标，更不是有效缺陷证明。完整输入、输出、issue 原文与冻结哈希见[独立 oracle 审计](screened_v1_oracle_audit.md)及其[逐条数据](experiments/screened_v1_oracle_audit.json)。

本轮参考有 9 个原始 source control 失败。原始生成参考失败共 88 条，其中 57 条受来源对照失败影响，排除这一污染才得到 31 条参考报警。受参考来源对照阻断的组合共 60 条；其中仍有 39 条独立候选报警必须保留为未能通过参考判定的结果，不能事后删除以提高 precision。31 条参考报警也不能等同于 31 条真误报，因为其中 2 条是参考本身与需求冲突。

screening v2 增加仅来自既有测试事实的确定性矛盾否决、候选 docstring 和 16 条准入校准对；模型改为 `deepseek-v4-pro`。这些变更没有向模型提供参考执行结果。

| Case | 自动事实否决 | 校准错误准入 / 8 个应拒绝样例 | 校准漏准入 / 8 个应接受样例 | 执行状态 |
|---|---:|---:|---:|---|
| P1 | 8 | 8 | 0 | 准入校准失败，未冻结执行 |
| P2 | 10 | 8 | 0 | 准入校准失败，未冻结执行 |
| P3 | 4 | 5 | 4 | 准入校准失败，未冻结执行 |

v2 的 manifest `valid=true` 只表示输出可解析且 ID 合法，三项 `calibration.passed` 均为 false；不能称为有效生成实验，更不能记为零误报。模型返回的批准数包含校准条目，不能直接当成生成组合数。校准失败表明模型连已有事实明确否定的关系也会批准；增加上下文或换模型没有在本轮解决该问题。

screening v3 使用同一批 proposal（其 proposal SHA 与 v2 一致），模型改为 `claude-opus-4-6`。P1/P2/P3 均记录 `valid=false` 和 `Expecting value: line 1 column 1 (char 0)`，属于输出 JSON 解析失败；没有可执行准入产物。这是模型接口/格式失败，**不能当成检测结果，也不能据此评价其语义判断精度**。本记录不包含仍在进行的后续请求。

## 目标归因与防止评价污染

[combination_targets.json](../configs/combination_targets.json) 和 `target_audit.py` 仅属于评价器：在产物冻结之后，用输入坐标、观察字段、关系类型和实际失败证据匹配七个已知机制。生成器没有读取该文件。报告同时保留“任意差分证据”和“已知目标证据”，其余差异记为 additional differential candidates，不能自动宣布为新缺陷。

P1 要求非 Unicode 编码上的 repeat/release 义务；P2 要求非 shift modifier 与非空 text 共同作用于 `character=None`；P3 要求含表示修饰位的 alternate alias membership。P4–P7 分别检查路径表示、复合 host/guest、共享 observer trace 与非恒等递归转换。该匹配是事后行为归因，不等同于精确源级根因证明。

这些是已知发现集上的开发记录。后续版本必须重新冻结、执行和匹配目标，不能把不同分支最好的局部结果拼成一次已经完成的统一实验，也不能根据参考输出筛选生成器的告警。
