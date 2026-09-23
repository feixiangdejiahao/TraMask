**从行为关系缺口到 combination tests：程序分析主导的方法设计**

旧版归档：该方案因缺少集中的学术抽象、范围过大而被替换。当前方案见 [关系残差切片](../method_design.md)。

本文件是设计方案，不是已经实现并验证的系统。依据为 [10 个 trial 的人工分析](../manual_case_analysis.md) 和 [2026 年相关研究](../literature_2026.md)。本轮没有运行实验。名称沿用 handbook 的 Discriminating Combination Coverage（DCC），以下定义仍需未来实证验证。

**1. 可作为论文中心的问题**

建议研究问题：在 coding agent 已经完成一个候选 patch、并拥有若干成功的单项验证后，能否从 issue、代码依赖及已有测试中恢复“尚未被有区分力地检验的行为关系”，以较少新增测试发现候选仍违反的契约，并在相同修复预算下提高最终 issue resolution rate？

这里有三个必须同时解决的技术问题：

1. **哪些组合值得检查？** 因素组合需有程序结构或需求契约见证，避免任意两份 test 的笛卡尔积。
2. **已有 tests 是否真的检查过这个关系？** 需要同一次逻辑情景、相同对象/实例/epoch 和合适值，不能把不相干运行的覆盖并集视为联合作用。
3. **观察能否区分语义丢失？** 即使相关语句都执行过，也可能被恒等值、错误观察层级或只查终态的 oracle 掩盖。

“coverage 不足”本身是已有认识；“call graph + LLM 生成测试”也有强相关工作。潜在贡献应该是一种有证据支持的交互义务表示及其缺口判定，并把输入、堆关系和时序统一到可观察的语义义务上。新颖性仍需更全面 related-work 检索，不能仅凭这些 pilot 保证。

**2. 为什么单纯比较两个 test 的测试位置不够**

设 `S(t)` 是 test 所触及的生产位置集合。`S(t1)∩S(t2)≠∅` 只能作便宜召回信号：共享 logger、构造器或 assertion helper 会产生大量噪声；两次调用同一函数也可能使用完全不同对象；P3 两组数值可能覆盖同一行，却不触发相同语义。

更合适的分析单元是：`〈生产语句/值，调用上下文，抽象对象，字段/索引，执行阶段，契约角色〉`。测试提供构造配方、输入限制和观察；生产程序提供关系证据。

| 候选关联 | 应检查的程序事实 | 必须附加的约束 | 例子 |
|---|---|---|---|
| 生产者→消费者 | return/argument def-use 可达 | 类型可统一，前置条件满足 | factory 返回 closure→Go 调用 |
| 写→读 | W(a) 与 R(b) 指向同一抽象位置 | 同一实例/alias 类，先写后读 | clone 内 setter/getter |
| 两条流→共同输出 | 两者进入同一字段或分支合流 | 两个 guard 可共同成立，oracle 观察该字段 | modifier/text→character |
| wrapper→core API | 调用边与参数变换 | 表示层语义保持 | quoted command→path |
| 同契约的平行入口 | 共享结果类型/issue 义务、入口映射 | 合法语法或等价初始状态 | Kitty 两种语法、Go/VM |
| 对象复制/转换 | 源与目标的图映射 | 内部别名保持、外部隔离、闭包捕获一致 | clone、schema 重写 |
| 生命周期/并发 | 同资源的状态转换和回调 | epoch/key 区分、happens-before | clear/reuse/late completion |
| 观察层关系 | 输出值到 assertion、yield/close 到观察 | 运行时/类型层次相符 | Valibot typecheck、HTTPX first yield |

注意“位置间不存在实际依赖边”不能成为绝对排除条件：P1 中缺失的传播边本身就是可疑点。应采用**实际程序关系图 + 契约所要求的关系图**，二者不一致处也产生候选。

**3. 统一中间表示：测试情景、行为事实、交互义务**

首先把大 test 拆为若干保持数据关联的逻辑情景。pytest parametrize 的一行、Go table 一行、一个 test 中一组连续 setup-act-assert，才是输入单位。不能因为 100 行 test 同时包含数组和 Call 就认为数组经 Call 返回；不能把参数表中的输入列与期望列拆开后任意组合。

建议记录的 TestScenario：

```text
identity: repository, commit/patch hash, test path, test name, parameter row,
          trajectory step, historical source hash
provenance: developer | agent-file | agent-ephemeral | generated
setup: constructor/fixture DAG, initial-state predicates
entry: resolved symbol, receiver, invocation context
inputs: constants, expression provenance, abstract domains, constraints
heap: allocation sites, containment edges, alias classes, captured cells, owner
sequence: actions, resource/epoch IDs, order constraints
observation: assert expression, observed field/event, exception/resource checks
status: source-only | historically executed | replayed-current | unknown
```

BehaviorFact 必须有证据种类：AST 精确事实、静态 may-depend、动态 observed、issue contract、LLM hypothesis。不同级别不能混成一个“已证明”集合。

一个交互义务建议表示为：

```text
u = <contract, interface, factors, activation_predicate,
     heap_relation, order_relation, observable, oracle_basis, evidence>
```

- factors 可来自输入谓词，也可来自对象形状、入口和阶段。
- activation_predicate 说明什么值真正激活交互，例如 `shift∈M ∧ shifted_key≠base_key`。
- heap_relation 可表达 `same_cell(f,g) ∧ different_owner(source,clone)`。
- order_relation 可表达 `clone < write(f′) < read(g′)` 或 `first_yield < EOF`。
- observable 决定要查看 aliases、共享状态、资源关闭还是时序事件。
- 一个义务可以需要三个或更多节点，故使用超边/小型关系模式，不强制只用 test pair。

示例（P6 的回顾性标注，不是未来模型输入）：

```json
{
  "contract": "clone preserves source-internal sharing while isolating the clone",
  "interface": "Compiled.Clone + CompiledFunction.Call",
  "factors": ["clone", "two closures", "shared mutable local"],
  "heap_relation": ["capture(f)=capture(g)", "capture(f_clone)!=capture(f)"],
  "order_relation": ["clone < write(f_clone) < read(g_clone) < read(g)"],
  "observable": ["getter return in clone", "getter return in source"],
  "required_value_constraint": "written_value != initial_value",
  "status": "manual candidate; not executed"
}
```

该表示需要支持**没有第二份供体测试**的情形：从一份现有测试与一个契约/程序模式构造缺失关系。P4、P6 不能被强行限定成“两份现成 test 的拼接”。

**4. 静态阶段：缩小到 issue 相关的依赖切片**

输入边界仅为 issue、base/candidate code、candidate patch、developer tests、agent tests 和可见运行日志。不得把 handbook 人工缺陷说明、hidden failure、reference patch 放入生成器。

步骤 A：围绕 changed functions、changed fields、new entrypoints 和 issue 中可解析到符号的 API 建初始 seed。向外扩展到 callers、parallel adapters、结果构造器和读取 changed state 的位置。保留 base 与 candidate 两份结构以定位变化，但 base 不是新功能 oracle。

步骤 B：解析测试及 fixture/helper。将 expected value、raises、mock expectations、文件/数据库验证、type assertions 分开。识别变量绑定与实参角色，展开可安全静态求值的参数表。无法求值的 fixture/动态生成参数标为 unknown，后续通过 runner collection 补充。

步骤 C：构建有调用上下文的局部 CFG/SSA/def-use、控制依赖和 R/W 摘要；从断言 backward slice、从输入与 patch forward slice，两者交叉形成候选关键区域。单看 backward slice 会漏掉尚未被任何断言观察的新字段，因此需补充 issue 指定观察和 parallel-entry obligations。

步骤 D：构建有限抽象域，而非无限猜输入：enum/default、null/empty/nonempty、bitset 的单个位与已见组合、字符串表示类别、容器深度/叶类型、alias partition、initial/mutated/finalized、同步/异步及 entry family。域值的来源必须记录。

步骤 E：按图模式生成候选。可先用 hash index 对 `(abstract field, callee, contract role, representation boundary)` 分组，避免 O(n²) 的全库 test 配对。对 k=2 做主搜索，仅对发现的 alias/顺序等小型 motif 展开 k=3 或必要更高阶，不任意全排列。

逻辑规则示意：

```text
Candidate(t1,t2,u) :-
  Supplies(t1,A), Supplies(t2,B),
  RelevantToIssue(A), RelevantToIssue(B),
  InteractionWitness(A,B,u),
  NotKnownIncompatible(A,B).

Candidate(t1,u) :-
  Supplies(t1,A), ContractRequires(A,B),
  NoKnownCurrentWitness(B).
```

`NoKnownCurrentWitness` 是开放世界中的 unknown，不能自动当成“肯定缺失”。SAT 的 UNSAT 只有在当前约束域、建模完整且契约一致的局部问题上才有意义；全程序无法证明时保留 unknown。

**5. 语言落地：Tree-sitter 是前端，不是依赖分析器**

| 层 | 建议实现 | 能得到什么 | 不应声称什么 |
|---|---|---|---|
| Python | ast/symtable + imports/fixture resolution + 局部 CFG 与 bounded interprocedural summaries | 赋值、guard、call argument、字段、断言数据流 | 动态 dispatch/monkeypatch 全程序精确可解 |
| Go | go/packages、go/types、go/ssa；按需的调用图与字段/对象摘要 | typed calls、alloc/free vars、heap access、frame 代码关系 | AST 文本相同即同一运行时对象 |
| TypeScript | Compiler API 的 symbol/type checker + AST/CFG 摘要 | 函数值、对象 spread 覆盖、属性读写、test vs test-d | TypeScript 类型成立即 runtime pipeline 正确 |
| 嵌入语言 | Tengo parser/compiler 的只读分析适配，或专门 guest AST | script bindings、captured local、容器内 callable | Go 字符串 literal 的 token 能证明 alias |
| trajectory shell | Bash AST + heredoc/文件写入数据流 + step/version provenance | 临时测试和历史输入快照 | 每个含 assert 的命令都是 test |

这些是计划中的组件，当前安装的 Tree-sitter 库和早期 `scripts/extract_tests.py` 只提供语法 inventory。现有脚本的 shared-call 边未解析符号、未验证动态关系、未做参数行语义绑定，也没有真正的 PDG/points-to；不能把其结果宣传成本文方法已经实现。

官方能力参考：[Python AST](https://docs.python.org/3/library/ast.html)、[Go SSA](https://pkg.go.dev/golang.org/x/tools/go/ssa)、[TypeScript Compiler API](https://github.com/microsoft/TypeScript/wiki/Using-the-Compiler-API)。各实现依赖需按目标仓库工具链固定版本。

**6. 动态阶段设计：只在高价值候选上收集 witness**

未来实验可在已准备的隔离环境中，对排序靠前候选做窄范围 instrumentation，而非整库动态 taint：

- 记录接口参数的抽象值、调用/返回、关键字段读写及关联对象 ID。
- 对 clone 记录源 cell 与目标 cell 的映射，对递归 schema 记录属性和实际执行 callable。
- 对状态机记录资源/epoch 与操作序列，对流记录 read/first-yield/EOF/close。
- 每条轨迹绑定 test parameter row、candidate hash、环境与 fixture 实例。
- P6 需要证明写与读访问同一 cell；E1 需要证明旧/new entry 的 identity；仅凭时间相邻不够。

仪器不能改变待测语义。并发只对候选 schedule 用 barriers 控制；对弱内存或真实调度敏感问题需专门调度器，不能承诺通用 Python trace 足够。

输出缺口至少分成：`UNOBSERVED`（未观察到合法联合执行）、`NONDISCRIMINATING`（联合关系存在但值/断言不足）、`ALREADY_WITNESSED`、`INFEASIBLE_IN_MODEL`、`UNKNOWN`。在本轮只有静态材料时，优先使用 `STATIC_CANDIDATE/UNKNOWN`。

**7. 区分能力：需要输入把差异激活，也需要 oracle 观察到差异**

为义务 u 构造有限的语义丢失假设集 H(u)，例如：不传播 metadata、跳过 normalization、将共享 cell 错分成两个 cell、跨实例仍共享一个 cell、跳过 pipeline action、延迟所有 yield 到 EOF。它们是通用操作类，不得从目标 hidden failure 或 gold diff 定制。

对于某个输入 x，若“保留该语义”和“丢失该语义”在观察投影 π 上相同，则 x 对此假设不具区分力：

```text
π(semantics_preserved(x)) = π(semantics_lost(x))
```

实际系统没有真实正确程序可调用。上述式子是定义，不能假装有 oracle。实现采用两种有明确边界的近似：

1. 对简单局部转换使用可解释符号求值，如 tuple/bitset 正规化、纯字符串变换和独立的算术 oracle。
2. 对其余情形使用选择性关系扰动/有限 mutants，观察输入及断言能否分辨；结合独立契约依据。只把它当 adequacy 证据，不当断言正确性的证明。

例如 `trim('abc')` 与不 trim 等价，`trim(' abc ')` 不等价；P3 无 shift 的位集合不会分辨 alias 去重；P6 只读两个初始相等 cell 不会分辨共享是否保持；P7 readonly 的值 oracle 不会分辨 action 丢失。

相应 DCC 报告应给出 `〈义务 u，激活 witness，传播路径，观察断言，已区分的假设 h〉`，而不是一个无解释的覆盖率数字。若给出比率，分母仅为本次可实例化/有 oracle 依据的 `(u,h)` 集合，另报 unknown 和未建模数量。该比率不代表所有真实 interaction bugs 的覆盖率。

尤其不能套用“生成的测试必须在 candidate 上通过，否则删除”的验证规则：本任务的 candidate 本来就可能有 bug。编译/fixture/前置条件错误应修复；有独立契约支撑的语义失败必须保留，而非让 LLM 把 expected 改成 actual。

**8. 从候选关系到可运行测试：约束式拼接**

生成单位是 AST/对象构造图/事件序列，不是两份测试文本拼接。

1. **抽取供体。** 分别提取输入/构造片段、入口调用和 oracle slice。保留 fixture 初始化、资源清理和参数与期望的关联。
2. **求统一映射。** 给变量、receiver、schema/closure、对象 owner 做 alpha-renaming 和类型统一。检查生产者结果可进入消费者；为有状态路径创建等价但隔离实例。
3. **选择一个主变换。** 初期只支持 representation substitution、entry lifting、shape lifting、alias-preserving clone、sequence extension、discriminating-value substitution。变换应有明确前置条件。
4. **生成 oracle。** 优先复用仍成立的已有断言；其次用 issue 明确后置条件；再次用已经独立核验前提的 metamorphic relation。API 等价对照是证据，不是默认可信的 reference。
5. **附带控制组。** 单项 A、单项 B、组合 A-with-B；状态型再加入 source unchanged、same-owner shared-state。若只有组合失败，能帮助定位，但不是逻辑上自动证明根因。
6. **执行检查（未来）。** 收集、编译、fixture、合法输入、目标关系 witness、重复性、oracle 和故障分类；最小化时保留关系 witness 和断言依据。
7. **闭环修复（未来）。** 给 coding agent 提供失败最小测试和独立契约证据；修复后跑原始与新增 tests。预算用尽或证据不足时 abstain，不能自动放宽规范。

| 生成操作 | 输入证据 | 必须验证的约束 | 典型 oracle |
|---|---|---|---|
| representation substitution | 路径/协议语法与原场景 | 编码后仍是相同领域对象 | normalized status、目标文件 |
| entry lifting | 等价 API/VM 入口 | 相同初态、参数、错误约定 | 已有结果断言/双路径关系 |
| shape lifting | callable、array/map 构造片段 | callable 真正穿过边界且之后被调用 | 叶子调用的可计算结果 |
| alias-aware clone | captured mutable state 与 clone 契约 | 内部共享保持、外部隔离 | write-one/read-other + source |
| sequence extension | 状态机与读写关系 | 合法转移、对象/epoch 一致 | 状态/异常/事件偏序 |
| discriminating substitution | operator 和 observer | 输入有效且不为恒等点 | 独立转换结果/关系差异 |

测试冻结文件建议包含：donor test IDs、版本 hash、relation witness、前置条件、契约摘录定位、oracle 来源、变换步骤、执行命令、结果分类。证据文件是可审计记录，不是形式化正确性证书。

**9. 少量 LLM 应放在哪里**

先由程序分析生成 top-k 的很小证据包：相关 issue 句子、已解析符号、少量 slice、已发现关系与未知项。LLM 只承担难以规则化的语义命名、接口语义对齐或测试框架适配。

| 任务 | 程序优先 | LLM 可辅助 | 最终验证 |
|---|---|---|---|
| 找 tests、实参、断言和绑定 | 是 | 一般不需要 | AST/runner collection |
| 找 R/W、调用及 alias 关系 | 是 | 为未知外部 API 提议 summary | 类型/源码/动态见证 |
| issue 义务映射到符号 | 部分 | 带原文位置的有限候选 | 规则一致性与人工抽样 |
| 选观察不敏感的值 | 简单域是 | 提议新的 witness | 符号约束/实际观察差异 |
| 拼接代码和 imports | 模板优先 | 未支持框架的局部适配 | 编译、前置条件、oracle |
| 判定测试失败是真 bug | 否，不能只看 rc | 可解释证据冲突 | 独立契约与 evaluator |

可预注册一个预算，例如每 issue 最多 3 个候选，每候选最多一次语义辅助与一次编译修复，并和零 LLM / 直接 LLM / 相同 token 预算方法比较。数字只是设计预算，需 discovery 阶段校准，不是本轮实验数据。

用户当前禁止将代码发往外部服务；本轮没有这些调用。未来少量 LLM 可以用获准的本地模型，或在另行明确授权的服务上使用白名单证据。纯程序分支应始终可用，遇到未知语义明确 abstain。

**10. 拟提出的 insight 及可证伪性**

H1：有“语义义务所连接的具体依赖关系”的 test/context 配对，比共享函数/文本相似性更能找到有效组合；在同预算下应显著降低无关和不可运行候选。若没有，应放弃复杂关系图或修改抽象。

H2：联合执行、值敏感激活和可观察性分层，比 branch/line coverage 更能发现真实候选缺陷。若新增 mutant score 上升但真实 bug 和修复收益无增益，不能以代理指标宣称成功。

H3：对 alias/epoch/事件顺序显式建模，能覆盖 scalar pairwise 参数矩阵遗漏的行为；需要在 held-out 的有状态/并发任务上证实，而不能只用 P6 回证规则。

H4：已有 test 的构造和 oracle 片段可降低生成成本，但必须结合前置条件和来源检查。若大部分有效测试都需人工提供 oracle，自动化主张必须收缩。

其中最有希望的中心贡献是：**用契约对齐的程序关系为组合建立义务，并寻找使该关系的语义丢失可传播到合法 oracle 的 witness。** 图、切片、SMT、mutation、LLM 都只是支持这一贡献的组件。

**11. 如何证明最终提高 issue resolution rate**

先固定 discovery set：本次 P1–P7 加 E1–E3；它们不能再进入独立 holdout。按 issue/task 家族划分，不能把同一 Textual issue 不同模型 trial 放到 train/test 两边；必要时按 repository 做更严格外推。

从公开 Flash cohort 按 task/model/语言/有状态行为预抽样并冻结。检查 trajectory、snapshot、测试输入和基础运行是否可恢复，报告所有排除项。失败和成功候选都要纳入，否则不知道新测试导致误修复和回归的代价。测试生成阶段隐藏 outcome/verifier/reference；评估阶段在冻结生成结果后由隔离 evaluator 使用官方验证。

建议分两阶段：

- **诊断阶段：** 固定 candidate，不让修复。评估关系候选精度、前置条件正确率、自动可运行率、有效 oracle 比例、真实缺陷检出、不同缺口类型的命中和 unknown 比例。缺口召回率只能在人工充分标注的子集上估计，不能将模型自己的候选集当全部真值。
- **修复阶段：** 从同一 candidate/checkpoint 给 coding agent 相同修复预算，随机/配对比较原 workflow 与加 DCC 的 workflow；输入只差新增测试及证据。分别报告 原失败→成功、原成功→失败、仍失败及不变。

主要终点：

```text
ΔResolution = mean(Y_DCC - Y_control)
```

其中 Y 是完整独立验证下的 issue 是否解决，分母为预注册可评估任务集。重复模型随机运行并按 task 聚类置信区间；不能把同一 issue 的多 trial 当相互独立样本。只统计“生成 test 使 candidate 失败”不能推出 resolution 提升。

基线应包括：等量随机/边界值扩增、constraint-aware pairwise、仅 shared-callee 关联、仅 PDG 关联、coverage-directed generation、同证据与预算的直接 LLM test generation，以及可移植的 MR-Coupler/SAINT 思路。原工具若受 Java/特定领域限制，只能明确称 reimplementation/adapted baseline，不冒充原工具原生结果。

消融至少去掉：契约平行路径、值敏感域、heap/temporal 关系、oracle discrimination、trajectory 临时测试、LLM。除 tokens 外控制测试数量、执行时长、agent 修复 tokens 和工具调用预算。报告 graph construction 与 instrumentation 代价。

**12. 范围与实施顺序**

第一版应以同步 Python/TypeScript 的字段/表示/规范形关系为主，接入 Go 的确定性调用/容器场景；接着做 alias 与 captured state；并发 epoch 与 stream liveness 作为后续扩展。P1–P4 适合快速验证管线，P6 是证明关系抽象价值的重要难例，P7 检验区分能力；E1/E2 防止把方法限定成输入 tuple 组合。

本轮交付的是方法设计和人工标注。下一步若实施，先做可解释的 obligation extractor 和证据核验器，再做有限模板生成器，最后加少量 LLM fallback。对动态反射、未知 native code、复杂字符串理论、弱内存并发、没有可信 oracle 的功能，明确输出能力边界。鲁棒意味着控制误报、可解释地 abstain、预算可控和独立验证，不意味着保证找出所有遗漏。

**附录 A：如何真正找到并提取 tests**

提取应同时覆盖三条来源，再按代码版本和情景去重：

| 来源 | 程序提取规则 | 必须保留的内容 | 不能直接推出的结论 |
|---|---|---|---|
| repository tests | 配置中的 test roots；pytest/unittest 定义；Go Test/Run/table；TS test/it/each 及类型测试；解析 fixture/helper 调用 | 名称、参数行、fixture DAG、执行入口、实参绑定、assertion slice、清理动作 | 文件名包含 test 就一定可收集；test-d 能检查运行时 |
| candidate patch | AST 节点对应关系识别新增/修改 test；合并完整 repository 定义 | base/candidate hash、test 变动、未修改但相关的 developer tests | 只扫描 diff 就拥有全部测试 |
| trajectory | 解析工具调用与 shell AST；跟踪 heredoc、文件写入/覆写、pytest/go test/脚本执行；保守恢复临时脚本 | step、cwd、文件版本、输入来源、可见输出、当时生产代码版本 | 包含 assert 的编辑脚本是 test；历史成功代表最终版本成功 |

静态阶段不执行任意 Python 表达式来展开参数表。只求值白名单常量、字面量容器和简单纯表达式；其余保留表达式和 unknown。测试发现与 collection 要分开，后者将来在隔离环境中执行，可能运行 import/fixture 代码。本轮只完成手工阅读，没有执行 collection。

情景分割依据数据流与生命周期：如果两个 act 使用同一 fixture 的同一可变对象且后一个依赖前一个，就保留序列；若是独立构造的实例，可以分成独立情景。一条 assertion 有时观察多个先前动作，必须从观察反向保留依赖。无法安全分割时保留整个 test 并标为 coarse，而非猜测独立性。

供体匹配的基本索引是 `resolved callee/field + contract role + input/observable type`。先找受 patch/issue 影响的 tests，再扩展到必要的 helper 与相关 developer tests；不要只保留 agent 新增测试，也不要把测试名称中的相同词当作关系证明。

**附录 B：一条候选从提取到生成的完整推导**

以 P2 为解释性例子。这里的人工推导属于 discovery 标注，未来不能原样注入 held-out 生成器：

```text
test A:
  input fields = {code:65, modifiers:4, text:absent}
  observation  = Key.character
  assertion    = character is None

test B:
  input fields = {code:0, modifiers:default, text:[97]}
  observation  = Key.character
  assertion    = character == 'a'

program evidence:
  nonzero shortcut branch produces Key.character
  associated text can reach the same field
  code==0 follows a distinct branch

contract:
  printable AND has_non_shift_modifier => character is None
```

第一步用断言切片找到共同观察字段，再用输入切片找到两个影响来源。第二步保留 A 的 guard 与 oracle 前提，只将 B 的 text 子结构迁入 A。第三步在协议约束下选择 `code!=0 ∧ printable ∧ has_non_shift_modifier ∧ text_nonempty`。第四步生成 typed input AST 并序列化，保留 `character is None` 及快捷键名称断言，同时生成 code=0 的正向控制。

这展示了程序分析的必要性：直接合并两份期望会冲突，合并整个 B tuple 又会进入 text-only 分支。数据角色、guard 和 oracle 前置条件共同决定可复用的片段。若 issue 没有可独立支持该条件的语义，系统应返回 oracle-unknown。

对 P6，同一个推导槽位从 scalar predicates 换成 `capture(f)=capture(g)` 和 `owner(c′)!=owner(c)`；对 E2 则换成 `first_yield < blocked_tail_read`。实现可以分成不同分析插件，但它们输出相同的义务与证据格式，不能声称一个普通标量 SMT 求解器就能处理全部语言和并发语义。

**附录 C：缺口判定与预算控制的伪代码**

```text
S = recover_versioned_scenarios(repository, patch, trajectory)
F = extract_scoped_facts(S, changed_code, issue_symbols)
U = infer_relation_obligations(F, supported_contracts)

for u in prioritize(U, evidence_strength, issue_relevance, cost):
    if preconditions_are_proven_inconsistent(u):
        report INFEASIBLE_IN_MODEL
        continue
    matching = match_same_scenario_identity_values_order(S, u)
    if supported_oracle(u) is unknown:
        report UNKNOWN with missing evidence
        continue
    H = instantiate_supported_semantic_loss_operators(u)
    if matching has checked_activation_and_observation_witness(u, H):
        report ALREADY_WITNESSED with the finite hypotheses checked
        continue
    candidate = instantiate_typed_template(u, donors=matching_or_partial(S,u))
    validate_input_and_relation(candidate)
    validate_oracle_independently(candidate)
    classify_and_preserve_semantic_failures(candidate)
```

这里的 witness 检查是未来可选的动态/符号验证步骤，不是当前脚本已提供的功能。匹配不到 witness 时，只能报告“在已恢复且已建模的情景中尚未建立证据”；不能从有限执行证明全体 tests 没有关系，也不能从 may-alias 直接声称已经联合执行。

第一版排序可采用透明的分层队列：独立契约明确且关系摘要完整的候选优先；其次是有可验证局部假设的候选；缺 oracle 或核心依赖未知的候选暂缓。每层按 patch 距离、现有供体可复用度和预计执行成本排序，同一义务去重。暂不需要训练一个“遗漏概率”模型，也不应在 10 个手工样本上拟合权重并报告预测性能。

有限语义丢失操作与传统 mutation 的缺陷激活/传播、数据流覆盖的思想相通。本方案需证明的增量价值，是面向候选修复的交互义务如何被发现、如何判定现有 suite 的缺口、如何从供体生成可靠的失败测试，而不是声称首次提出“覆盖并不保证发现错误”。
