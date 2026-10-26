> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../../research/trajectory_logic_20260928/python_sql.md) · [旧路径映射](../../../../results/path_map.tsv)

# N01–N04：从测试生成过程重新审视 combination gap

本轮只读取原始 trajectory、issue 和候选代码；没有调用 provider，没有重跑实验。旧 expanded-trials 报告仅用于定位。本报告中的“explicit”表示原始 `reasoning_content`、命令或输出直接出现；“inference”表示根据这些可观察行为归纳，不能当作 agent 心理事实。这里的 reasoning_content 是公开轨迹已有字段，不是本轮模型推理。

一个影响方法定位的新发现：**N02 和 N04 的 agent 明确想到过目标交互，却认为它不需要满足更强的契约；N03 明确看见过重复候选，却依据无配额测试认为无害。** 不能把这三例统一叙述为“agent 没想到组合”。测试确实缺少有效判别组合，但生成缺口部分来自对规范范围的主动缩窄。

## 原始材料

相对路径从仓库根开始，SHA-256 是本轮读取文件的真实字节哈希。步骤号使用原始 `step_id`，不使用数组位置。

| Case | 原始 trajectory | SHA-256 |
|---|---|---|
| N01 | `data/relational_gap_v1/N01/trajectory.json` | `1fc31b6c219dc3a02d9318394a399135b8721c600bfc589fd1b6bde94ade5441` |
| N02 | `data/relational_gap_v1/N02/trajectory.json` | `728c9be50347f0a1aca11a9cb625483936a6251cb11b6a7d16684b5e192f394e` |
| N03 | `data/relational_gap_v1/N03/trajectory.json` | `f6bc5c602184a2e49ea7e341eda9017bab391b2dca3702104cc5f39ee72c5d0b` |
| N04 | `data/relational_gap_v1/N04/trajectory.json` | `dd6476088e5465efb92a1f568ca85264073fc33c82b28b67e1d0b6271a06609e` |

可复查的逐步 SHA 在文末。步骤 JSON 使用 `json.dumps(step, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 编码 UTF-8 后哈希；这只是检索证据，不是算法的自然语言 schema。

## N01：关闭保证原先依赖耗尽，增量改造改变了保证成立的条件

Issue 同时要求畸形 JSON 抛 DecodingError、streaming response 消费并关闭、内存 response 可重复迭代。

**Explicit 设计依据。** step 26 写道：

> This is satisfied as long as I iterate over `self.iter_bytes()` to exhaustion (which closes).

同一步继续说 `iter_bytes()` 对内存与流式 response 可以获得相应行为，“both behaviors come for free”。这是“先完全耗尽，再解析”的实现下关于关闭的具体理由，不是本文替 agent 推测的假设。

**Explicit 测试划分。** step 45 列出 async、stream consumption、repeatability、encodings、NDJSON edge cases 等项目。step 57 将下面两类测试加入同一文件并得到 `155 passed`：

- `test_iter_ndjson_invalid_line`：`content=b'{"a": 1}\nnot json\n'`，构造已经在内存中的 response，只检查 DecodingError。
- `test_iter_json_streaming_consumes_and_closes`：合法 application/json generator，检查产出、consumed、closed 以及再次迭代 StreamConsumed。

**Explicit 后续实现变化。** step 76 因 issue 的 “incrementally” 和可能的 streaming timing 检查，改为逐块 NDJSON/json-seq 解析。step 77 的 sync 实现由先 `b"".join(self.iter_bytes())` 变为：

```python
yield from _iter_json_lines(_iter_json_text(self.iter_bytes(), charset))
```

此时解析可能在底层 iterator 耗尽前抛错。step 78 重新跑旧测试仍 `155 passed`，新增正常流手工观察显示第一次 next 后 `is_closed=False`、完成后 True。step 82 加入正式 `test_iter_ndjson_streams_incrementally`：第一次 next 后不关闭、第二次有正确值、StopIteration 后关闭，得到 `156 passed`；step 95 仍为 `156 passed`。

**Inference，边界明确。** 可以从代码与测试证明：关闭性质原本借助“先耗尽”的执行次序成立，而后续增量改造改变了次序；新增测试检查正常中途未关闭与正常结束关闭，没有将畸形行搬入尚未耗尽的流并在异常后观察关闭。不能据此声称 agent “忘记了”某段推理，只能说原来的充分条件已改变，测试未见证新异常出口。

**不是任意 malformed × streaming 都有效。** 把 malformed 内容放入 application/json 流仍会先完全缓冲，解析报错时资源已关闭；把错误留到 NDJSON 最终 flush 时也可能先耗尽底层流。有效测试必须让畸形完整行在底层流完成关闭之前被解析，并在捕获异常后观察同一 response。这是执行位置和事件顺序，不是字符串关键词组合。

**可导出算法事实。** 给 `is_closed` 的来源定位到 `iter_raw` 正常尾部关闭，把程序改动前后的异常控制流对比：将解析移动到消费循环内会新增“throw 绕过 close”的路径。使用已有坏行作为 throw witness，保持 `response` identity，复用已有关闭观察；不能复用“已成功解析的值数”断言。这里存在可机械生成的路径目标，必要的语义问题仅为“已开始消费的解析失败是否属于关闭契约范围”。

## N02：已经想到异常不关闭，并把旧 API 行为类比成新 API 契约

**Explicit 测试选择。** step 54 计划 comprehensive test file，项目中分别有“streaming sync consumes & closes”和“malformed framing”。文件具体用法为：

- `test_multipart_response_malformed_framing` 在 `content=body` 的内存 response 上检查 DecodingError。
- `test_multipart_response_streaming_consumes_and_closes` 用合法分块 `IteratorByteStream(stream())`，检查 part、consumed、closed 和再次迭代失败。

step 57 verbose pytest 列出这两类的通过结果。step 70 在后续重构后再次验证合法 sync/async streaming，输出 closed=True。step 118 相关三个文件共 `87 passed`。

**决定性 explicit 证据。** step 65 为解决 mypy nominal stream 类型问题，决定从 `iter_raw()` 改成直接传 `self.stream`，在 Response 层手动管理消费和关闭。该步明确写道：

> If DecodingError is raised mid-iteration, `self.close()` after the generator won't run (exception propagates). That's acceptable but maybe we want to close anyway.

随即理由是：

> Actually `iter_raw()` uses a `with request_context(...)` and closes at the end; on exception it doesn't close either (generator abandoned). So same behavior.

step 67 实际落地 `yield from decoder.iter_parts(); self.close()`。step 99 回顾 issue 时，将关闭要求检查为“after full iteration”，并标记通过。

**另一条必要的 phase 证据。** step 113 特意验证 Content-Type 非 multipart 的 streaming response：输出 `DecodingError OK; consumed: False closed: False`，随后仍可读取原始 bytes。这不等于已覆盖 malformed multipart 消费中失败。前者在消费前拒绝，不应从“有 DecodingError、closed=False”简单判定目标 bug，也不能把本算法写成“任何错误都移植 close=True”。

**Inference。** 该 trial 的测试缺口有明确的规范范围判断参与：agent 知道异常后 close 不执行，却类比既有低层 iterator 行为接受它。仅依赖 trajectory 中的测试期望或让同一个模型补写期望，可能重现这个判断；仅报告“遗漏错误×stream组合”也掩盖了问题。

**对算法的实质要求。** 必须区分“消费前拒绝”和“已开始处理资源后失败”；必须独立于候选实现，核实 issue 的关闭义务在哪个 phase 生效。程序分析可提供可验证的有限选择：异常发生在 consume 起点前/后、close 是否后支配这一出口、观察是否同一 response。LLM 只在这个已定位的契约范围冲突上回答，并附 issue 原句；不允许用候选通过结果自动把 close=True 修成 False。

## N03：重复不是没看见；它在无界处理下不影响最终结果

**Explicit 测试。** step 32 写 `/tmp/test_daemon.py`，包含单个目录两个文件配额 1，以及同一 `watch6` 同时作为 CLI 与 config 来源但不设配额的场景。后者甚至有源注释：

```python
# both files move (CLI and config same watch; duplicates okay, each moved once)
assert len(list(movie6.iterdir())) == 2
```

step 32 首次脚本因最前面的 exit code 问题提前失败，**不能把该步写成通过证据**。step 33 修复后整个脚本输出 `ALL OK`。step 78 又运行该脚本及多份边界脚本，全部 OK，local tests `322 passed`。

**决定性 explicit 证据。** step 36 已经准确描述执行机制：

> each file appears twice as candidates ... first move moves file, second move fails because source gone (OSError -> logged). Result: still 2 files moved.

接下来又说：

> But if same path appears in both, it's duplicated. Not a problem for hidden tests likely.

所以不能说 agent 没发现 duplicate identity。它确实发现了，并根据观察到的无配额成功情形接受它。

**Explicit 另一条验证轴。** step 39 验证位置参数 d1 与 `--watch d2` 合并，但两个目录不同。该脚本后面日志行数断言失败；这里只能把前面已通过的断言作为局部证据，完整通过由 step 78 给出。step 59 再测试 `--watch d1 d2 --batch-size 2`，每个目录三个文件，断言只移动两项，输出 `BATCH GLOBAL OK`。reason 明确说是要证明全局 cap 而非 per-watch cap。

**Inference。** 同一路径多来源时的重复扫描，与全局配额都实际测试过；“重复只多产生一次可忽略错误、不改变完成结果”的已观察现象只在处理无界时成立。配额截断发生在 move 成功之前时，重复先消耗候选名额，再被 OSError 忽略。

**可执行的最小构造，不依赖目标字符串。** 对已有两个来源的位置绑定相同规范化 path，让至少两个不同文件可用；保留已有有限正配额 2。从候选代码读到按 path 排序以及 `candidates[:batch_size]`，可计算最短序列 `a,a,b,b` 的前缀长度 2 只有一个 distinct identity。测试不必认识电影文件名；需要证明资源 identity 相等、结果计数观察不同资源数、预算计数发生在成功过滤前。

**理论意义。** 幂等化（去重/忽略重复失败）与有界消费不交换：`distinct(take(2, [a,a,b,b])) != take(2, distinct([a,a,b,b]))`。这是能够产生长度和别名约束的代数反例，而非“两个功能相关”的标签。其适用范围应限定为可识别的 collection/budget/resource processing，不应强称可直接覆盖所有 17 例。

## N04：bulk 与 invariant 已共存，但 UPDATE 不改变 invariant；而且 agent 明确缩窄了验证范围

**Explicit 最初测试目标。** step 90 说验证 “bulk --safe-mode must support UPDATE”，一边验证 UPDATE 正常成功，一边验证语法错误和 UNIQUE 约束失败能 rollback。实际输出表明 SQL/UNIQUE 错误返回 1 且数据不变；这些错误并不需要应用级 import invariant 检查。

**决定性 explicit 证据。** step 170 明确写道：

> Since bulk has no table, no invariants. But maybe hidden tests expect bulk --safe-mode to validate invariants for ALL tables? That seems unlikely.

随后：

> The spec says "bulk --safe-mode must support UPDATE" — that's about the SQL, not invariants. I'll keep table=None.

这是具体设计决策，不是本文从后验失败猜测的心理。step 80 已实际传 `_safe_operation(_bulk_execute, strict=False, table=None)`；下游检查由 table 非空保护。

**Explicit 最终综合测试。** step 228 经过几次修复测试设置后成功，输出 `ALL FINAL CHECKS PASSED`：

1. 同一个文件 DB 的 t 表注册 `COUNT(*) = 1`。
2. safe insert 第一条成功，第二条失败，检查 count 仍为 1。
3. 同一 DB/t 表 bulk UPDATE `name` 为 X，检查 exit 0、实际 name 为 X。
4. 后面调用 validate CLI，却仅断言输出出现 “Pass” **或** “Fail”，不能提供 predicate 为真的独立判据。

step 229 全 suite `1070 passed, 16 skipped`。

**Inference。** “已注册 invariant + bulk + safe mode + 同 DB + 同 table” 全部发生了。缺的是写入触及 invariant 的观察内容并将它从真推成假：name UPDATE 对 `COUNT(*)=1` 不敏感。即使候选完全删除 validation，该测试也同样通过。这是验证空转，不是对象绑定完全缺失。

**算法要求。** 从 invariant SQL 提取读集合与语义：COUNT 读的是行数，不是任意字段；从 UPDATE 提取修改列与受影响行。先判断是否可能改变 predicate，再构造 `P(s)=true ∧ P(U(s))=false` 的输入。仅做列读写集合交集只是必要条件而非充分条件，例如 `age>=18` 与 UPDATE age=31 虽交集非空仍不判别。构造成功后，issue 决定应拒绝并恢复快照；不能从候选实际 exit=0 学到“应成功”。

## 四例共同约束：已有成功不等于已有区分能力

| Case | trajectory 实际提供的成功理由 | 该理由未覆盖的可计算条件 | 不能作出的表述 |
|---|---|---|---|
| N01 | 耗尽底层 iterator 导致关闭；后来正常增量流也通过 | throw 在 EOF/close 之前；异常出口上的同资源观察 | “agent 从未考虑 streaming”，或“任何 malformed 流都能检出” |
| N02 | 正常耗尽关闭；低层 API 异常不关闭可接受 | 消费中异常与消费前拒绝有不同义务；issue 与候选类比冲突 | “agent 没想到异常不关闭” |
| N03 | 重复 move 的第二次失败可忽略，无界下最终仍处理全部 | `take(k)` 在成功过滤前，重复占据有限前缀 | “agent 没发现重复路径” |
| N04 | UPDATE 能执行；SQL 异常能 rollback；COUNT 对 name UPDATE 不变 | 更新需要使已绑定 invariant 真→假；bulk 路径绕过检查 | “bulk 和 invariant 从未组合” |

这四例建议改变研究问题的叙述：不仅问“哪些操作没组合”，还问“已有测试为什么允许一种更弱的实现/解释与所要求行为无法区分”。这句话本身仍只是问题描述；下面只有在给出实际构造运算时才算方法方向。

## 两个能导出运算的方向（研究提案，不是已验证统一方法）

### A. 从断言的充分条件入手，系统反驳成功测试的简化理由

可借用 weakest precondition、control dependence、fault-based testing。候选单位不是一个自然语言关系，而是**断言成立所依赖的可执行路径条件或中间状态条件**。例如 N01 的“底层 EOF 已先发生”、N03 的“预算前缀中每次成功对应不同文件”、N04 的“验证 predicate 对本次 UPDATE 不变”。

具体算法步骤：

1. 以 source assertion 为根，反向 slice 到最后影响其观察状态的写入、分支和事件；保存具体 SSA value/object identity 与调用阶段，不只保存函数名。
2. 从已有测试的对比及 candidate CFG 定位让断言容易通过的条件：正常出口支配 close、列表截断前的 identity 重复、predicate 的 read set 与 operation write set 不相交。可用 execution trace 确认这些机制是否实际触发，而不是模型描述。
3. 生成对条件的最小反例：复用已引发 DecodingError 的字节使异常提前；把两个已有来源参数统一到同一 path 并保留有限预算；让 UPDATE 绑定已有 predicate 读取列并跨边界。语言层面需提供有限的 dataflow substitution、event/exit binding、scalar/collection construction 原语；不应放任 LLM 生成完整测试逻辑。
4. 对 scope 仍不确定的断言，提交“issue 原句 + 已定位的两个出口/状态”给 LLM 选择其适用域；输出是条件/候选选择，不是自由文本测试 schema。程序验证对象绑定、可达性与 definedness；assertion 的语义正确性仍需独立契约证据。
5. 先过滤没有改变相关状态/路径的候选。例如 COUNT 对 name UPDATE 不变可直接剪枝；malformed application/json 流在 parse 前已关闭也可由 trace 剪枝。这个过滤只能证明某种机制未激活，不能把相同观察值的所有候选一概判成无效——它们也可能正确地被系统屏蔽。

创新点尚待证明：用 validation 的成功依据来构造反例上下文，替代对测试文本的无约束乘积。风险也明确：完整 WP 在现实程序难计算；当前只给出了四例适用片段，不可宣称已统一处理 heap clone、区间重叠等其他关系。此方向如果最终退化成列举三类规则，就没有解决用户指出的工程拼装问题。

### B. 用 processing algebra 的不交换临界对生成有限反例

N03 最强支持此方向。程序中的 collect、sort、take、normalize、distinct/success-filter 对象可形成小的 stage 表达式。既有测试固定了输入元素与预算，静态分析恢复处理阶段次序；算法寻找共享资源维度上不可交换的邻接阶段，再用最小反例长度构造输入，而不是先枚举任意 relation label。

例如取 `take(k)` 与“相同文件只可能成功一次”的 effect summary，若 truncate 在重复失败过滤前，直接解最小整数/identity 条件：`0 < unique(prefix_k) < min(k, unique(all))`。最小可用候选为两个 identity、一个重复、k=2；实际排序需要重复相邻时，使用两个来源扫描相同目录即可保证。对已证明 commute 的阶段不生成组合，对资源读写不相交的阶段不生成临界对。

这可以借用 term rewriting 的 critical-pair 思想，但不能假装已有一般化定理：程序阶段不是现成纯函数，move 有副作用，success-filter 隐含在异常处理。需要从现有代码与小样本执行恢复 effect summary。LLM 可负责提出某调用的受限 effect family，例如 consume-once、count-preserving、predicate-read，但必须由代码/动态证据确认；否则“代数”同样会沦为 schema。

对 N01/N02 是否能用“parse/close/exception”表达为同一个阶段代数、对 N04 是否能包含 post-write validation，现在证据不足。该方向目前更适合成为 collection/resource 子域的深方法，不宜为了覆盖 17 例无限增加算子。

## 本轮不应继续作出的研究宣称

- 不能说 17 例都只是搜索没有覆盖到关系。至少本报告 N02/N04 含可见的规范范围错误。
- 不能说扩大 LLM 上下文自然能修复；这两个轨迹已经有需要的事实却接受弱语义。
- 不能把“覆盖了 throw 分支/UPDATE/duplicate”作为 combination coverage：N02 的消费前拒绝、N04 的不敏感 UPDATE、N03 的无界 duplicate 都是反例。
- 不能从候选输出修 oracle 来保证通过；这是这些缺口最可能再次出现的方式之一。
- 本轮没有检验新算法的实现、检出率或误报率，不改变已有 4/17 的实测结论。

## 步骤哈希

以下哈希由原始 trajectory 对象计算，供逐条核验。精确重算命令见本文开头的编码约定。

| Case | Step | Canonical step SHA-256 |
|---|---:|---|
| N01 | 26 | `d4eeb2bb0cedb4d70429702c60c73545ff229403a40a5d23f0800f7aa85ff00a` |
| N01 | 45 | `e65933f3b320ad894452f6a295c6563ae2c554dc85177e813d166f75ebd35327` |
| N01 | 57 | `b3e81c6fa31f7609c871bf61b17ef9251e204111a2521a32da902ab672ddc569` |
| N01 | 76 | `751cb9a20b67f76ec23c4514fc406dc40d2aa568bb9936ffecdcc518583a03de` |
| N01 | 77 | `1a6a6d77ccc5d264545ea08c1a37f9ad71a1f248fb0a2df03794cbfdce7f97ae` |
| N01 | 78 | `426192e2ef1498a0a4548c88356e1698f208a5cbf63a50d627c66e65d4455904` |
| N01 | 82 | `957656f841882677af784c4c88ce1737c272212e28092f78d201fde992bd87c5` |
| N01 | 95 | `b40e5b66a4b91db299a50413265461b7e3e744b28dbdaa57b27b6b3b27617377` |
| N02 | 54 | `8665ae0b0008bd1be2bf7d3ae4420999ecf5390fef9dcc58df5bdc78d165b163` |
| N02 | 57 | `4c4ae23220e69af7e1afb2126409316876474b6d486c0dba4948e0287c6151de` |
| N02 | 65 | `6c288d98e6e7c0696748aa9f9853c4b0e1f6a4287d9fd72980944de0e618f58a` |
| N02 | 67 | `21fa4e5ffdc75ac011fef79e5baf4a2de7d4ae2c19d382110e332efa727ea750` |
| N02 | 70 | `2a697ebdff5594c83d6d1770493f99c643f6e110265197713c50f38510d5de0d` |
| N02 | 99 | `a9f363b174930f9a8455be1c8dd0443e4202316ebf945eeb189d4ccd963daf69` |
| N02 | 113 | `a9113aab00b1099286cee788edbe72398ac9e5ffc9d99e033110022d50114aed` |
| N02 | 118 | `125344bdb11b9cec0c756b6fe2007e6da097669234a1c7e76140a13724f88356` |
| N03 | 32 | `d481ea63ff5d24029439c48ad0560ad244f3cb94161419fd91e5277126bb91e3` |
| N03 | 33 | `bfee35f58ce35776d2fdbac842ffd0c2b4e11bda4f884208b76357ac76e02dcf` |
| N03 | 36 | `11ae54e246bfe2b59275be76883c6872db12e5e1df8d6d604d61a90e047b0347` |
| N03 | 39 | `6c46f03bdefa810d191ff1c2a5c94713d5ff983dd72cfde5cd1541fdeccd1fa1` |
| N03 | 59 | `8d3819fac378b5d96373af32991ae8b74b75c46cb3f2168c9dcb075119cd910e` |
| N03 | 78 | `8426880039c9184d6703baf220c5d2a4067b43096e7556fc3d423623cdd85223` |
| N04 | 80 | `48cbf78fd6114fda9b969504fc91396d2f2fd5e62f245053487bfeb54e165ff5` |
| N04 | 90 | `1b64b0c25ec97a0a61541e1432102f90b50bbff74884e9311b69cb3f2de0ccf3` |
| N04 | 170 | `fba5738f6268040f27e1750405ae477dabc2dec578e3583d14f4ba6968c283bf` |
| N04 | 228 | `6b02bba56ac93bf5de53a1776200c0d8d0d6f48906173e1eb61ab429a3ca8422` |
| N04 | 229 | `e8926bd67e0b3dd64a8f2a94705c7ad58d8d065a17587da3d64c03104c90a8b7` |
