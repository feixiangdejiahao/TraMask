# P1–P7：不依赖竞争实现的搜索反馈候选

2026-09-28。独立研究备选，没有执行新实验、没有调用 provider。本文件只讨论 candidate + 已有 validation + 可执行 trace 能提供什么，**不再要求生成正确 rival 或修复片段**。原 trajectory 证据见 [pilots.md](../trajectory_logic_20260928/pilots.md)。

## 结论先行

我建议考察一个较小的核心：**把测试看作对象与操作之间的绑定图，搜索尚未出现的绑定形状，并跟踪这些绑定是否被已有断言实际观察。**

它不是“检测某种自然语言关系”，而是一个实际可执行的操作：改接测试程序中的一条使用边。新增候选由语法、类型、作用域和真实对象流确定；反馈记录“这次改接是否成功形成新形状、哪个状态变化到达哪个断言”。不需要先知道正确行为。

这个方向目前能给出算法和可审核指标，**还不能诚实宣称具有已证明的新颖性**。类型引导序列生成、数据流融合、状态覆盖、checked coverage 都有直接先例。可能值得验证的改造，是以对象身份、生产边界、观察阶段限定图中的绑定，再把“新绑定但传播中断”的情况保留为高价值待检查项，而非只奖励已有实现成功传播的路径。

## 1. 为什么先从绑定而不是功能名入手

P1–P7 中，很多功能已经出现，问题在于被绑定到了哪个具体对象、哪条生产路径和哪个观察阶段：

- P2 的非空 text 与 shortcut modifier 必须进入同一个 packet。
- P3 的 shifted metadata 与 shift bit 必须共同参与同一 event 的 alias 生成。
- P5 的 nested callable 必须来自一次 Go Call 的返回，而不是 compiled.Get 已存的容器。
- P6 两个不同 closure 必须共同指向同一 capture cell，clone 后再经不同根写读。
- P7 运行时 parse 必须消费含非恒等 transform 的那一个 recursive schema；“其他 type test 有 transform”不能替代这个绑定。

这些差别至少有一部分能由实际 reference/value flow 区分。单纯函数名集合、调用次数、两段代码是否都执行，无法保留它们。

## 2. 可计算的对象：有界的测试绑定图

对每个测试执行构造一张小图。仅跟踪在验证入口、修改区域和断言切片附近的对象，限制 access-path 与 call-context 深度。

**节点是程序实体，不是LLM写的标签：**

- 一个可构造值的 definition site；
- 一个实际调用的 receiver / argument / return 位置；
- 一个 field / index / closure-capture 访问位置；
- 一个断言实际读取的值和正常/异常 continuation。

**边从三种机械事实获得：**

1. def-use：该实参/receiver/字段内容来自哪一次定义；
2. heap binding：哪些访问路径到达同一 runtime 对象或捕获单元；
3. boundary crossing：值经过哪个公开调用的参数/返回位置、再被哪个消费操作使用。

比较不同测试时使用源位置、参数位置和有界访问路径规范化；**不把裸地址或每次新分配的实例编号当新行为**。同一 execution 内的对象身份必须保留。例如两个变量来自相同 allocation site，不代表它们是同一对象。

图的有限节点/边上附程序直接给出的抽象值：源代码谓词的真值，optional 字段存在性，runtime type，受支持原语的 empty/nonempty / zero/nonzero，以及 source comparator 常量附近的取值区间。这是有限谓词抽象；不让模型先发明“与本任务相关的所有维度”。

例如 P2 的格子由真实源码给出：`other_modifiers` 空/非空、`text` 空/非空，两者是同一次事件构造的实参/控制来源。P5 的格子则是某个 callable receiver 的来源：Get-return 还是 Call-return，是否经过容器 member。**这不是一个固定关系枚举表**：格子位置来自该仓库实际 def/use 与 source predicates。

需要注意，若只保存 def-use 源位置，不保存 concrete-object alignment 与 bounded producer context，这一抽象仍会将P5/P6错误合并。

## 3. 一个通用的一步搜索操作

给定一个 test 使用位置 `u`，它目前绑定值 `v`。在当前作用域或可搬入的前缀片段中，枚举另一个可构造值 `v'`，执行：

```text
redirect one use edge: u ← v'
```

替换时：

1. 类型与实际动态类别相容；
2. `v'` 的必要 setup/fixture 和 side effects 被保留；
3. def-use 决定需要改哪些引用，不按变量名做全局文本替换；
4. 跨 scope 搬运时显式重新绑定 free variables，不能把不同closure的同名局部变量当同一cell；
5. 原输入与原候选程序不改，只改测试AST。运行后以trace确认预期绑定真的建立。

在缺少现成 `v'` 时允许一层类型合法 constructor extension `v'=C(v)`，`C`必须是仓库/测试已出现的constructor AST，或明确前端文法给出的构造。随后可以再改接一个member/call使用边。每步都有真实AST diff，不存在 `construct_relation(name)`。

**优先级的来源。** 为一个消费位置收集已经见过的producer、值类别与共享形状，生成该位置尚未见过但类型合法的邻接改接。先试新增AST最少、已有assertion后缀仍可运行的候选。这个优先级只看未覆盖的绑定格子和构造成本，不看case标签或隐藏target。

例如将P7 runtime parse的schema参数改接到type-only test的真实schema表达式，比从零写递归schema短；P5将已有nested成员调用后缀改接到Call-return，比任意拼两份完整脚本更有针对性。但**如果原Call返回的不是容器，就不能靠改接伪造容器**；必须生成新的factory输入，见第7节。

## 4. 反馈必须分开“关系建立”与“关系被检查”

只奖励taint到达oracle有一个危险：实现的错误可能恰好切断需要的依赖。P6 bug把共享cell复制成两个cell，如果只有传播成功才得分，搜索会惩罚目标bug并把它丢弃。

因此保留两个可审核集合，而不把它们混成一个神秘分数：

- `B(T)`：实际实现的新绑定形状/抽象值组合，以入口输入和具体对象对齐确认；
- `O(T)`：这些绑定后续涉及的状态，哪些被哪些断言读取，读取发生在哪个正常/异常阶段。

还记录从入口到观察之间的**传播结果**，至少区分：实际到达、实际未到达、分析未知。未到达不是“没有价值”，更不是“没有bug”。

低成本版本可用 dynamic backward slicing 得到 `O`，但只能叫dependency evidence，不能称observer充分。更强版本对test做一个合法小干预（候选程序保持不变）：改变一个输入值或插入已有状态写操作，重复执行，记录哪个被检查的具体值发生变化。干预由同一AST操作给出，可直接复核；不是构造另一个实现。

**不能将“输出必须改变”作为充分性门槛。** P2正确实现就应在不同associated text下保持character=None；P6错误实现恰好不会把writer变化传到reader；二者都可能呈现不变。反馈仅说明当前操作—观察之间发现/未发现响应，不能判定哪种响应正确。保留已有强断言，或在有独立契约时生成新断言；没有oracle的样例只能进入待裁决池。

也不能将 `assert x is not None` 读到x算作已充分验证x。可选的assertion-only局部检查是在固定合法候选值域中求该谓词能排除什么值，这只测断言判别范围，不给出正确值集合。若值域未知，就报告未知，不造“可靠性分数”。

## 5. 可以直接审核的度量

不声称拥有全部可能组合的分母。固定源构件、context深度和输入抽象后，报告：

1. **可构造改接数**：冻结的有界文法中类型/作用域合法的候选数量；另外报告动态有效率。
2. **新绑定格子数**：候选确实建立了多少之前未见的producer→consumer、共享形状及程序谓词联合取值。需附每格的source位置、AST diff与trace证据。
3. **观察连接比例**：已形成格子中，有明确断言读取相关状态的比例；按正常/异常阶段分开。它是checkedness近似，不是正确性。
4. **干预响应表**：每个干预对哪些checked values产生响应；保留未响应及unknown，不用一个总分抹平差异。
5. **同预算缺陷检出与误报**：只有独立oracle支持的失败才算检出；无oracle的新格子不算bug。已有target只用于最终评估。

主要消融是相同构件与相同运行预算下：按line/edge coverage保留种子、按普通def-use保留、按对象/producer上下文保留、再加入观察反馈。若绑定格子上涨却不提高缺陷检出，应否定它作为好的搜索奖励，而不是再增加几十种关系标签。

## 6. 如何由原语推导P1–P7：哪些真的能、哪些目前不能

| Case | 从candidate/tests可直接提取的结构 | 一步或少量改接的机会 | 尚未解决或不能强称自动的部分 |
|---|---|---|---|
| P1 | 多种序列进入parser并产生Key；phase断言；正则分组/结尾族 | 将事件phase观察的输入producer绑定到其他编码族 | 候选不支持的合法协议组合无法仅从候选正则推导；需协议grammar/encoder。不能把regex拒绝都当bug |
| P2 | `other_modifiers`、`text`、同一Key构造与character断言 | 同包填入非空text，保持shortcut modifier | regex字段化encoder需要实现；断言契约来自issue，覆盖奖励自身不知道None正确 |
| P3 | modifier各位与shifted_key共同流入alias构造 | 含shift取值绑定到已有alternate packet | 若实现从不消去shift，分析仍不知道这种消去正确；保留原alias契约或求局部LLM语义 |
| P4 | Path→magic字符串→真实文件操作、directAPI观察 | 换含特殊字符的路径，通过真实encoder接到magic | agent tests无quoted-path producer；合法shell quoting需前端/明确library encoder |
| P5 | Get→container→member→Call、Call→single closure→Call 两条真实生产路径 | 复用member/Call后缀，优先探索另一producer边界 | 仍需guest AST把factory返回值变成含callable的container；Go Object类型不能自动做到 |
| P6 | 单closure capture、clone、source isolation、重复状态写 | 改接读/写roots到共享cell shape，clone后交叉使用 | 现有tests没有双closure共享cell构造；需guest词法绑定前端或局部构造提案。实际实现打断alias时应保留样例 |
| P7 | runtime parse schema参数；type-only test里真实transform schema AST；recursive constructor | 将runtime parse绑定到已有transform schema，保留到达child的input | 新value expected不能简单照抄input；length这种表达式可直接求值，否则oracle未知 |

这张表最重要的是P1/P4/P5/P6四项前端缺口。**绑定反馈不等于凭空生成缺失的合法结构。** 与rival路线不同，这里缺的是测试输入构造能力而非第二个正确实现；前者通常局部、可验证，但仍不是免费。

## 7. 工程上应做什么，哪些只是研究假设

### 已有可复用条件

仓库已经恢复了17条candidate、validation AST/片段与执行harness；已有结果说明保留原断言至关重要。无需再向模型发送整个仓库，也无需先写正确reference。

### 可实现但本轮尚未做的前端

- host AST def-use、scope、调用参数/返回端口及断言读取；
- 关键boundary和对象field的runtime identity/producer标签；
- closure捕获映射及正常/异常continuation；
- 正则字段/SQL/Tengo等明确guest parser，只选实际支持的子集；
- 输入AST重写与原fixture完整重放。

跨Python/Go/TS全部同时实现仍很重。学术原型应先冻结一种host/guest组合，验证反馈比普通dataflow是否增益，而不是把多语言适配当作贡献。

### 真正未证的研究假设

- agent遗漏更集中于**绑定上下文的空格子**，而非任意新值；
- 保留object identity/producer边界能以可接受开销给出比传统dataflow更有效的搜索奖励；
- 观察反馈能减少“生成了组合但断言看不到”的浪费；
- 对传播中断单独保留候选，能避免单实现反馈主动筛掉依赖被破坏的真实bug。

这些需要等预算控制组，不能由7例事后解释证明。最小研究问题可以是：在已有validation和固定可构造输入文法下，对象与producer敏感的重绑定搜索是否比普通dataflow融合更快产生被有效断言检查的新交互？

## 8. Primary prior art 与新颖性边界

以下来源均在本轮直接查阅primary论文/官方会议信息。没有从二手摘要推断论文不存在某种能力。

- **Randoop，ICSE 2007。** 已有通过执行反馈生长调用序列，因此“收集类型可用对象、扩展方法调用”不是新贡献。[作者页](https://homes.cs.washington.edu/~mernst/pubs/feedback-testgen-icse2007-abstract.html)
- **Checked Coverage，ICST 2011。** 通过断言的dynamic slice衡量被检查的执行；说明运行到某行不等于结果被检查，也意味着我们的观察连接统计已有直接基础。[作者论文](https://www.st.cs.uni-saarland.de/publications/files/schuler-icst-2011.pdf)
- **Observable MC/DC，ICSE 2013。** 把条件覆盖加上到oracle的非masking传播义务，并提供tagged semantics。因此“依赖必须传播到观察”不是创新。本案额外难点在对象身份、作用域和候选本身可能漏掉依赖，不能直接用已发生传播筛掉所有未响应样例。[作者论文 §II–III](https://greg4cr.github.io/pdf/13omcdc.pdf)
- **DATAFLOW，FUZZING Workshop 2022 registered report。** 对def/use覆盖的精度/成本进行研究，明确其初步结果中许多target纯control-flow反馈更好。这是反证风险，不能笼统说dataflow必优；也不能被NDSS网站当前导航误导成2026正会论文。[原始PDF](https://www.ndss-symposium.org/wp-content/uploads/fuzzing2022_23001_paper.pdf)
- **FlowFusion，USENIX Security 2025。** 已将developer tests表示为dataflow并融合多个test，目标是PHP解释器memory errors。故“按变量依赖拼测试比直接concat好”已存在；我们必须比较对象/producer上下文与语义断言反馈究竟增加了什么。[官方页面](https://www.usenix.org/conference/usenixsecurity25/presentation/jiang-yuancheng)，[论文](https://www.usenix.org/system/files/usenixsecurity25-jiang-yuancheng.pdf)
- **WITFuzz，ISSTA 2026。** 官方摘要说明其在resolved WIT AST上做结构重写和相关更新，且用分层build oracle捕获生成阶段之后的错误。这为结构合法性与后续阶段观察提供直接参照；“LLM扩展rewrite策略”本身也不应再被当作创新。[官方收录页](https://conf.researchr.org/details/issta-2026/issta-2026-research-papers/190/WITFuzz-Validity-Preserving-Greybox-Fuzzing-for-WebAssembly-Interface-Type-Binding-G)
- **NIST combinatorial coverage。** 已有输入联合取值覆盖的成熟定义。若我们只把源码谓词转成pairwise表再补格子，仍是code-aware interaction testing，不能因换上object字段而自动成立贡献。[NIST原始报告入口](https://www.nist.gov/publications/combinatorial-coverage-measurement)

最终判断：这比竞争解释路线少一个不必要的困难，且给出了真正一步可运行的搜索操作。但它目前仍是一个**需要实证验证是否超越dataflow fusion的具体候选**；不能将几种已有技术写成大流程之后宣布学术抽象已解决。
