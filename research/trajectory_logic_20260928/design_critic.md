# 独立方法批评：可执行语义 version space，还是测试构造语法？

2026-09-28。本报告只评估方法设计，不调用 provider、不生成新实验结果。N01–N04 的原始证据和哈希见 [python_sql.md](python_sql.md)。STARS 的结论只依据已下载论文及 [阅读笔记](../stars_abstraction_review.md)。

## 1. 对 version-space 提案的判断

**它是合理的选测试目标，但目前还不是解决测试合成的核心算法。** 写成下式已经相当精确：

```text
H = 所有与当前 validations 的观察一致的候选语义程序
选择 t=(input, observer)，使 {observer(h(input)) | h ∈ H} 尽量分裂
再由独立 issue 契约判定哪个结果正确
```

然而，困难仍在第一行。多个程序符合有限样例、再通过查询区分意图，是 program synthesis/PBE 的经典问题；version-space algebra 本来就是压缩表示候选程序集合及其运算的工具，不能把这些既有性质当作本工作的创新。[Gulwani、Polozov、Singh 的 Program Synthesis，§7.2](https://web.eecs.umich.edu/~weimerw/2024-481F/readings/Gulwani17.pdf)

保持假设对称、不默认候选正确，是契合当前任务的重要前提，但不是足以独立支撑论文的构造贡献。与给定的 AdverTest/Testora 定位相比，也仍需证明新方法怎样从输入材料确定性地恢复其他工作没有的、值得区分的程序结构。这里没有重新检索这两篇论文，故不将父任务概述扩大成已核验的详细 novelty claim。

### 四例具体暴露的假设构造问题

| Case | 容易写出来的两种假设 | 实际尚未解决的构造工作 |
|---|---|---|
| N01 | 仅正常退出关闭 / 所有已消费后的退出关闭 | close 位于底层 iterator，exception 在 parser；要恢复跨层对象与退出关系，并生成 try/finally 等效变体。轨迹中没有一份已经正确的替代程序可直接取用。 |
| N02 | post-yield close / finally close | 此例候选 AST 改动小，但必须排除消费前 header 拒绝；把 entire method 包 finally 会引入不同契约。所谓“小孔”已经需要 phase 分析。 |
| N03 | raw candidates 计预算 / distinct-successful resources 计预算 | 需要恢复 path identity、去重位置，以及按候选数或成功数扣配额。把 `[:k]` 换个常数不是正确假设；新增 dedup 或改变循环记账是新的算法。 |
| N04 | bulk 不验证 / 验证写到的表 / 验证所有表 | `table=None` 是表面小孔，但填入真实表需要 SQL 解析、表集合与跨连接 identity；多表语句、trigger、quoted names、缺失 table 参数都不是一个标量替换可解决。 |

若 LLM 把这些完整代码生成出来，主困难仍由不可复现的修复模型完成；若为每例人工写一个竞争实现，实验就使用了人为提供的修复先验。将它们装进 H 不会降低这一先验。

### 还有五个容易被掩盖的问题

1. **H 可以一致地错。** 对称只能消除“原程序必对”的假定，不能保证 H 含有正确的语义。全体假设都缺少某个交互时，零分歧并不意味着覆盖充分。
2. **已有 oracle 可能排除正确程序。** 例如正常断言误移到新上下文。若 H 必须让全部 validation assertions 通过，错误旧断言会成为硬约束。应区分观察数据一致与期望正确，不能偷换。
3. **最大分歧可以选到无关细节。** 临时错误消息、返回对象 identity、无意义 iteration order 很容易产生分歧，却不检验 issue 义务。observer 需要外部契约范围约束。
4. **编译通过不代表假设有意义。** N03 改成始终 move 两次、N04 验证所有无关表都能产生大量差异，但会让测试资源耗在未经支持的语义上。
5. **解释文字不能自然编译成小 AST 孔。** N04 “bulk has no table” 是规范范围决策；它没有决定如何恢复 SQL 写集合。必须展示语义定位到 AST 的算法及其失败率。

因此我的建议是：保留 version-space/disagreement 作为一种实验性排序信号，暂不选它为论文的唯一核心。除非能先给出一个无需目标答案的、有限且统一的假设构造演算，并证明构造出的假设具有较高任务相关性。

## 2. 更可操作的替代：带绑定的测试上下文语法

这个替代不声称已经有足够新颖性；它的优点是能先清楚说明程序怎样生成组合。借用 anti-unification 与 contextual composition，**构造对象是已有 validation 程序的参数化上下文，而不是几份假想的正确实现。**

普通 anti-unification 对两个语法项构造保留公共部分的泛化项与两组替换；它已有精确算法和 soundness/termination 研究，不能算我们的发明。[NASA：Verification of an Anti-Unification Algorithm in PVS](https://ntrs.nasa.gov/citations/20240015670)

对本问题的必要改造是：不把整个“不同输入/不同输出”压成一个大孔，而是沿 test 的 def-use 图，在**输入数据、对象构造、调用出口、观察**的实际程序边界因子化，并保留变量共享。算法输入可以是测试 AST、有限 helper 展开、候选调用图和类型/动态类型信息；输出是可执行代码 grammar，所有规则都有原始代码位置。

### 可计算对象

一个 grammar production 是从测试抽取的 lambda/statement context：

```text
byte-data             -> 已存在的 byte literal / 拼接表达式
stream-from-bytes(x)   -> 原 generator 或 IteratorByteStream 的参数化代码
response-from-stream(s, h) -> Response(..., stream=s, headers=h)
consume(r)            -> list(r.iter_multipart())
closed-observer(r)    -> r.is_closed
```

这里的名字只是帮助阅读；实际 nonterminal 用参数/结果类型与代码位置标识，不能人工登记“异常关闭组合”规则。程序生成 `stream-from-bytes(malformed)` 的原因是一个现有 context 的自由输入是 bytes，而另一个数据项的结果是 bytes。资源 sharing 保存成绑定边，而不是复用同名字符串。

### 三个明确运算

**运算 1：沿值来源切开并泛化。**

对共同候选 API 的验证，反向展开 test 中的纯 helper/构造辅助代码；在不同来源流入同型参数的位置做 anti-unification。每次将一个可替换表达式抽成 lambda 参数，并用 def-use 闭包带上必需定义。generator 的 yield 字节、分块循环的 body 变量、SQL AST 的 scalar 值都可以形成孔；不能把不可解析字符串声称为结构化 SQL。

**运算 2：上下文代入与绑定合并。**

结果类型可供参数类型使用且环境闭合时，将一个 context 代入另一个孔；同时枚举有限的输入 root 绑定分区，例如两个 source path 相异或相同。合并绑定时要对共同 scope 内全部 use 一致重命名，并按 helper 的 effect 保留顺序。深度和新增孔数限制搜索规模。这个操作能生成现有测试中从未出现过的“坏字节在 generator 内”及“有限配额 + 相同来源”。

**运算 3：按出口接观察，再作依赖剪枝。**

将 source observation 作为 continuation 接到正常返回或已捕获异常之后，沿同一对象的 use 链绑定。definite-assignment 排除异常出口尚未产生的返回值，例如 `len(parts)`；已有 response 的 `is_closed` 仍可读。对照生产代码判断新输入是否进入 observer 的动态/静态影响范围；SQL COUNT 与 name UPDATE 不相交时，标记该候选不能检验相关 invariant 义务。

注意：continuation 可执行不意味着其旧 expected 适用。期望仍在最后用 issue 的独立语义判定；不能通过“原断言存在”证明跨出口保持。这一算法有生成算子，但没有自动解决 oracle。

### N01–N04 怎样使用同一组运算

**N01。** bytes literal 与 generator-yield/context 都来自 validation；运算 1 抽出输入字节，运算 2 将坏完整 NDJSON 行代入 generator 并保留 Content-Type，运算 3 把异常后的同 response closed 观察接上。CFG/trace 检查必须看到异常先于底层 EOF，否则 application/json 全缓冲组合会被误认为有效。

**N02。** 分块 generator 从 `body` 读取 bytes，坏 framing 本来就是 bytes。因此替换 body 的来源即可，不要求生成任何修复程序。仍需在消费调用异常出口接 closed，并用控制流区分 header precheck 与已经消费中的 decoder 错误。

**N03。** 在 CLI helper 的参数构造树里，有限 quota 来自一个测试，多个来源 path 来自另一个；通过同作用域 root 绑定合并，令两个来源传相同 path。保留源测试的至少两个 distinct 文件和有限 quota。实际值不能仅凭同为 str 混换：Path 转换、option 分组与解析器 use 链必须参与识别，否则 basename、movie destination、state path 都会被错误统一。

**N04。** 这是一项诚实的压力测试：s228 本身已经有相同 DB/table、COUNT invariant、name UPDATE，简单 context composition 没有任何新价值。需要 SQL AST 将 invariant 读字段和 UPDATE 写字段暴露为参数化构件，再生成影响同一 predicate 的数据。已有测试提供 `COUNT(*) = 2 AND SUM(id) = 3`、id=1/2/3/4 等项时，可以探索两行起始状态和 `UPDATE ... SET id=4 WHERE id=1` 这样的 predicate-flipping 更新；必须另行核实数据/SQL 是否能从实际 grammar 推导，不能直接把这个人工示意算作自动产出。如果 SQL 前端或这些构件缺失，应报告 unsupported；不由 LLM 临时写一份完整正确程序补齐。

### 为何比先造 H 更容易落地

- 不需要先实现 dedup、finally 或 SQL 写集合验证的竞争修复；只需要构造能运行的测试。
- 每次扩展具体产生一段代码，类型、自由变量和 definite-assignment 给出机械拒绝条件。
- 绑定合并生成资源别名；不是在文本上复制两个独立测试，正好针对 N03。
- 抽取失败与生成失败能分开统计；没有“语义假设已准备好”这种难以审计的前提。

不过，它可能最终只是高质量的 test amplification，不够独立新颖。旧系统已实现片段端口和部分值交换；如果本方法只把那些构件写成 grammar，也只是改名。真正需要证明的改进是：**同一泛化与代入规则能从 validation 自动学习之前没有的 context 构造，而非为每种 relation 手写一个 adapter。**

## 3. 明确的不可覆盖反例与研究门槛

| 反例 | grammar 路线为何失败 | version-space 路线是否自然解决 |
|---|---|---|
| 所有源测试只用内存对象，仓库也无可解析的 stream 构造 | 没有产生 streaming context 的 production | 不自然；仍要猜 alternative program 和可执行 stream input |
| Oracle 与正确契约相反，如 agent 明确主张 bulk 不验证 | 生成判别输入后仍可能选错 expected | 不自然；H 对称也不能自行决定哪个语义正确 |
| 需要新的 observer 方法链，源观察均太弱 | 只复用 source observer 会漏；需 STARS 式调用链扩展 | 差异只存在未纳入的 observer 时也漏 |
| 复杂 heap sharing、闭包别名、深层递归嵌套 | 有界 root merge/浅构造不足以保证构造出结构 | 竞争实现同样可能都未表达该结构差异 |
| 区间重叠必须由多行 diff 输入间接产生 | 纯 AST substitution 不知道文本怎样产生区间；需进一步值语义合成 | 写“overlap 假设”不能替代从文本到区间的前端 |
| SQL 是动态拼接、经过 trigger、或运行在外部 CLI | 精确 read/write summary 缺失；不可把静态无法证明当独立 | `table=None` 孔也不足以实现合理竞争语义 |

建议下一轮先做一个很小但决定性的构造实验：不给目标标签，仅从原始 validation 建 grammar，打印 N01–N04 的完整 derivation tree；检查每个节点是否有源码来源、是否用了例外规则、最终代码是否正确绑定、oracle 是否独立可证。比较旧片段交换、朴素 anti-unification、带 def-use/exit/alias 的改造。只有同一操作实际生成跨结构场景并改善有效候选率，才值得把这个改造提升为核心学术抽象。

**我的最终立场：目前 version space 不应直接获选；上述 grammar 也不应被宣布为成熟新方法。** 前者缺少可复核的假设前端，后者有明确生成操作但创新与复杂关系覆盖仍待证明。最不应做的是为了统一 17 例，给任一路线增加一个能够“恢复任意语义”的 LLM 黑盒，再把它隐藏在一个新术语里。
