> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/manual_case_analysis.md) · [旧路径映射](../../../results/path_map.tsv)

**Pilot cases 手工特征分析与补充样本**

分析日期：2026-09-23。本轮仅阅读和方法设计：未执行测试、replay、修补实验或外部 LLM 请求。以下把源码事实、静态推断与待执行验证分开。未读取 hidden verifier 或 reference patch。

本分析者已经看过 handbook 的人工假设，因此这是回顾性机制分析，不能作为“盲化自动发现缺陷”的结果。下面的示意测试也不能放进未来自动生成器的输入来证明方法有效。最终目标是将它们抽象为跨项目的分析规则，并在未见过的 issue 上验证。

**1. 主要判断**

遗漏通常发生在两个行为需要满足同一个语义义务的位置：一个分支产生的表示进入另一个分支、两条数据流汇入一个输出、克隆必须同时保存内部共享和外部隔离、或者正确性依赖某个动作先于另一个动作。测试分别拥有相关行为，并不意味着同一输入、对象或执行中出现过这些关系。

还有一种不同的不足：关系确实出现，但测试使用的值或断言投影不能区分“关系实现正确”和“关系语义丢失”。P3 是有 alias 断言但 modifier 值不敏感；P7 是有递归与 pipe，但运行时转换不改变值。

7 个 trial 实际只有 4 个 issue / repository 家族；P1–P3 属于同一 Textual issue，P5–P6 属于同一 Tengo issue。它们适合提出机制假设，不足以估计遗漏比例、方法召回率或 issue resolution rate。原始 7 条 trajectory 来自不同模型，并非 DeepSeek-v4-flash 专属样本；补充 E1–E3 的 `agent.model_name` 均已核对为 `deepseek/deepseek-v4-flash`，逐条元数据见 [人工标注](../../../research/manual_annotations.json)。

| Case | 已有测试包含什么 | 需要联结的关系 | 易遗漏原因 | 主要程序分析需求 |
|---|---|---|---|---|
| P1 Textual | 特殊键序列；普通字母 press/repeat/release | 同一 phase 语义跨语法分支传播 | 新字段只进入某一解码路径 | 语法分支、构造器字段、跨路径义务对齐 |
| P2 Textual | modified shortcut 的 character=None；text-only 序列 | 非 shift modifier 与 associated text 共同决定 character | 两份测试的局部正确性掩盖同一输出的优先级冲突 | 谓词和字段级 def-use、assertion slice |
| P3 Textual | shifted alias；多 modifier 输入 | shifted alternate 与包含 shift 的集合共同决定 alias | 原测试 modifier=5，不触发 shift 规范化 | bitset 抽象、值敏感分析、规范形 oracle |
| P4 IPython | magic 入口；直接 API 的 path 与 bundle 行为 | 引号表示经 tokenizer 进入文件系统路径 | 适配层未保持表示语义 | 跨过程字符串流、边界契约、等价入口 |
| P5 Tengo | Go Call、returned closure、容器中的 callable | 外部调用建立 frame 后构造复合返回值 | 测试入口、返回形状、局部槽位分开覆盖 | host/guest 联合分析、frame 状态、shape |
| P6 Tengo | clone 隔离；单个闭包的捕获 | clone 内两个闭包共享同一个 cell，且与源隔离 | 只验证跨实例隔离，没有验证实例内共享 | capture/points-to、堆图复制、读写序列 |
| P7 Valibot | recursive+pipe；结构指针、值相等和类型断言 | schema 图重写保持运行时 pipeline 转换 | readonly 运行时为恒等，类型检查与执行混淆 | 属性覆盖、闭包捕获、oracle 区分能力 |

**2. P1：不是“特殊键”一个标签，而是语法路径与 phase 义务的交叉**

事实依据：

- [test_xterm_parser.py:43](../../../data/cases/P1/repository/tests/test_xterm_parser.py#L43) 的分块测试包含 `ESC[8~`；同文件 `test_unknown_sequence_followed_by_known_sequence` 的第 129 行也使用该类特殊键序列。
- [test_xterm_parser.py:432](../../../data/cases/P1/repository/tests/test_xterm_parser.py#L432) 的 `test_kitty_key_phase` 把 phase 参数化，但输入固定为普通字母的 `...u` 语法。
- [_xterm_parser.py:40](../../../data/cases/P1/repository/src/textual/_xterm_parser.py#L40) 中新正则识别 `event_type`，结尾固定为 `u`；`_re_extended_key` 接受 `~`/字母结尾，但没有 phase 的 `:event_type` 结构。
- [_xterm_parser.py:525](../../../data/cases/P1/repository/src/textual/_xterm_parser.py#L525) 的 extended 分支构造 `Key` 时没有传 `phase`。

可提取维度：`syntax_family={u,tilde,letter-final,legacy-ESC}`，`phase={default,press,repeat,release}`，`modifier_bits`，`input_chunking`，`observation={event count,key,phase,dispatch}`。特殊键也可通过某些 `u` 编码表示，所以“key=function”不足以定位缺口，必须保存编码/解码分支。

关联见证不是两份测试之间的直接调用，而是两个生产路径都实现“外部输入→Key 事件”，共享字段级后置条件。把一个入口的 metadata 义务迁移到另一合法语法分支，才能提出候选。

生成草图：从现有合法 special-key 序列提取语法树，在协议允许的位置加 phase；复用 key 身份断言，增加 phase 断言，并保留 press 控制组。不能直接字符串拼接，也不能把候选正则拒绝的输入自动标为无效——缺陷本身可能正是候选正则漏接了一种合法语法。语法合法性需要 issue、仓库文档或已有解析规范支持。

静态预期：某些带 phase 的非 `u` 序列无法走完整的相应解码路径。此处未运行，不声称具体失败输出。难度：中。

**3. P2：竞争的是同一个输出字段，不只是“共享一个函数”**

事实依据：

- [test_xterm_parser.py:440](../../../data/cases/P2/repository/tests/test_xterm_parser.py#L440)：`ESC[65;4u`，断言 `key == 'alt+shift+a'`、`character is None`。
- [test_xterm_parser.py:451](../../../data/cases/P2/repository/tests/test_xterm_parser.py#L451)：`ESC[0;;97u`，检查 associated text 作为 key/character。
- [_xterm_parser.py:493](../../../data/cases/P2/repository/src/textual/_xterm_parser.py#L493) 特判 `key_code == '0'`；[同文件:552](../../../data/cases/P2/repository/src/textual/_xterm_parser.py#L552) 的 shortcut 分支将 `text or None` 传给 `Key`。
- [issue.md](../../../data/cases/P2/issue.md) 要求非 shift modified printable shortcut 保留稳定名称且 `character=None`。

维度不能只写 `text present`：需要联合记录 `key_code_zero`、`printable`、`has_non_shift_modifier` 和 `text_nonempty`。text-only 的零 key code 与 modified printable 的非零 key code 不可直接把整个参数 tuple 合并。

关系为两组谓词到同一 `Key.character` 的数据/控制依赖。源测试 A 提供 shortcut oracle；B 提供 associated-text 的合法构造方式。生成时保留 A 的非零 key code 和 modifier，迁移 B 的 text 子结构，而不是迁移 B 的 `character=='a'` 断言。

可检查的组合草图：`ESC[65;4;97u`，在 issue 对应前提下仍应 `character is None`，同时保持 shortcut 名称。另保留 `key_code=0` 的正向控制，防止通过“无条件丢弃 text”错误修复。

这类关系一般化为：**条件覆盖不等于同一输出在多个影响因素共同激活时的契约覆盖**。难度：低到中；oracle 依据在 issue 和已有断言中都比较明确。

**4. P3：组合标签已经出现，缺的是会改变语义的值**

事实依据：

- [test_xterm_parser.py:457](../../../data/cases/P3/repository/tests/test_xterm_parser.py#L457)：输入 `ESC[61:43;5u`，已经断言 `ctrl+plus in aliases`。
- [test_xterm_parser.py:434](../../../data/cases/P3/repository/tests/test_xterm_parser.py#L434)：另一个测试使用包含 alt+shift 的 modifier，但没有 alternate alias。
- [events.py:323](../../../data/cases/P3/repository/src/textual/events.py#L323)：alias 直接拼接所有 modifiers 和 shifted_key。

协议 modifier 编码是 `value-1` 的位集合。5 对应 ctrl，6 对应 ctrl+shift。因此在 5 上，错误的“直接拼接全部 modifier”与正确的“shift 已体现在 shifted alternate 中”产生相同 alias；在 6 上会分开。

维度：`alternate_present`、`alternate_differs_from_base`、`shift∈modifiers`、`non_shift_modifiers`、`alias_normalization`。如果把整型参数抽象成“有 modifier”，会错误地认为组合已覆盖。

生成草图：保留 `61:43` 和已有 alias 断言，选择 modifier 位组合使 shift 的去重义务活跃；同时检查 base_key、shifted_key、modifier metadata，避免为满足 alias 断言丢失原始 modifier。精确 oracle 必须来自 issue 的 shifted-form shortcut 语义，不能从候选拼接实现反推。

关键分析：对 alias 的 backward slice 回溯到 modifiers 的 bit 操作与 shifted-key 选择；求一对值使“保留 shift”和“消去已被 alternate 吸收的 shift”在观察值上不等。难度：中。这个例子反对把每个 test 简化成无值的特征集合。

**5. P4：依赖跨过解析适配层，数据的表示会变化**

事实依据：

- [test_sessionbundle.py:73](../../../data/cases/P4/repository/tests/test_sessionbundle.py#L73)：magic roundtrip 使用未加引号的简单 path，断言状态路径和 bundle 文件。
- [test_sessionbundle.py:268](../../../data/cases/P4/repository/tests/test_sessionbundle.py#L268)：直接 API 的 start/stop/status。
- [session_bundle.py:88](../../../data/cases/P4/repository/IPython/core/magics/session_bundle.py#L88)：`parse_argstring → args.path → start_session_bundle`。
- [magic_arguments.py:164](../../../data/cases/P4/repository/IPython/core/magic_arguments.py#L164)：调用 `arg_split`。
- [_process_common.py:188](../../../data/cases/P4/repository/IPython/utils/_process_common.py#L188)：默认 `posix=False`，tokenizer 具有保留引号的语义；适配层未显式消除这种表示差异。

要谨慎：在所审阅的该 case 新增 session-bundle 测试中，未找到一个能够直接证明“quoted bundle path 已被单独测试”的供体。不能为了符合 handbook 的 `A+B` 叙述而虚构第二份测试。本例部分候选应由边界契约与 tokenizer 的语义产生，而非只做 test-pair 拼接。

维度：`entry={magic,direct API}`，`path_object={str,Path}`，`representation={plain,single-quoted,double-quoted}`，`contains_whitespace`，`operation={start,status,stop,replay}`。quote 是命令表示，不能当成物理文件名的一部分。

生成草图：在两个隔离 shell / 相同初始状态中，一边 `start_session_bundle(path)`，另一边通过合法引用形式调用 magic；比较实际创建文件、status 中归一化路径和 bundle 内容。对于有不确定 quoting 规则的输入，应先验证命令层前置条件，不能把本来无效的未转义空格输入当缺陷。

抽象模式：**调用图上的 wrapper→core API 边必须携带表示转换契约**。难度：中。检查两个位置之间有无调用路径有帮助，但不识别引号/路径的表示层次就无法生成正确测试。

**6. P5：返回值形状与调用入口相互作用，真正触发条件可能是 frame 局部槽位**

事实依据：

- [callable_test.go:24](../../../data/cases/P5/repository/callable_test.go#L24)：同一大测试包含外部 `.Call()`、返回单个 closure、以及在脚本中事先创建的 nested holder。它们在一个函数中出现，不表示 compound holder 经由 Go root call 返回。
- [vm.go:109](../../../data/cases/P5/repository/vm.go#L109)：`runFunction` 为外部调用建立 frame，`v.sp=len(args)`。
- [vm.go:733](../../../data/cases/P5/repository/vm.go#L733)：VM 内部 `OpCall` 路径为局部槽位计算 `v.sp=v.sp-numArgs+callee.NumLocals`。

这提示一种可检查的 frame 初始化不对称：同一个被调用函数，若局部槽位多于参数槽位，入口对局部与求值栈区域的处理可能不同。没有执行证据，不能将这直接宣布为已确认根因。

维度应包括 `entry={Go Call,in-VM}`、`NumLocals−NumParameters`、`return_shape={scalar,closure,array,map,nested}`、`callable_leaf_count`、`closure_use_after_return`。只做 `Call×Array` 仍可能选到不触发槽位冲突的程序。

生成草图：用同一 guest-language 工厂在两个新建、等价的 compiled instance 中分别从脚本内和 Go 端调用。工厂包含非参数局部变量，并返回含 callable 的数组/映射；取出叶子 callable 后真正执行，比较已知小计算结果。不得只断言 `CanCall()`，也不能共享一个有副作用的源实例后按先后执行两条路径。

分析需要解析 Go 字符串中的 Tengo 程序，建立 guest binding / closure-capture / return-shape 摘要，再连接 Go `Object.Call` 与 VM frame 初始化；Tree-sitter-Go 看不到字符串内部的语义。可将类型/编译信息作为辅助，而不是让 LLM 猜栈布局。难度：高。

**7. P6：clone 必须同时满足“内部共享保持”和“外部共享切断”**

事实依据：

- [gocall_test.go:44](../../../data/cases/P6/repository/gocall_test.go#L44) 测试单个 closure 的捕获；[同文件:197](../../../data/cases/P6/repository/gocall_test.go#L197) 的 clone 测试主要观察 global counter 的隔离。
- [script.go:285](../../../data/cases/P6/repository/script.go#L285) 为每个 global 调用 `transfer`。
- [call.go:203](../../../data/cases/P6/repository/call.go#L203) 每次 transfer 建立新的 seen map；[同文件:215](../../../data/cases/P6/repository/call.go#L215) 为每个 closure free slot 新建 `ObjectPtr`，没有在这个分支保存源 cell→目标 cell 的共享映射。
- [vm_test.go:1670](../../../data/cases/P6/repository/vm_test.go#L1670) 有大量闭包场景；其中“有多个 closure”也不能自动推导为“共享同一个可变捕获 cell”。

手工分析未证明最终测试集中存在一份现成的“两闭包共享同一个局部 cell”供体。因此更准确的描述是：clone 测试和 closure 测试提供基础，但还需通过 alias 图义务构造新的对象关系。这是 pair-of-tests 方法的召回边界。

设源实例中两个闭包 f、g 捕获 cell c。clone 后应满足：

```text
capture(f′) = capture(g′) = c′     // 同一副本内部保留共享
c′ != c                           // 与源实例隔离
write(f′, 7); read(g′) == 7        // 同一 cell 的读写关系
read(g) == original_value         // 源实例不受影响
```

这不是把 `clone=true` 和 `closure=true` 两个布尔值凑在一起。必须保留别名等价类、对象所属实例与先写后读顺序。若 f/g 各读到一个数值相等的副本，只读测试会通过；写 f′ 再读 g′ 才有区分力。

生成草图：共享局部变量的 setter/getter 作为一个复合值导出，先执行原始关系控制组，再 clone，在 clone 内 update→read，最后观察源仍不变。读写值应不同于初始值。不能用两个彼此独立的计数器替代共享 cell，也不能只断言两个 clone 对象不相等。

程序分析核心：作用域绑定、capture graph、field-sensitive points-to、复制映射的 alias-class 保持；运行时只需对候选 witness 的 cell/object identity 和 read/write 事件做窄范围观测。难度：高。

**8. P7：可见 schema 图、执行闭包和观察值是三个不同层面**

事实依据：

- [recursive.test.ts:71](../../../data/cases/P7/repository/library/src/methods/recursive/recursive.test.ts#L71)：`recursive(pipe(object(...Recur...), readonly()))`，断言递归属性链接正确且输出深等于输入。
- [readonly.ts:36](../../../data/cases/P7/repository/library/src/actions/readonly/readonly.ts#L36)：运行时 `~run` 直接返回 dataset；并非只是在选定值上“接近恒等”，而是该实现的运行时值操作本来就不改变数据。
- [recursive.test-d.ts:65](../../../data/cases/P7/repository/library/src/methods/recursive/recursive.test-d.ts#L65)：有 `transform(input => input.length)`，但位于字段内部，且断言是 TypeScript 类型关系，不能替代 root pipeline 的运行时验证。
- [_resolveRecur.ts:54](../../../data/cases/P7/repository/library/src/methods/recursive/_resolveRecur.ts#L54)：把 resolvedItems[0] 的属性复制进 updated；[同文件:117](../../../data/cases/P7/repository/library/src/methods/recursive/_resolveRecur.ts#L117) spread 合并对象。这些属性包含执行方法 `~run`。
- [pipe.ts:2693](../../../data/cases/P7/repository/library/src/methods/pipe/pipe.ts#L2693)：`~run` 闭包遍历捕获的 `pipe` 数组，而不只依赖对象上可见的 `.pipe` 属性。

静态风险：schema 结构改写可能替换 pipeline 的执行方法，或者令对象属性与执行闭包捕获的对象不再一致。`.pipe` 看起来正确不等于实际执行完整 pipeline。这里不根据 handbook 宣称某个任意 transform 一定失败。

维度：`recursion_container`、`depth`、`transform_placement={field,outer-pipe,recursive-level}`、`sync/async`、`transform_effect={runtime-identity,value-changing}`、`oracle={type,structure,runtime-value}`。

生成草图：在包含 Recur 的外层 pipe 添加形状保持的非恒等转换，例如把每个节点的 value 加上固定标记；对深度至少 2、初始值互异的树检查根和子节点的输出。用独立的纯映射构造期望，并单独验证 transform 在非递归 schema 上的控制组。字段内的 length 转换只能作为转换语义证据，不能不加区分地移到外层并宣称 oracle 可直接复用。

难度：中到高。除了数据流，要分析对象 spread 的属性覆盖与函数值/闭包捕获。单纯 pairwise 参数覆盖不能表达这类观察不足。

**9. 三个 DeepSeek-v4-flash 补充样本**

公开入口：[DeepSWE trials](https://deepswe.datacurve.ai/data/v1.1/trials)。索引下载到 `sources/deepswe_trials.json`，共有 31,617 行；其中本次筛选 `source=deep-swe`、`model=deepseek-v4-flash`、`has_trajectory=true` 得到 452 行。该计数仅描述下载时的索引。

按任务类别先选择以下三个 task，再选该 task 名字字典序最前的 Flash trial；未按 reward、隐藏失败或通过率挑选。仅下载 trajectory 和 model.patch，下载链接及哈希在 [flash_provenance.json](../../../research/sources/flash_provenance.json)。这是扩展发现集，不能再充当未见过的验证集。

| 补充样本 | 新增维度 | 审阅中的主要观察 | 证据范围 |
|---|---|---|---|
| E1 LangChain `6MJsqSj` | 并发、key 复用、执行世代、late completion | 跨接口组合已有不少；clear→reuse→old completion 更值得审查 | patch + trajectory 临时脚本 |
| E2 HTTPX `2HymEqZ` | 流式前缀、首次产出、EOF、消费/关闭 | 最终序列相等会掩盖先读完再 yield | patch + step 41 等脚本 |
| E3 sqlite-utils `3yukcR8` | 嵌套 transaction、schema 与数据原子性、CLI/API | 多个重要组合在临时脚本中已出现；仅看 patch 会误报缺测试 | patch + step 202 |

**E1：clear 与同 key 重入是执行世代问题。**

[trial](https://deepswe.datacurve.ai/data/v1.1/trials/langchain-request-coalescing__6MJsqSj)；本地 [patch](../../../research/sources/flash/langchain-request-coalescing__6MJsqSj/model.patch)、[测试增量](../../../research/sources/flash/langchain-request-coalescing__6MJsqSj/test_coalesce.py.added.txt)、[trajectory 测试命令](../../../research/sources/flash/langchain-request-coalescing__6MJsqSj/manual_test_commands.json)。

最终 test 文件分别检查 clear/cancel、register fresh、sync/async invoke、stream joiner。trajectory step 67 已有 stream↔invoke 与 sync↔async 组合，step 88 有中途 join 与 stream clear；step 111–112 还有跨 sync/async 临时测试。不能把“跨接口调用”整体报告为缺失。

候选实现 `complete(key)` 从 `_executions[key]` 获取当前 entry，clear 删除 mapping，而旧 leader 在完成时仍使用 key 回调 complete。由此得到待验证序列：旧请求 L1(k) 启动→clear→新请求 L2(k) 注册→L1(k) 迟到完成→新 joiner 观察结果。当前 key 相等不代表 execution identity 相等。

生成需要 barrier/event 控制顺序，不用 sleep 猜时间；断言新请求不能被旧结果满足。独立输入不变而返回值可通过执行世代计数区分。此候选的完整 clear/leader 契约仍需审核，未执行、未确认缺陷。方法新增需求：抽象位置必须包含 key 的等价类和 execution epoch，依赖图必须带 happens-before 约束。

**E2：内容 oracle 观察不到增量性。**

[trial](https://deepswe.datacurve.ai/data/v1.1/trials/httpx-streaming-json-iteration__2HymEqZ)；本地 [patch](../../../research/sources/flash/httpx-streaming-json-iteration__2HymEqZ/model.patch)、[测试增量](../../../research/sources/flash/httpx-streaming-json-iteration__2HymEqZ/test_responses.py.added.txt)。

issue 明确要求 incrementally yield。candidate 的同步入口先 `b''.join(self.iter_bytes())`，异步入口先收集所有 byte chunks，再开始 yield。仓库新增测试和 step 41 临时脚本主要做 `list(iter_json())` / async list，然后观察 consumed/closed。它们能验证最终内容和完整消费，却不能观察首次产出是否早于 EOF。

可靠的待执行 witness：受控 NDJSON stream 提供第一条完整记录（含换行），在给出下一条记录前等待 consumer 的确认；消费者应能先得到第一条记录。流后缀 gate、producer 计数和 first-yield 事件是 oracle 的一部分。可以设有限超时防止测试永不结束，但“超时”本身只是症状，需与 barrier 状态共同分类。

增量性→first yield before requesting blocked tail 是本文手工提出的测试义务，不是官网隐藏测试结论。重要性在于把观察从终态值扩展到事件偏序；它提供 7 个原始 case 没有充分覆盖的场景。

**E3：这是避免误报的反例，不应强行包装为新缺陷。**

[trial](https://deepswe.datacurve.ai/data/v1.1/trials/sqlite-utils-safe-import-checkpo__3yukcR8)；本地 [trajectory 测试命令](../../../research/sources/flash/sqlite-utils-safe-import-checkpo__3yukcR8/manual_test_commands.json)。最终 patch 不包含新增测试文件，但 step 202 的 heredoc 已有：safe insert 失败撤销新表、strict 异常、nested checkpoint rollback/commit、executescript 建表和 trigger 后回滚、CLI safe bulk UPDATE 的失败退出码。将“patch 中没 test”推成“agent 未测试”会错。

仍可提出更严格的观察义务：数据行与 sqlite schema 指纹的前后比较、外层 checkpoint 的存活性、失败后再成功的生命周期。但这些只是进一步审查方向；本次不声称它们缺失或发现了缺陷。已有测试在历史版本执行过，也不自动意味着对最终候选仍有效，必须保留 step→源版本→脚本内容的映射。

**10. 可复用的高风险特征与不应过度推广的结论**

| 高风险特征 | 为什么单独测试容易通过 | 检测抓手 | 限制/反例 |
|---|---|---|---|
| 新增语义横跨旧入口 | 默认值掩盖未传播字段 | 平行路径的字段初始化义务 | 不同入口可能合法地有不同语义 |
| 两因子影响同一返回字段 | 单因子下两实现等价 | def-use + guard + assertion slice | 共享字段不等于合法共同激活 |
| 编码参数压缩多个属性 | 某个位组合未触发规范化 | bitset/enum 分解与边界值 | 无规范时不能任意猜编码 |
| 适配器把字符串变领域对象 | 简单表示可透明穿过 | 字符串流、normalize/parse 契约 | 引号、转义规则依平台而变 |
| 同形值来自不同构造路径 | Go/VM、类型/运行时路径不同 | producer provenance + shape | 仅记录结果类型仍不足 |
| 对象共享与隔离同时要求 | 值相等的多个 cell 看似正确 | alias 类、复制映射、write-read | 需要精确实例范围 |
| 恒等或饱和值 | 执行有无目标操作结果相同 | 非恒等 witness、观察投影分析 | 不是所有恒等变换都无效，可能是类型契约 |
| epoch/生命周期复用 | fresh 状态测试不触发旧回调 | 时序、allocation/epoch identity | 并发测试必须控制调度 |
| 终态 oracle | 全量读完与增量执行终态相同 | first-yield、resource event oracle | 时间常数不是可靠语义模型 |
| agent 临时测试被丢弃 | 最终 test 文件不代表全部验证 | trajectory shell AST 与版本对齐 | assert 也可能是编辑器保护断言 |

这些是机制解释和候选风险信号，尚不是“具有该特征就会漏组合”的因果结论。更不能据 10 个被人工阅读的 trial 估计全体缺陷分布。关于如何检索 A、以及七例是否满足关系残差和供体重组前提，见最新 [适用性审查](anchor_applicability_audit.md)。候选设计及其限制见 [method_design.md](method_design.md)；2026 文献依据见 [literature_2026.md](literature_2026.md)。
