> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../../research/trajectory_logic_20260928/go_ts.md) · [旧路径映射](../../../../results/path_map.tsv)

# N05–N10：从测试生成过程重新审视组合缺口

本轮直接阅读六条 `data/relational_gap_v1/Nxx/trajectory.json`、对应 issue 与必要的最终候选代码，重点是历史 agent 为什么写这些验证、如何解释结果、之后改了什么。本轮没有新实验、没有 provider 调用、没有读取参考补丁或新增隐藏 verifier。历史结论只用于定位，没有把历史报告当作本次的原始证据。

先给出会改变研究问题的发现：**这六例不能统一解释为“agent 没有想到把 A 和 B 组合”。N05 已执行底层组合并接受异常输出；N06 已执行几乎就是目标的组合并通过，后来修改使其回归；N07 把目标部分重叠场景写在推理中，却没有执行；N10 在文字中想到默认调用，却仍只执行显式参数调用。** 继续把它们均标成未生成组合，会对方法提出错误要求。

## 证据约定

`STEP` 是原 trajectory 的 `step_id`，不是数组下标。下文引号是历史 agent 的可见 reasoning/message/command/result，不是本报告认可其推理正确。[go_ts_evidence.json](../../../../research/trajectory_logic_20260928/go_ts_evidence.json) 保留选中步骤的完整原始字段，并给出完整步骤 SHA；表内给出 SHA 前 12 位以便核验。步骤 SHA 按原步骤对象 `json.dumps(step, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')` 计算；原轨迹则直接哈希文件字节。

| 案例 | 原 trajectory SHA256 |
|---|---|
| N05 | `f38b401208ef5900d293ac348790fa769699409c12974ff3c33340e65c6cdf05` |
| N06 | `63c36dd161d0662815f5f0f5629b7dabe927e526036c744c6225e6f1f3d2ce6e` |
| N07 | `2345c3b8e9f7d93e53601dba66b639d94968f7f143f953d6542f871c0403e28c` |
| N08 | `f6f4c38299feff88e40dfcd86131a42a310cc9cbc8d320c18e05ad38fc5fba1d` |
| N09 | `f596ef89f8f046747d9d87a5f227ac05957767cf9419f23a90a1d0f0935e8bbb` |
| N10 | `12b498adb04285b2a6439f4f2aa3a16f6d29698c0c7a53c249179d672c9fe395` |

issue、model.patch 的完整 SHA 也在证据文件中。下文对“没再执行”的否定只覆盖这份完整 trajectory 记录的命令，不能推断记录之外不存在执行。

## N05 termenv：已经观察到组合行为，错误契约推断让报警消失

**为什么生成这些 tests。** STEP 23 明确要写 “a comprehensive test file”，按 ANSI tokenizer、width、truncation 等功能列例子。STEP 32 再按 API 入口列清单：`Style.PreserveResets`、`Style.Truncate`、`Output.String`、`Output.Truncate`、template helpers。Output preserve 的输入 `bold + foo + reset + bar` 宽度取 5，只有真正截断路径。最初 STEP 32 缺 `WithPreserveResets` 编译失败，不能算通过；STEP 35 补实现后又看到 template 断言问题，之后继续修复。STEP 37 主动发现 Style fitting 路径不重开样式，改为先调用 `Styled`，STEP 38 增加 fitting test。

| 步骤 | 短摘录或实际行为 | 步骤 SHA 前缀 |
|---|---|---|
| 38 | “Style.Truncate when the string fits but has internal resets — should re-open” | `8799d3698962` |
| 54 | 实际运行 `TruncateANSI("\x1b[1mfoo\x1b[0;31mbar", 7, PreserveResets:true)`；返回原串 | `5758643e3a85` |
| 55 | “the quick path returns unchanged… isn't re-opened with bold”；最后认定 “quick path behavior is acceptable” | `5f303e747a2d` |
| 84 | 明确写 `o.Truncate("\x1b[1mfoo\x1b[0mbar", 100, {})` 的两种候选输出，最后决定保留 quick path | `5ef5e224dae0` |

**原先的缺口分类不准确。** STEP 54 已在直接 callee 上执行 fitting × preserve，并打印未重开 bold 的结果。STEP 55 的解释不是没注意输出，而是认为 quick path 符合常见 upstream 行为。STEP 84 进一步精确提出 Output wrapper 的目标场景，既承认 issue 的字面含义支持重开，也承认 quick path 不会重开，最后以“spec doesn't say preserve-resets applies even when the string fits”接受现实现。STEP 84 的实际命令只是 branch/status、现有 suite 和 gofmt，没有把这段 Output 判别推演变成测试。

**可确认的机制。** 一方面按入口编排验证，Style 有 preprocessing 因而不暴露 Output 的缺口；更关键的是可观察的组合行为已经出现，却被基于惯例/猜测 upstream 的契约解释接受。这里至少是“错误 oracle/规格解释”，同时有“明确语义分歧没有形成约束当前代码的可执行断言”。不能再称纯粹输入组合缺失。

**方法要求。** 只扩大输入生成将再次产生 agent 已见过的输出。需要保留当前实现与另一可执行解释之间的分歧，并从 issue 的一般义务或可信 sibling API 契约独立确定 oracle；不能从当前 candidate 输出学期望。跨入口对比可以定位不一致，但 Style 与 Output 的规格本来允许不同 Ascii 行为，因此“所有入口都等价”也不是合法万能 oracle。

## N06 etree：目标组合已经通过，后续过宽分类使它回归

**为什么生成这些 tests。** STEP 29 以 “exercise the new API… comprehensive test” 生成 DeepEqual、diff roundtrip、patch format、merge、reverse 等按功能分组的测试。看到 roundtrip 与 XPath 索引错误后修程序；看到“新元素自带属性”不等于“既有元素新增属性”后修测试输入，STEP 34 相应测试通过。STEP 41 增加结构冲突、auto resolve 等例子；错误命名 `diff_test2.go` 导致未执行，STEP 42 重命名才真实通过。

| 步骤 | 短摘录或实际行为 | 步骤 SHA 前缀 |
|---|---|---|
| 45 | “ours adds an element and theirs changes text of a different element — should merge cleanly” | `e526ca931f5e` |
| 45 | `/tmp/dbg3.go` 实跑：base `<root><a>1</a><b>2</b></root>`；ours 加 `<c/>`；theirs 把 a 改 9；结果 `conflicts: 0`、两修改均在 | 同上 |
| 50 | 为处理 Add+Replace 重写 `classifyConflict`，实际代码用 `isStructural(a) || isStructural(b)` | `7a4ea8d907c8` |
| 51 | 只新增 `TestMergeIndependentAdds`、`TestMergeAddVsReplaceConflict` 与 move test，三者通过 | `39f40a06995b` |
| 109 | 最后 `go test ./... -count=1` 通过，但不包含外部 `/tmp/dbg3.go` | `b28126e33610` |

**这个案例不是从未形成目标组合。** STEP 45 是目标关系的直接实例：共同父节点下新增兄弟元素与既有 child 文本修改，明确预期无冲突，实际输出确实满足。STEP 46 开头说 “Good, non-conflicting merge works”。这比单独 A/B 验证更强。

STEP 50 出现可定位的回归过程。agent 讨论 Add+Add 是否应该冲突，明确拒绝字面“同父路径就是同修改”的解释；随后担心 Add+Replace，文字计划一度是 `isStructural(a) && isStructural(b)`，实际生成程序却用了 OR。结合 `related` 的路径前缀判定，任一 structural 操作与 descendant text 操作都可能被标成 structural conflict。STEP 51 只验证新增的 Add+Add 例外和 Add+Replace 冲突，原 `/tmp/dbg3.go` 没纳入 suite，在整个剩余命令中也没再次出现。最终候选 `repository/diff.go:1353` 仍是该 broad OR 判定（后来 text×attr 的修正没有解决它）。

**可确认的机制。** 已经验证的独立性在后续分类泛化中被破坏，且一次性脚本不再执行。可称“validation evidence 随程序修改失效而未被重新验证”。这是研究目标的一个重要边界：历史测试 corpus 包括这个正确组合；当前算法若要从历史 validation 修补 agent，应首先恢复它，没必要重新发明组合。

**方法要求。** 原成功观察必须绑定代码版本，后续变更触及其调用/效果切片时重新建立有效性。普通 regression test selection 就能解释这一需求；如果方法只做最终版本的输入组合，这一缺口会被误诊。注意这里并未本轮重放 STEP 45 对最终版本的失败；回归定位来自完整命令序列、实际旧输出、最终分支逻辑和已有公开失败的独立历史证据。

## N07 go-git：准确说出了目标区间关系，却以想象执行代替测试

**为什么生成这些 tests。** issue 明确要求 overlap 与 repeated lines。STEP 42 设计两个 diff-hunk 序列同步扫描；STEP 51 用少数代表性端点手推来确认算法。STEP 62 再按 fast-forward、普通 merge、content conflict、delete/modify、add/add、file/dir、dirty/config/index 分类写测试。相同中间行冲突与首/末行分离是典型代表。STEP 62 初次编译失败，STEP 63–64 修 test，STEP 65 逐项通过。

| 步骤 | 短摘录或实际行为 | 步骤 SHA 前缀 |
|---|---|---|
| 51 | 手推 `[1,2)`×`[2,3)` adjacent；`[1,3)`×`[1,2)` same-start overlap；均认为正确 | `04d1a4bba5fc` |
| 66 | 临时诊断含 “repeated overlap”，实际都是同一行 `[1,2)`；输出打印而非 assert | `172b2ebeac41` |
| 82 | “ours deletes [1,3)… theirs changes [2,4)… Overlap [2,3). Conflict.” | `a3369e385449` |
| 145 | 恢复 `/tmp/worktree_merge_test.go` 跑现有 merge suite 后再删除；“complete and robust” | `617179b7de4c` |

STEP 66 的诊断不是无效：它实际发现 insertion 重复输出，STEP 67–68 据此修 hunk 起点。然而后来 STEP 82 **精确**写出不同起点的部分重叠，并直接推断会输出 markers、推进到 `max(3,4)`，没检查是否能进入同时处理两个 hunk 的分支。该步命令修改的是 Commit 的 MERGE_HEAD 删除时机并跑既有 tests，没有执行这组区间或对应文本。后续 STEP 97 又以“overlapping correctly. We tested”回顾，STEP 146 最终声称 detects content overlaps。

**可确认的机制。** “overlap”这个行为类别已有通过示例；不同端点关系只在口头推理中被等同为同一已覆盖类别。目标组合不是 agent 想不到，而是把自己认为的路径当成实际路径。既有候选仅在两个 hunk 同时满足 `start <= basePos` 才走 conflict；先遇到的 hunk 会跨过另一个起点。这里需要把具体推演转成实际输入，不应再要求模型开放式想更多 edge cases。

**方法要求。** STEP 82 已提供 high-value 约束及预期，搜索应先让构造后的文本经真实 diff pipeline，确认 hunk 区间确实是该相对关系，再执行真正的 Merge 和相应错误/marker/index 观察。直接把 normalized hunks 注入私有函数只能证明组件，不等于端到端解决；上一轮 N07 broad unequal-start overlap 也不等于已覆盖所有严格 partial overlap。

## N08 Pebble：明确知道 exclusive range，却选了内部点和远端点

**为什么生成这些 tests。** STEP 117 按 callback、wait、job、notify、stats、DisableWAL、close、metrics 八块列验证。STEP 115 使用 “comprehensive test file”。模型有意使 tests 较快且易协调：等待远端目标会慢，所以按现有 blocking test 处理；notify 真正覆盖 future target 被认为 “Hard to coordinate ordering”。这些选择把最有区分力的边界关联拆开了。

| 步骤 | 短摘录或实际行为 | 步骤 SHA 前缀 |
|---|---|---|
| 45 | “A batch occupies seqnums `[SeqNum, SeqNum+Count)`” | `13cbd1f0070ad` |
| 117 | 两次 Set 后 Wait(s)、Wait(s+1)、high≥s+2；远端等待100000；notify100的 ch 最后丢给 `_ = ch` | `7039ffa3e4e9` |
| 118 | 删除本来错误的 `NoError(Wait(s+1000))`；认为另一个等待测试已覆盖；解释 `_ = ch` “fine” | `712085f3b780` |
| 209 | “a batch with 2 records has seqNum range [seqNum, seqNum+2), so seqNum+1 is covered. Good.” | `b53881d3db90` |

候选代码也将 `HighestDurableSeqNum` 注释为 exclusive（`durability.go:35`），计算 `seqNumEnd = b.durableSeqNum + keyCount`（118行），但 register/signal 使用 `target <= high`（169/194行）。这不是 reviewer 事后才赋予“exclusive”解释：trajectory STEP 45 和 STEP 209 都明确知道区间右开。

补充核对：STEP 117 / 候选 `durability_test.go:102,196` 已在初始化时执行 `WaitForDurability(0)` 和 `DurabilityNotify(0)`，tracker 初始 high=0。因此不能说全局没有 `target=high`。本文所说遗漏端点专指**非空 batch 完成后，由该批次产生的实际 exclusive high**；初始化的相等不覆盖这个来源/阶段。这要求关系反馈保留值的更新来源，单独统计比较结果会误判已经覆盖。

STEP 117 的生成逻辑已经接近正确实验：“call DurabilityNotify(seqNum+count) before commit? Hard to coordinate ordering. Simpler: call … a future seqnum …”。实际代码却先订阅常量100，提交1条，另外只读 `DurabilityNotify(s)`；100的 channel 不检查是否 ready。STEP 118 没补 future assertion。`Wait(s+1)`不是边界错误证据，因为其 test 写了2条记录；STEP 209 甚至明确正确算出这一点。STEP 126 定向 tests 通过，STEP 234 race 定向 tests 通过，均未增加 `target=s+count` 的相等端点。

**可确认的机制。** 生产操作返回的范围与消费目标之间的边界约束在 reasoning 中存在，但实际 tests 用内部点证明成功、远未来证明等待，遗漏恰好相等。future channel 的断言又因实现便利被删去。这是“计划与具体执行输入不一致”和“操作已发生但观察缺失”的联合例子。

**方法要求。** 利用代码中的生产式 `start+count` 直接构造消费者值，而不是泛化地把任意两个 integers 做±1。target 要绑定同一 DB、已经完成的一次 batch、实际 count，观察必须是未就绪而不是只检查函数返回。该义务来自 exclusive range，不能从现有错误 ≤ guard 自证。

## N09 Koota：记录级二分测试掩盖字段级混合

**为什么生成这些 tests。** STEP 28 直接将“has/get same as after flush”解释为 virtual overlay；STEP 33 要实现 “projected state comprehensively”。STEP 38 用 `hasParams` 表示 pending value 来源；STEP 54 comprehensive repro 采用 `trait({value:0})`、完整参数 `A({value:1})`，观测 flush 前后；最初 get/has 失败促成多轮修复。正式14项测试继续主要用一字段 A/B。

| 步骤 | 短摘录或实际行为 | 步骤 SHA 前缀 |
|---|---|---|
| 54 | 单字段 A、B；`e.get(A).value===1` before/after flush；初次 before get 失败 | `f7127c26da55` |
| 113 | 分别说 hasParams=true “returns params object”、no params “returns defaults… Good” | `25777047b95b` |
| 194 | 修 absent/live defaults 分支；打印 amount7、amount0、value0 三个一字段结果 | `a76af02d7911` |
| 195 | 正式 deferred suite 14 passed | `1fa6fbd1f3f8` |

STEP 194 是关键：agent 注意到了无参数的新 trait/relation 在现有 entity 上 get 没 default，于是改成先返回 liveValue，缺失再 defaults；但保留最前面的 `if (traitState.hasParams) return traitState.params`。临时脚本分别验证参数对象与完全默认对象，而不是一个多字段实例既有显式来源又有默认来源。

**可确认的机制。** 生成者采用了与实现相同的二分：对象“有参数/无参数”。在单字段 schema 中，这恰好等于字段“全给/全不给”；于是全部示例满足 `hasParams ⇒ no missing fields`，这个意外前提掩盖了 issue 的一般保证。没有发现 target “部分参数 + 多字段 default + before flush”在记录中被明确考虑；这是六例中较干净的组合输入缺口。

**方法要求。** 从 trait schema 的字段构造与 pending params 的字段使用恢复两种值来源，不需要自然语言 feature tags。最小构造必须有至少两个字段、只显式提供其中一个，再在 before-flush 投影中读另一个。规格已直接给出 before/after flush 等价，因而可以先 clone snapshot 再 flush 对照；只重复 full/default 两组测试或比较同一可变引用会无效。这个具体操作需要接口语义，而非任何 record 都盲目删一个字段。

## N10 DynamoDB：文字声称默认入口已覆盖，执行只验证显式 mode

**为什么生成这些 tests。** STEP 54 把 conditional requirement 按 put/update、DTO、JSON、Zod 逐项设计。Zod parser helper 被写成仅在 `mode==='put'` 执行，于是 STEP 124 手动脚本和 STEP 161 正式 test 都显式传 mode，直接满足新代码的 guard。

| 步骤 | 短摘录或实际行为 | 步骤 SHA 前缀 |
|---|---|---|
| 124 | missing/present trigger 的 parser 均 `.parser({mode:'put'})`；console 结果合理 | `01b678e96b39` |
| 130 | helper 解构 `{mode}`，`if (!hasRequiredIf || mode !== 'put') return zodSchema` | `5fde03d02d22` |
| 135 | “Hidden tests might call `.parser().parse(...)` and expect a ZodError. Our superRefine … Good.” | `18638a081f21` |
| 174 | 类型允许 `'key' | 'put' | undefined`；删除非法 update test，仍只保留 put | `3e6f70332e70` |

STEP 127 原 suite 报 ZodObject 变为 ZodEffects，使 agent 给无 requiredIf schema 加了保护分支；这属于真实 regression feedback，修复有依据。但 STEP 135 的默认调用仅在推理中出现，该步执行的是 anyOf、nested `$set`、多规则条件例子，未执行 `.parser()` 加 requiredIf。STEP 174 又看到 `undefined` 是合法选项，仍只修非法 `'update'`。STEP 180 八项新增测试通过；STEP 201 730 schema tests 通过。baseline 的默认参数 tests 没含新 requiredIf，所以这些结果无法支持文字中的一般结论。

**可确认的机制。** 测试沿新实现分支进行生成，显式设置选项以激活新功能；review 又把显式配置的结果提升到公共默认入口。缺口是默认配置归一化的调用链没有落实在新 guard 上，不是完全不知道 defaults API。

**方法要求。** 追踪 optional parameter 到 defaults 与新 guard 的数据流；省略调用与显式默认调用应属于同一公开模式，但内部判定分别读 raw undefined 与 normalized put。LLM 可定位语义上的默认等价；删除一个 optional argument 是程序操作，错误 oracle 则可沿原条件 required assertion 保留。

## 对学术设计最直接的约束

| 案例 | 输入组合是否真正缺失 | 更准确的遗漏环节 |
|---|---|---|
| N05 | exact Output 未执行；callee同根组合已执行 | 输出被错误契约解释接受；没有可靠 oracle |
| N06 | 否，目标关系的组合已经执行且通过 | 后续修改使旧验证失效；临时脚本未重跑 |
| N07 | 目标具体约束在文字中明确存在 | 手推代替真正路径执行 |
| N08 | 精确 s+count 未执行；future计划有所表达 | 参数未绑定实际生产状态；future观察被丢弃 |
| N09 | 是，未见 multi-field partial params 场景 | 记录级布尔分支遮蔽字段级混合 |
| N10 | 默认调用在文字中存在 | 有关该调用的正确性主张没有相符运行 |

“comprehensive”并非覆盖证据：N05 STEP23、N06 STEP29、N07 STEP47、N08 STEP115、N09 STEP54 都有类似主张；N07 STEP145 还说 complete and robust。需要把 **说过、执行过、在最后版本执行过、观察能区分、期望有依据** 分开，否则方法会把口头推演和失效历史通过都算成 coverage。

## 一个可继续研究的算法方向：从仍未区分的可执行解释生成测试

这是一项待验证设计，不是新的已成立贡献。可借用主动学习的 distinguishing query、mutation testing 的可观察区分、regression selection 的版本依赖，但对象需要改为 **trajectory 中仍与现有验证相容的局部行为解释**。不是把每个关系填成自然语言 schema，也不是要求全仓库生成一个正确参考实现。

### 构件与明确操作

1. **收集可执行候选解释。** 优先使用已经真实出现的历史局部实现/编辑前后版本，和 trajectory 中具体代码化的替代方案。N06 的 STEP45 时实现与 STEP50 后实现天然给出一对；N05 的 quick return 与 always-process 分歧可映射到特定 early return；N07 的文字区间可生成一个局部区间判定备选，但此映射需 LLM 产出小代码并进行类型/来源检查。没有可执行差异就暂不称之为 hypotheses。
2. **历史验证构成经验等价类。** 对可执行解释记录有限 tests 下的输出向量。旧验证不能区分的解释才值得继续搜索。版本改变使旧结果失效时优先重跑受影响脚本（N06），不要立刻发起全新合成。这里的经验等价不意味着语义等价。
3. **针对差异切片改测试。** 从局部程序差异反向找到控制/数据依赖的输入 AST 节点；复用已有测试构造器和断言对象。可执行操作是替换/省略同类型实参、连接既有生产表达式到消费参数、按 AST 同名字段替换局部 record、保留已执行前缀并重建依赖观察。选择只影响差异切片的编辑，按编辑距离枚举；优先 trajectory 已写明的具体输入（N07）和历史脚本（N06）。
4. **以观测分歧作为搜索信号。** 执行候选输入在小范围解释上的输出；不分歧的测试不增加对这些解释的区分能力。若内部路径已分歧而原断言值相同，沿差异的 forward slice 到公开 getter/return/error/status，搜索 type-correct observer 链，输出真正的 distinguishing test。这可借鉴 STARS 的表示到生成操作，但不是盲目把 observer 加到任何输入。
5. **最后才裁决 oracle。** 区分只表明现有 tests 不充分，并不证明当前 candidate 错。N05 必须用 issue/已有明确契约裁决；N06 可用早先自己明确并运行过的无冲突义务；N09 可用 issue 明说的 before/after flush 等价。若无独立依据，交付分歧而非自动硬写 expected，不能当真实 bug。

### 为什么比旧问题描述更可算法化

目标从“构造未知的正确组合关系”变为“让两个具体程序解释在可观察输出上分开”。已有成熟的 differential execution、dynamic slicing、mutation-directed input search 可以给出可执行搜索信号。LLM 的任务是把历史可见的一小段分歧映射成局部候选或识别契约出处；它不需凭空完成整个组合和 oracle。剪枝可以明确由类型不合、差异切片无依赖、所有解释输出相同、重复输出向量和成本界来做。

但这还没有解决所有难点：构造复杂输入时依然可能缺少有效编辑语法；局部解释是否代表有意义的候选需要验证；N09 未见显式 partial/default 替代解释，必须从实现默认来源不一致或额外局部 mutation 得到，不能假称 trajectory 已直接提供。主张创新前应检验它相较常规 differential/mutation testing，是否因 trajectory 的实际设计分歧而显著减少无效 mutants、无关输入和错误 oracle。尤其 N05/N06 的重新分类应在评价中独立报告，不能混入“新的 combination 生成成功数”。
