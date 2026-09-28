# 无竞争实现的搜索反馈：把观察搬到状态变化发生的地方

2026-09-28，独立方法备选。只设计，不调 provider、不运行新实验、不改主方法。原始 N01–N04 证据见 [python_sql.md](../trajectory_logic_20260928/python_sql.md)。

**建议优先验证“观察表达式提升为只读探针，再搜索它在不同对象绑定和阶段下的新关系状态”。** 这里不造 rival，不要求完整正确规格，也不把 observation 的当前值当作正确答案。搜索得到新状态后，是否构成 bug 仍需已有可信断言或局部 issue 语义裁决。

它比纯 execution coverage 多问一件具体的事：同样走过这些代码时，测试是否曾在这个资源的这个阶段，见过这些观察量之间的这种关系？最值得实验的机制不是给关系取名，而是**测试中的观察能够在候选未执行对应检查的位置被独立求值，并将未满足关系反向映射到下一次输入修改。**

## 1. 已有条件和研究假设分开

已有的输入条件：candidate、原始 test/script、issue 文字、能够重放的 execution、test/candidate 的 AST；不假设有正确参考程序、自动可得的完整 effect summary 或正确自然语言规格。

能直接计算的材料：test 中可解析的观察表达式及其根对象、构造/调用参数、正常和异常出口、运行时字段值、已执行的参数来源、受支持对象的 identity、受支持容器的元素及长度。

仍需检验的前提：能否自动为观察表达式找到足够的可读阶段；跨 CLI/DB/guest language 能否保留 resource identity；小的关系域是否保留目标交互；足够的 typed input constructors 是否存在。**这些不是算法已经获得的能力。**

必要语义辅助限定在两处：无法解析的构造器/DSL 参数结构；新场景的 oracle 范围。LLM 不负责填写关系图，不提供竞争实现，也不把 bug 的正确修复作为搜索前提。

## 2. 核心对象：可执行观察探针及其阶段化状态

从一个断言中分开表达式与期望，例如：

```python
assert response.is_closed        # 探针是 response.is_closed；True 不是普适规格
assert len(moved_files) == 2      # 探针是 len(moved_files)；2 暂不跨上下文迁移
assert db.validate(...)["valid"]  # 需要确认读操作，不能默认 arbitrary getter 无副作用
```

探针仍是实际代码 AST。它的 root 来自 def-use 绑定，例如具体 Response allocation 或具体 DB file/table；不是从变量名字推断同一对象。对 stateful getter，只有能证明/限制为只读、或能在隔离快照上求值时才提升；否则记 unsupported。

**提升（lift）的操作**：把同一表达式按 root 的可用绑定，放到以下有限 cut 上求值：

- test/候选调用前、正常返回后、异常传播后；
- 对该 root 进行已识别写入的调用返回点；
- 原断言所在点。

观察越过异常出口时做 definite-assignment：response 通常仍有定义，未成功赋值的 `parts` 不可读取。内部 cut 的值只用于搜索；最终断言仍应落在合法的 test/API 状态上。

**为什么不只选 current assertion slice？** 缺 validation/cleanup 边时，观察量本来就不会被 candidate 读取，或没有变化传播到最后的断言。提升的依据是 test 已经拥有的表达式与 root 的可读性，不是该边已经出现在当前执行依赖中。

## 3. 关系来源：固定小的类型域，不预填 pilot 关系

关系项只能来自三类机械来源：

1. test 的比较表达式、注册的可执行 predicate、已有观察的操作数；
2. 同一 resource/调用边界的参数、返回值、字段以及长度；
3. 固定类型模板：布尔值、空/存在、数值 `< = >`、同一运行内的 identity 相等/不同、容器中 identity 是否重复、同一探针的前后相等/不同。

先固定访问深度、容器样本界和每个 profile 的原子数，再自动实例化。SQL 数值不能因外层 Python str 有类型就可比较：需要 SQL AST 或已有可执行 SQL predicate。路径的 value equality 不等于文件 identity；无法用规范化路径/文件标识建立对应时，关系必须 unknown。

作用域筛选采用两层：已知同一 resource 的关系优先；跨调用共享配置、持久化文件或无法解析 ownership 的关系进入有预算的 unknown 队列。**“没看见依赖”只降低优先级，不能当作 disjoint 的证明。**

## 4. 一个确切可算的反馈，而非“关系覆盖充分”口号

设 `o` 为探针；`b` 为 cut 的源位置；`e` 为 normal/throw；`κ` 为相对 root 的绑定分区；`α` 为固定关系域的抽象。一次执行产生 token：

```text
(o_id, b_id, e, κ, α(values_before), α(values_at_b))
```

`α` 保留当前 profile 中的有限 order/presence/alias 关系。它不保存裸地址或任意长字符串，也不把 “case=N03” 放进特征。normal/throw 可以再关联已存在的 consumed/pending 等公开状态；不人工为某 case 填“正确消费阶段”。

两个最基本反馈：

```text
novel(t) = |tokens(t) − tokens(corpus)|
distance(t,g) = 未满足原子数 + 支持的数值/长度边界距离
```

保留带新 token 的 seed，以及对一个已登记目标 g 缩短距离的 seed；同一 token 留最短且可重放的代表，但需为不同 constructor provenance 保留有限副本，避免把未来扩展能力不同的 seed 合并。

`g` 来自“既有可评估 profile 的尚未观察组合”，不是 target 标签。对每个 scope 的小 profile，枚举未观察的类型合法 valuation；source comparisons 的邻接边界和现有 donor 状态用于排序。很多 valuation 不可达：未找到不等于证明不可达。

**可报告的 metric**：每单位执行时间新增 token 数、达到的 profile valuation 数、可评估探针比例、未知 root/phase 比例；冻结目录后可报告 `observed valuations / syntactically permitted valuations`，但只能称目录覆盖，不能称语义完备率。发现真实 bug、误报和 oracle 未定另计。

**不要把“必须改变最终 assertion value”设成奖励条件。** 如果缺失的边使结果始终不变，要求该值先变化才能保留 seed 会系统性删除目标。中间探针状态、绑定关系和出口组合本身就是反馈。

## 5. 下一次 edit 怎样从反馈得到

给未覆盖目标 g，选距离最小的 seed。只针对未满足的原子做一步修改：

| 未满足原子 | 输入 provenance 给出的下一步 |
|---|---|
| 数值/长度次序 | 在流入对应参数的 source constant、producer 返回值、容器长度上做邻界改动；保留 `low+count` 等导出表达式，而非给结果填一个数字 |
| alias / duplicate | 合并或分离两个可兼容的 constructor root 绑定，全部 use 同步更新；容器复制不是 pointer alias 的代替 |
| absent/present | optional 参数省略/恢复，或从相同类型 donor 代入已有非空值 |
| 正常/异常且资源前态不同 | 将已有触发该异常的 donor 数据绑定到接收该类型的 constructor context，保留 receiver 身份；重放确认异常真的发生在目标 cut |
| 探针真值不改变 | 用探针自身的读集合选择可修改字段/输入；若当前 producer 的所有受支持改动均不可能影响它，改选已有 producer/注册 predicate，或有界扩展 typed constructor grammar |

最后一行的重要区别是：这里读的是**独立 probe 的表达式语义**，不要求 candidate 当前存在写→检查的路径。例如 SQL predicate 读 id，下一步就优先修改 UPDATE 的 id 或其写值；candidate 跳过 validation 不影响这一选择。

不支持精确转换时不调用万能 `solve_relation`。保留 unknown，用一阶有限差分试改源输入，观察哪些中间原子改变；它只学习输入到 probe 的经验影响，不把未改变当作永久无关性。没有任何可构造 producer 时明确生成失败。

搜索循环可以小到如下程度：

```text
replay seeds; build lifted probes, provenance, and finite profiles
while budget:
    choose an uncovered profile valuation and its nearest retained seed
    choose one unsatisfied atom; mutate one of its input-provenance roots
    run the unchanged candidate with isolated fixtures and read-only probes
    retain novel tokens / improved distances / a bounded unknown sample
    when a new context reaches a legal observation point:
        materialize that observation; assess expected value independently
```

## 6. N01–N04 的手工推演：算法该得到什么，不计为实测

### N01/N02：同样的 throw，需要在不同资源前态下再看一次

原验证可给出这些记录：

```text
memory bad:  closed_before=True,  exit=Throw,  closed_after=True
stream good: closed_before=False, exit=Normal, closed_after=True
```

关系目录含 `closed_before=False ∧ exit=Throw` 的空格。其两个条件来自现有执行，无需猜正确 cleanup 实现。前者的 provenance 指向流构造，后者指向已有 malformed 数据；将坏数据接入流 constructor 是下一步 mutation。

N01 还必须区分 full-buffered JSON 与提前异常的 NDJSON：同样 malformed bytes 若经过完整耗尽，probe 会显示错误前已经关闭，未达到 desired prestate。已有 NDJSON producer 是下一个同类型候选；不能说任意 malformed × stream 都已检验。

N02 的非 multipart precheck 已产生 `closed=False, consumed=False, Throw`；目标消费中错误给 `closed=False, consumed=True, Throw`。`is_stream_consumed` 与 `is_closed` 已在源测试中存在，目录无需人为命名“消费中失败”。最终 `closed=True` 是否仍应满足，必须另由 issue 裁决。

### N03：已有重复与有限配额的关系空格

已有测试见过相同目录两来源但 quota absent，以及不同目录两来源但 finite quota。source binding 的相等关系与 optional numeric quota 的 presence 产生一个未覆盖 profile。下一步是合并两个路径 root，保留 donor 的有限 k 与多个不同文件，或者将有限 k 代入重复来源 seed。

候选列表 slice 前后的 collection identity profile 还可保留重复集中在前缀的 seed。最终移动 count 是原测试已有观察，即使每个分支都早已覆盖，`duplicate=True, finite_k=True, moved<k` 也是新状态。因为需求原文“caps”本身只是上界，不能仅凭这个 tuple 自动判 bug；具体可处理文件数、无额外失败和应处理数量仍要独立确认。

本例**基础组合目标本身接近 pairwise**，不能包装成新理论；研究价值若有，来自统一 root 绑定、区分 nominal path 与实际 identity，以及没有新分支时保留有用的状态 seed。

### N04：在缺检查的地方也能看见 predicate 被写坏

已有的 `COUNT(*)=1` + name UPDATE 让 independent predicate probe 真→真。这不是有效“破坏 invariant”的刺激；同表同 API 的共现不改变这一事实。

在 INSERT 验证里，注册的谓词与失败检查已经提供 predicate 构件；注册行为的资源是 DB file/table。即使 bulk 不调用 validation，也可在可读 write-return cut 独立求该 predicate，或在最终 DB 上只读求值。缺失的 validation 边不会把这个 probe 从目录剔除。

下一步修改不需要生成一份“正确 bulk”代码：SQL 前端恢复 predicate 读集合和 UPDATE 写集合；当前 COUNT 对普通字段 UPDATE 不敏感，则尝试已有 SUM(id)/field predicate 的注册构件，或其他已有写操作。源测试已有 `COUNT(*)=2 AND SUM(id)=3`、两行 id=1/2 与标量 3/4，可用于探索 SET id 的更新值；每次改动从 SQL AST/输入字段 binding 导出，不硬填 age>=18 这个目标例子。

当 probe 真→假且 safe-mode 命令仍成功，这个候选被保留，即使 exit code 没有变化且代码覆盖没增加。已有 issue 对“验证失败拒绝/回滚”的义务才使它成为正式 failure assertion。若 SQL parser、跨连接资源对应或可重放 predicate 缺失，本例仍失败；不能说这个 metric 自动补好了前端。

## 7. 另两个备选为什么不作为主核

**动态不变量反例搜索。** 能用既有轨迹建立 `memory ⇒ closed` 或 `duplicate ⇒ final count unchanged`，再寻找反例。但很容易学习 candidate 的错误行为并把它当准则；仅把违反 invariant 作为 novelty 也早有 INVSCOV。它可以做 profile 排序，不足以独立成为新颖核心。

**因果扰动/当前 assertion influence。** 固定其他输入、修改一个来源，观察 q 是否变化，能帮助选下一步 root；但缺 validation 时 q 对 invariant 的影响为零，缺 alias interaction 时局部一阶扰动也为零。不能以无影响删除关系。因果实验只能是补充，主要队列仍必须保留未被检查的中间状态及身份/阶段差异。

## 8. 与已有工作的区别和不能认领的部分

- **Checked coverage** 已经从 assertion 做动态后向 slice；我们不能把“考虑观察而非只考虑执行”说成新发现。当前 slice 对缺边的盲点是采用独立 lifted probe 的动机。[Schuler/Zeller 论文](https://citeseerx.ist.psu.edu/document?doi=e7439bf3253d51d86655cdc7ed0e3253de4d29b2&repid=rep1&type=pdf)
- **INVSCOV** 已经用程序变量的 likely invariants 划分状态，并奖励违反它们的输入。故“关系状态新颖性”和“反驳偶然不变量”都不是新贡献。[作者版论文](https://www.diag.uniroma1.it/delia/papers/usenixsec21.pdf)
- **StorFuzz，ICSE 2026** 在存储发生时记录位置与值，使未改变控制流的状态也能保留，尤其不要求这些数据已经被读取/比较。它直接反驳“必须影响当前 assertion 才有价值”的过滤；应成为状态反馈基线。[作者版论文](https://softsec.rub.de/files/pdf/icse2026-storfuzz.pdf)
- **Daikon** 已支持 conditional/context-sensitive invariants，不能把按调用上下文拆分关系本身当创新。[项目手册 §6.2](https://plse.cs.washington.edu/daikon/download/doc/daikon.html#Conditional-invariants)

本提案唯一值得争取的窄贡献是：**从 validation 的可执行观察自动构造资源绑定、跨阶段的探针；在 candidate 未实现检查边的位置仍计算关系状态，并用这些探针的输入 provenance 选择程序级组合修改。** 这句话仍需算法和实验来证明；没有证明前，它是可操作的研究假设，不是论文结论。

## 9. 必须承认的盲点与可否定实验

source 没有合适观察时需要扩展 observer；不可读内部 phase、复杂 alias、异步时间窗口、SQL/guest code 前端会限制 probe lifting；两原子 profile 可能遗漏三阶以上交互；所有已有观察都不敏感或错误时，状态反馈不能制造正确 oracle。关系目录的大小也可能淹没搜索预算。

冻结同一 input grammar，比较 edge coverage、store-value novelty、INVSCOV 式关系 novelty、仅终态观察、lifted phase probes；再消融 root 绑定与 probe-provenance mutation。记录真实关系首次到达时间、有效探针率、无新增 edge 但有目标进展的候选数、真正检出数与误报/未定数。**若只是加入更多 instrumentation 或更大语法就赢，应承认核心反馈没有贡献。**

不要把“数据/关系 coverage 比 code coverage 更细”当最终 insight。需要证明被遗漏的组合恰好在现有断言所定义的状态维度上被旧反馈折叠，而 lifted probe 能保留通向它的中间输入，并给出比无差别枚举更直接的下一步修改。

## 10. 对 root 提出“局部关系状态商空间”的进一步批评

把 order/alias/presence profile 明确写成抽象映射 `φ`，再搜索相等块合并/拆分、相邻次序交换等邻居，是比自然语言关系更可执行的方向。但必须保留下面两个区别。

**抽象等价不一定对 mutation 保持。** 对 landmarks `{0,3,7}`，x=4 和 x=5 都在同一次序块，观察 `x==7` 也都 False；合法 edit `x += 3` 之后，分别变成 7 和 8。这时一个可满足观察、另一个不可。按当前 diagram 只留最短代表，会丢掉后续可达性。称其为数学上的等价类没有问题，但不能未经证明称为保留搜索能力的 quotient transition system。

一种有限可操作补强是 probe 驱动的前像细化：对支持的 mutation `x'=x+3`，把 probe `x'==7` 拉回 `x==4`，给当前块增加 landmark 4。仅对有限深度、精确支持的表达式做；其他情况保留不同 constructor/provenance 的有限代表，当相同抽象节点的同种 edit 得到不同后继时拆块。不能声称这能建立任意真实程序的 bisimulation。

**内部 diagram 邻边不是现成输入 edit。** 若 x/y 是直接 test 参数，合并等值块能直接同步绑定；若 x 是 tokenizer 输出、diff 区间或 SQL 聚合，要求 x<y 并不告诉我们怎样改原始字符串。必须单列“邻边可实现率”：请求抽象邻边多少、生成可执行 edit 多少、真实重放到达该邻边多少。否则旧 `construct_witness` 黑盒只是换成了 `realize_neighbor`。

要让 probe 真正制约覆盖，需要它至少参与三项实际决定：

1. 选择 scope：从该 probe 的 resource root、注册 predicate 和可合法观察的 phase 出发，而非先计算全程序关系再附一个 observation ID。
2. 选择/细化 partition：源比较常量及受支持的 bounded probe preimage 成为 landmarks；一个与 probe 及其可用 continuation 已证明无关的临时计数器不能增加该 scope 的 novelty。
3. 选择 edit：使用 probe 自己的读依赖和 input provenance，而不要求 candidate 当前存在到 assertion 的传播边。未知依赖保留预算；只有有证据的 disjoint 才剔除。

这个补强不是完整新方法。有限前像/分区细化属于已有程序分析思想，是否适配 combination gap 并带来更少搜索，仍需证明。

### 不用全 17 例的最小验证

先用三个真实小目标加两个独立控制，给每个相同 input grammar 与执行预算：

- N01/N02 二选一：检验同资源 before/throw/after 的 probe 能否实际增加目标状态，而不是只重发现 throw 分支。
- N03：检验 alias/presence 邻边能否从现有 CLI 构造落地，测 `requested neighbor → realized neighbor`。
- N04：检验缺 validation 边时的 independent predicate probe 能否保留 true→false 的 UPDATE 状态；COUNT/name 真→真必须被识别为不敏感，不能靠 case 名手工换 predicate。
- 独立控制 A：上述 x=4/5、+3、observer==7，检查粗 diagram 合并是否漏掉路径，以及前像细化能否修复。
- 独立控制 B：增加一个与 observer 根已证明无关的可变计数器；相同预算下它不应制造 observer scope 的 novelty 或吞噬大部分搜索。

消融只换反馈/partition：edge、通用关系 novelty、终态 probe、lifted phase probe、加入前像/transition refinement；构造器和语义 oracle 保持一致。最关键结果不是总 token 更多，而是更低的目标状态首次到达成本、较高邻边实现率、较少无关状态，以及没有因为粗状态合并丢掉控制 A。这五项通过，才值得扩到完整 17 例。
