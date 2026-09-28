# 从十条轨迹得到的研究假说：验证见证的关系闭包

状态：本文保留 2026-09-26 提出的案例驱动研究假说。2026-09-28 已开始实现有限子集，当前算法及完整评价见 [实现说明](../relational_gap_method_v2.md)；下面的完整闭包定义仍是研究目标，不能等同当前能力。十条主案例见 [案例总表](README.md)，历史验证、候选代码及本地重放见四份分组报告。本文件不把人工挑出的失败见证算成自动生成成功，也不声称已证明泛化效果。

## 1. 核心问题应该如何改写

本轮证据支持的研究问题是：**已有验证分别覆盖了参与者，却没有覆盖这些参与者在同一状态、同一观察下可能成立的关键关系。如何自动补齐这些关系的见证？**

例如，go-git 已测两次修改同一行，也测两次修改不同行；缺的不是第二个修改操作，而是“起点不同、区间相交”。Pebble 已测已完成序号和很远的未来序号；缺的是“目标等于刚完成范围的排他上界”。Koota 已测所有字段显式给值和所有字段用默认值；缺的是同一个 record 内两种来源混合。

因此，不能把目标定义成拼接两个 test、增加功能标签的二元覆盖，或寻找两个测试位置是否存在调用依赖。上述操作可能完全不改变被测关系。反过来，etree 的目标恰好是两个修改**应该独立**：共同祖先导致的 may-dependence 不能证明它们应该冲突。

**建议只保留一个核心抽象：带观察的关系单元 `(q, ρ)`。** `q` 是已有可执行观察；`ρ` 是描述其相关输入、对象及可控事件安排的可执行约束。一个测试是该单元的“见证”，只有当运行真正实现 `ρ`，并在对应对象和阶段执行 `q` 时才算观察覆盖。观察覆盖与有效断言检查必须分开：打印 `closed` 和断言 `closed=true` 不等价。检查是否充分还取决于对 `q` 应用的断言及其契约依据，见下文。有效失败测试也算已经检查过该单元。

`ρ` 不采用模型生成的自然语言 feature 描述。例如：

```text
go-git:   fileA = fileB ∧ sA < sB < eA < eB
Pebble:   db_wait = db_commit ∧ target = batch.start + batch.count
Koota:    0 < |keys(payload)| < |fields(schema)| ∧ read_before_flush
HTTPX:    response_decode = response_observe ∧ live_stream ∧ payload=已有非法输入
```

这四个表达式分别是区间、整数、集合和事件关系。其语义来自运行值与源码位置，不依赖模型每次给它取什么名字。等式中对象相同表示同一次测试的身份绑定，不是不同 tests 的运行对象地址相同。

## 2. “关系闭包”的有限定义

给定最终候选版本 `P` 及观察 `q`，从程序与已有验证中选定有限的相关位置集合 `Vq`，以及有限的关系谓词集合 `Rq`。每个候选单元只选至多固定 `k` 个相关谓词，不枚举全项目的全部赋值；可将单元写成约束 `ρ`。只考虑由当前支持的测试构造片段、有限参数候选域及动作预算 `B` 能实现的单元：

```text
U_P(q) = { ρ | ∃ t ∈ G_B(existing validations): trace_P(t) ⊨ ρ
                                             且 t 可执行观察 q }
Observed_P(q) = { ρ ∈ U_P(q) | 已有运行在相同对象/阶段观察 q 并满足 ρ }
Checked_P(q) = { ρ ∈ Observed_P(q) | 运行对 q 执行了适用且有独立依据的断言 }
Gap_P(q) = U_P(q) \ Checked_P(q)
```

`G_B` 是有限的测试构造空间：既有构造器、调用、有限插入位置及有限参数候选域。仅限制动作长度并不保证有限；整数/字符串孔也要有冻结的位宽、长度或枚举值上限。所谓补齐闭包，就是为 `Gap_P(q)` 搜索短见证。关系不是所有变量对的笛卡尔积：从相关操作的汇合处及其控制条件取得关系候选，例如 Pebble 的 target 与 completed-high；同时保留源验证的对象绑定、effect和契约提供的关系，即使候选代码中相应依赖缺失。

`ρ` 描述测试如何安排输入/资源，不能包含待检义务已经正确成立这一要求。HTTPX 的可控条件是向同一真实流提供已验证的非法数据，“必须抛错并关闭”属于断言；SQLite 的可控条件是写入会违反已注册SQL谓词的数据，“必须执行validate”不能成为测试合法性的前置条件。

完整的 `Checked` 是规格相关定义，任意断言的正确性不可由程序普遍判定。原型只能对依据可确认的部分计算它，其他记录 unknown；不能把两个成功样例归纳成定理。历史不同版本的结果也不能直接并到 `Observed_P`：要在最终候选重放，或只标为历史种子/未确认覆盖。

这是**相对于所选谓词、可构造片段、观察和预算的覆盖定义**，不能当作整个 issue 的完备性证明。实际算法按需求见证，不预先精确计算 `U_P`；求解超时、未知别名、恢复不了的环境均保留为 unknown。观察覆盖不能仅靠源码出现了两个 API 来填充，断言是否通过更不能替代适用性判断。

## 3. 围绕这个抽象的一个算法

算法可压缩为：**找到相关关系 → 扣除已有见证 → 求最小新见证**。大模型不参与缺口集合的自由定义。

### 3.1 从哪里得到关系，如何快速找到源测试 A

先恢复实际执行过的验证片段，保留测试定义、调用、输出和执行时的候选版本。临时脚本和后来删除的测试也要保留；仅定义但没执行的 tests 不算已观察事实。断言沿 def-use 反向切片收集输入和调用；状态操作还需要 receiver/heap effects、控制条件和 fixture/setup。只做局部变量切片会漏掉 `flush`、`close`、DB 更新等操作。

按“被观察对象/字段、访问入口、控制谓词来源”建立倒排索引。若分析发现某个 `get` 返回分支或某个等待判断相关，只检索实际观察对应状态的 tests；同文件、关键词命中仅用于定位，不作为语义证据。**A 是带着某个观察义务的可执行种子，不要求它包含最多相关关键词。** 同一个 A 可以产生多个关系单元；B 可以提供另一条可构造路径或参数来源，也不必强行找一对完整测试。

对 `q` 的静态 may-slice 及相关调用入口，定位数据汇合与控制分叉：比较运算两侧、同一 record 的字段来源、同一资源的正常/异常出口。使用实际参数代换跨调用传播表达式。相关范围同时包含断言前动作的前向 effect slice，不能只用候选当前运行的 backward dynamic slice；例如 SQLite 的 bug 已经把 validate 路径跳掉，动态依赖恰好会消失。

最小的机械抽取规则可以精确定义为：在与观察相关的 SSA 比较 `x op y` 处，沿有界 def-use 与实际参数代换恢复两侧表达式；若都落在所支持的整数/有限枚举表达式语言内，枚举 `<,=,>` 可满足单元，并使用运行插桩核实值关系。不支持的表达式返回 unknown。这条规则只依赖程序结构；但它本身接近经典边界值/符号测试，不能单独宣称新颖性。

区间、默认字段和资源关系是候选扩展域，必须定义额外可复用的识别规则或库摘要。**整数类型不能自动证明某个字段是区间端点；record语法不能自动证明默认值契约。** 下表是设计范围及识别需求，不是已具备这些语义识别能力的声明：

| 可分析构造 | 有限关系划分 | 如何实现一个缺失单元 |
|---|---|---|
| 数值比较 `x op y` | `<, =, >`，结合实际 guard 的上下界 | 保留 setup，求使 x=y 等成立的参数；优先复用生产动作的返回值 |
| 两个区间的端点 | 满足各自 start≤end 的端点序关系 | 求可满足的排序，如 sA<sB<eA<eB；不手写“Go merge 专用变换” |
| 同类型资源/键 | 相同身份、可证不同身份；未知分开记录 | 将两个来源绑定到同一个构造对象或可验证的规范化 key |
| record 的 presence/default 分支 | 全显式、全缺省、显式与缺省共存 | 从 schema 实际字段集合选择两个不同字段，保留一个并省略一个 |
| 资源出口及阶段 | 正常/异常，操作前/后 | 用已有异常输入触发同一资源的异常路径，并将已有观察放到对应出口 |

这张表是有界抽象域的初始设计，不是已经完成的多语言分析器，也不保证每个领域都能精确求解。一般对象的“相同物理资源”、任意字符串路径的作用域、SQL谓词和复杂异常传播不由简单AST自动解决。第一版应该冻结支持范围；对不支持的关系如实记为不可恢复，不交给LLM任意杜撰一个替代关系。

### 3.2 用一个约束目标生成测试，而不是选任务专用变换

对未见单元，求一个对原验证修改最少的可执行测试：

```text
t* = argmin_t edit_distance(t, seed)
     subject to t ∈ G_B
                valid_setup(t)
                trace(t) ⊨ ρ
                q 观察的对象和阶段与 ρ 一致
```

数值和有限集合可用约束求解；复杂构造先枚举既有参数/调用片段，再用真实执行检查是否达到 `ρ`。这仍是同一个关系见证搜索，不需要模型先给任务选择“clone变换”“iterator变换”等名词。约束还不能实现时，结果是未生成，不是合法组合已通过。

固定预算下使用可复现的字典序：已有明确 oracle 依据的单元优先；其次预计编辑距离；再按源码位置排序。对同一个关系单元的多个同构测试只保留短代表，不靠人工 pilot 命中率调一串权重。是否比旧排序有效必须在未见任务上测量。

```text
for q in recover_observations(executed_validations):
    R = relations_at_relevant_joins(q, source, validation_traces)
    checked = replayed_and_justified_cells(R, final_candidate, q)
    for ρ in bounded_candidate_cells(R, excluding=checked):
        t = best_witness_within_budget(seed_for(q, ρ), ρ)
        if t exists:
            attach a justified oracle; execute; record cell and result
```

上式 `argmin` 是搜索目标；预算用尽时只能称 best-found，不能宣称全局最小或不可满足。输出区分找到见证、支持片段内已证不可行、未知。整个算法的新研究对象是 `ρ`，而不是更大的 prompt、更多脚本类型或更复杂的输出schema。恢复 tests、启动容器是必要支撑，但不应被当作论文核心贡献。

### 3.3 观察与预期从哪里来

`q` 只告诉我们观察什么，不自动告诉我们在新关系下什么结果正确。这里保留一个不可略过的前提：**新测试的期望必须有独立于候选当前输出的依据。**

- 若上下文在契约上不改变结果，例如显式默认 mode 与省略 mode，保留源断言；适用性来自参数契约及已有接口语义，不能仅由“静态上可拼接”推出。
- 若关系本来改变结果，例如两个区间由分离变成重叠，继续使用已有 conflict 观察，但从冲突规则和已验证的冲突侧取得期望；不能保留分离场景的 `no conflict`。
- 若源观察看不到遗漏效果，例如 Koota 只读 vx，需要检索另一个已有字段观察或完整 record 观察。没有可恢复的观察时记为 oracle/observation gap，不能把通过当成没有缺陷。
- SQLite 需要让输入使 invariant 为假。读写字段交集是必要的候选条件，却不充分；还要构造跨阈值输入。期望“拒绝并回滚”来自 issue/契约及源拒绝验证。

少量 LLM 的合理位置是：当代码与既有验证无法决定一条局部契约时，提出小的、可执行的关系或期望表达式，并指出依据。LLM 提案仍需固定输入、记录输出和独立校核；类型检查、有限表达式语言、源例子一致性都不证明契约正确。核心的 `Rq/Observed/ρ` 与执行结果不由模型自由改写。无法确认期望的项不能计为 bug，但应在 recall 分母中保留其未解决状态。

**尤其不能要求新关系在 buggy candidate 中已经传播到 q，才允许生成测试。** 缺陷可能正是传播边被删掉：bulk没有validate，异常没有close。用候选行为作硬性的“断言敏感性过滤”会把目标缺陷全部过滤掉。观测可达性和敏感性应在源控制、独立契约或限定的对照中分析；mutation存活只提示检查不足，不能自动证明原断言无效。

## 4. 一个完整例子：Pebble

历史测试 A 在一个 batch 中写两条记录。设起点为 s，它验证等待 s、s+1 都成功。历史测试 B 等待很远的100000，验证它尚未完成。两者都通过。

等待实现读取 `target` 和 `highestDurableSeqNum`。候选代码自己把后者定义为排他上界，更新表达式为 `start+count`。程序分析把这两个值选为相关位置，得到 `<,=,>` 三个关系单元。

A 覆盖 target<high，B 覆盖 target>high。target=high 没有见证。因此求解器无需理解“Pebble是什么”，只需在同一 DB 上构造一个 batch，令 `target=batch.start+batch.count`。最短例子写一条记录，立即订阅下一序号，然后检查当前未ready。

候选错误地用 `target<=high` 返回成功，所以组合失败。这是**关系的边界补齐**，而不是把“写入测试”和“等待测试”直接首尾连接。公开完整仓库测试与本轮候选函数组件重放都支持此根因；本轮组件中的起点10是合成值，未执行真实WAL。精确证据见 [G4](go_cases.md#g4pebble成功范围和未来等待的边界没有绑定到同一状态)。

## 5. 十例对自动化设计的支持程度

下面是事后可分析性评估，**不是自动提取成功率**。我们已经知道失败，不能据此声称未来分析器会自动发现所有关系。

| 案例 | 关系单元中的关键变量 | 程序依据 | 自动化仍缺什么 |
|---|---|---|---|
| HTTPX JSON | live response、exception exit、closed观察 | receiver身份、异常CFG、close是否后支配出口 | 流构造与外部资源效果摘要 |
| HTTPX multipart | 同上，decoder换成multipart | yield-from异常边与后续close | 异常生成器路径及async对等关系 |
| mnamer | 两来源的normalized path相等；quota有限 | 路径生成、排序、take(k)、消费去重 | 跨Path/CLI的资源身份，成功消费与额度契约 |
| SQLite | UPDATE写age；invariant读age；age<18 | 参数传播使table=None、SQL读写集合 | SQL表达式解释、数据库状态构造；仅may依赖不够 |
| termenv | entry=Output；width≥visible_width；preserve | 两入口callee汇合、早退guard | ANSI度量函数摘要及保留style的契约 |
| etree | 共同parent；text写与child插入的effects独立 | 路径前缀判断及op类型 | 精细作用域；字符串prefix不等于语义effect冲突 |
| go-git | 两区间部分重叠且起点不同 | baseStart/baseEnd、扫描推进 | 从文本构造稳定hunks；组件注入不能替代此前端 |
| Pebble | target=exclusiveHigh=start+count | update与wait共享tracker字段 | async就绪观察、真实DB序号及WAL环境 |
| Koota deferred | 同record部分显式部分默认、flush前 | hasParams整体guard、schema字段集合 | trait构造器与字段级默认值摘要 |
| DynamoDB | 同options省略mode与默认put、requiredIf生效 | wrapper参数传递、默认化与guard | 条件schema构造与Zod效果摘要 |

因此不应承诺“一套简单静态依赖分析自动覆盖十例”。更合理的原型主张是：**在可恢复的关系域内，有界补齐相对当前验证尚未见过的关系单元，能否以更少测试发现更多真实缺陷？** 对复杂effect推理的支持应通过独立实验增加，而不是每看到一例加一个专用分支。

## 6. 论文 insight 与新颖性边界

参考2026论文是学习如何把问题缩成可计算对象，不是把论文标题贴在工程流程上。以下三篇的会议收录及核心方向来自官方摘要；未据摘要宣称复现了其算法或结果。

| 工作 | 可以借鉴的研究切入点 | 本设计需要另行证明的差异 |
|---|---|---|
| [MR-Coupler，FSE 2026](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/200/MR-Coupler-Automated-Metamorphic-Test-Generation-via-Functional-Coupling-Analysis) | 用功能耦合约束值得搜索的方法关系，再生成和验证测试 | 我们寻找既有验证未见的对象/值/事件关系单元；不要求存在蜕变关系，也不以method pair本身为覆盖单位 |
| [ConUT，ISSTA 2026](https://conf.researchr.org/details/issta-2026/issta-2026-research-papers/169/ConUT-Condition-Aware-Test-Generation-for-Complex-Java-Code) | 从目标条件反向追到可设置字段和调用，弥合条件与输入构造的距离 | 此处目标是关系单元及其观察，而非仅到达分支；仍需证明关系目标比普通branch目标有价值 |
| [Feature-Focused Test Generation，ASE 2026](https://conf.researchr.org/details/ase-2026/ase-2026-research-track/183/Feature-Focused-Test-Generation) | 从输入grammar导出可计算的feature配置，用专化grammar生成有效输入 | 我们没有现成grammar，必须从执行过的验证与程序位置恢复有限关系；这既是潜在贡献，也是主要困难 |

还有两项不能忽略的既有研究：**程序数据流筛选值得组合的交互并不新**，[Identifying Interactions for Combinatorial Testing using Data Flow Techniques（2015）](https://doi.org/10.1145/2674632.2674643) 已研究这一方向。**结构覆盖不代表错误能被断言观察到也不新**，[Observable Modified Condition/Decision Coverage，ICSE 2013](https://greg4cr.github.io/pdf/13omcdc.pdf) 将观测传播要求结合到MC/DC中。

所以“dependency + pairwise + observable oracle”不能直接作为创新声明。可争取且可被反驳的贡献是：**从 agent 的实际验证见证恢复关系域，并以身份/阶段一致的关系闭包定义和生成缺失验证；在不预先人工建feature model的条件下，优于等预算的组合覆盖与分支导向生成。** 目前只有发现集证据，是否足够新颖和有效仍取决于系统性相关工作比较与盲测结果。

## 7. 如何验证，避免再次围绕pilot修补

原七例与这十例全部封为发现集；补充与排除样例也视为已见，不能悄悄放进blind test。先冻结关系域、抽取规则、预算及排序，再按仓库划分新的失败和成功trials。两个HTTPX任务不能拆到训练/评价两边来夸大独立性。

要区分三个问题，并逐层报告分母：

1. **关系恢复**：人工独立标出的目标 `(q,ρ)` 中，程序可恢复多少？不可解析、环境缺失、关系不支持分别列出，均不能从总体漏报分母消失。
2. **缺陷检出**：固定预算下有正确oracle且确实暴露候选缺陷的trial比例、确认报警precision、未确认数、每个有效缺陷消耗的测试/模型调用。10条全是选择后的失败正例，不能估计总体precision或误报率。
3. **修复收益**：相同agent、模型、起点与预算，有/无新测试的配对修复，比较最终独立verifier的issue resolution rate。生成有效失败见证不等于agent一定修复。

必要基线是原算法、等预算随机参数/上下文组合、普通pairwise特征覆盖、分支目标生成。关键消融只移除三项：关系约束、身份/阶段绑定、观察约束。若普通CIT加边界值就达到同样效果，应接受这一结论，而不是继续添加case规则维护新方法的表面优势。

误报主要来自oracle适用性错误、may-alias过粗和不可行关系；漏报主要来自关系/对象恢复失败、缺观察和预算。排除样例如SuperJSON、Bandit、Tengo明确说明：**已经执行目标组合却接受错误期望**，不能靠补关系覆盖自动解决。这是本抽象的边界，而不是再加一种模板就应包办的功能。
