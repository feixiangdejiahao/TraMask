# P1–P7：从原 trajectory 重建验证逻辑

本次阅读直接使用 `data/relational_gap_v1/P{1..7}/trajectory.json`、同目录 `issue.md`。`target_census.json` 只用于定位已知缺陷；下文不把事后 target 描述当作 agent 当时的想法。没有调用 provider，没有重跑 repository 或修改方法实现。

**核心结论：这七例不能统一解释为“agent 只测试两个独立功能、从未想到组合”。** P1、P5、P6 已构造复杂组合；P2 在代码里明确写出了错误的组合例外；P7 的组合 schema 已存在，但非恒等变换仅由类型测试观察。能从轨迹支持的共同点较弱：agent 将某一组有限观察作为一个更广行为声明的证据，却没有构造能够区分该声明及其近邻错误实现的实验。这个共同点是研究动机，不能直接宣称为新算法。

`pilots_evidence.json` 记录全部引用 step 的 canonical SHA 和每条 command SHA。原始 JSON 中的 `step_id` 是下文的 step，不是终端命令计数。引用 `reasoning_content` 的地方明确标示；这些是原数据已有的 agent 文本。P4、P7 没有 `reasoning_content`，不能凭空重建其内心判断。P1–P7 原生成模型也各不相同，不能把这些 pilots 称为七条 DeepSeek-v4-flash trajectory。

| Case | 原生成模型 | 本次证据支持的遗漏方式 |
|---|---|---|
| P1 | openai/gpt-5.6-sol | 新相位能力的验证只覆盖 `u` 编码族；实现有意保留另一编码分支 |
| P2 | anthropic/claude-opus-4-8 | 实现明确加入 “associated text 例外”；验证 checklist 未挑战这个错误例外 |
| P3 | vertex_ai/gemini-3.6-flash | alternate alias 和 shift 分别有检查，alias 所用代表是 ctrl-only；未检查含 shift 的归一化 |
| P4 | vertex_ai/claude-fable-5 | magic roundtrip 有完整观察，但测试路径从不进入 quoting 的非平凡语义；不是缺少一个已知的第二测试 |
| P5 | openai/gpt-5.6-luna | nested callable 与 returned callable 都验证过，但 producer 边界不同：Get 容器 vs Call 返回单函数 |
| P6 | anthropic/claude-opus-4-8 | 验证跨实例隔离、单闭包连续更新，没有双闭包共享同一捕获单元的形状 |
| P7 | anthropic/claude-sonnet-5 | 递归+非恒等 transform schema 在类型测试中已生成；runtime 用 readonly、输出等于输入 |

## P1：验证域跟随实现分支被切开

**明确证据。** step 11 的复现字典依照 issue 枚举 Kitty press/repeat/release、shift A、alt shift A、alternates ctrl plus、associated text、legacy alt 四类。相位序列均为 `\x1b[97;1:{1,2,3}u`。step 14 message 明确说：

> “retaining the old xterm branch for `~`, arrows, and function keys.”

同一 step 新正则只接受末尾 `u`，旧 `_re_extended_key` 保留 `[u~ABCDEFHPQRS]`，只解析旧 modifier、不解析 event type。这不是根据 hidden verifier 推测的分支划分，而是 agent 自己宣布并写出的实现边界。

step 16 `test_kitty_key_phase` 对 `event_type` 参数化，但固定 primary code `97`、末尾 `u`。这个测试严格检查 phase 和 is_press/is_repeat/is_release，并非弱断言。与此同时，`test_kitty_associated_text_preserves_key_metadata` 使用 `\x1b[97:65:113;2:2;65u`，同包已经包含 alternates、shift、repeat、associated text。**所以“没有做多维组合”在本例直接被反证。**

**验证演化。** step 16 测试首先发现 legacy uppercase 从 `A` 变为 `shift+a`；step 17 修条件。step 30 主动发现 alias-list 测试不足以证明 binding 命中；step 31 加真实 App binding integration。step 38 又验证 release 被 app 接收但不会触发 binding，输入仍是 `97;1:3u`。step 41 输出 `251 passed, 1 xfailed`，step 45 提交。agent 并非停在单元属性观察，而是能主动追踪较长调用链。

**事后解释及限度。** 更精确的遗漏是：相位保证从一个 parser 编码分支推广到所有键，而测试的编码 constructor 没有跨分支移动。现有日志没有一句“功能键无需相位”的判断，因此不能说 agent 明确拒绝组合。它明确选择保留旧分支，遗漏是否来自兼容性意图还是单纯疏忽，只能推断。

**算法启发。** 别只提取 token `repeat` 和 `function key`：从 branch→event-field 定义链发现多个 producer 都产出 `Key`，但只有部分 producer 写入 `phase`；把已有相位断言搬到另一个仍产出同类事件的编码 constructor。需要程序恢复具体 grammar alternative（例如有 `~` / `A` 结尾），不能只随机交换数字。

## P2：agent 写了组合语义，却写成了错误例外

**明确证据。** step 22、46 的 `reasoning_content` 都重复 non-shift modified shortcuts 应 `character=None`。step 61 实际生成的 helper 尾部却写：

```python
# A modified shortcut (or a non-printable key). Build a stable name of
# the form "modifier+modifier+key" and report no character (unless the
# terminal sent associated text).
key_name = "+".join([*modifier_list, base_key_name or ""])
yield events.Key(key_name, text or None, ...)
```

这表明 associated text 与 modified shortcut 的重叠情况**已出现在实现语义中**，但被赋予错误例外。不能归类为“从没考虑两者同时出现”。没有找到独立 reasoning 为该例外提供 issue/规格依据；代码注释是最直接的证据。

**为什么生成这些测试。** step 63 message 要做 “comprehensive verification script ... all the issue requirements”，脚本逐段打印 `=== REQUIREMENT: ... ===`。non-shift 行用 `\x1b[65;4u`、`\x1b[97;4u`，text-only 行用 `\x1b[0;;97u`；这些输入正好避开例外。step 64 遂说 “All requirements are satisfied”。step 85 将其固化：`test_kitty_non_shift_modified_printable_has_no_character` 包含足够强的 `assert event.character is None`，但输入仍没有 text；`test_kitty_text_only_key_code` 单测 `key_code=0`。

**验证演化。** step 85 输出 `72 passed, 1 xfailed`；step 117 为 `133 passed, 1 xfailed`；step 131 为 `114 passed, 1 xfailed`。不断扩大回归测试数量没有改变这两个输入代表的重叠空白。旁支中 step 73、101、103 的 reasoning 知道 declarative binding 可能仍不匹配，但选择用 method-handler 的成功解释 shortcut fix；这是另外一处主动缩小验证范围，**不能拿它当本例 character 缺陷的直接根因**。

**事后解释及限度。** “只生成 checklist 的典型正例，未验证保证和自加例外的冲突”由轨迹强支持。原断言本身不弱；后来我们算法投影只保留 key 才变弱，这两个阶段必须区分。

**算法启发。** 该例最值得搜索的是代码新增的分支例外：`character=None` 的契约域与 `text` 非空的 producer 条件相交。从现有断言回溯参数 `text or None`，解出非空 text 即可得到挑战例外的候选；语义是否允许例外仍需 issue 契约或少量 LLM 判断，不得用候选输出自行修 oracle。

## P3：代表性例子隐藏了 modifier 归一化义务

**明确证据。** step 18 `reasoning_content` 把 issue 的 alias 例子解释为带 Ctrl、shifted_key 为 plus，应该产生 ctrl+plus。step 41 再用 `\x1b[61:43;5u` 推演同一个例子。这里 modifier `5` 只含 Ctrl，并不含 Shift。

step 92 描述按 API unit 与 parser 划分测试；step 93 生成：

```python
k = Key("ctrl+equals_sign", None, modifiers=["ctrl"], shifted_key="plus")
assert "ctrl+plus" in k.aliases
```

同 step 又有 `test_key_modifiers_sorted_tuple`，使用 `["shift", "ctrl", "alt"]` 检查排序与属性，**但没有 alternate metadata**。step 96 parser alias 测试同样用 `61:43;5u`，要求 ctrl+plus；shift-only 测试使用 `97;2u`；non-shift shortcut 使用 `97;4u`。已验证的 modifier 构件不少，缺的是 modifier 与 alias 产生规则交互。

**验证演化。** step 97 测试暴露 legacy 输入需要 EOF flush；step 98–100 排查并修测试的消费阶段。step 124 最终 `82 passed, 1 xfailed`。没有找到与 target 相关的“带 Shift alternate alias”的失败后放弃，也没有找到显式拒绝这种组合的理由。

**事后解释及限度。** 两种“Shift 信息”分别编码在 modifier bit 与 shifted_code 中；若只保留原 modifier 并换成 shifted name，可能重复表示 Shift。这个是我们的语义解释，不是 agent 当时明确命名的原则。轨迹支持“只以 ctrl-only 的 alias 示例作为代表”，不支持“完全不了解 alias binding”：step 32、43 实际认真追过 binding 消费。

**算法启发。** 不只是 `5→6` 常数变异：应识别 `shifted_key` 与 `shift` bit 是两条抵达同一 alias 的语义通道。程序可先找到两字段共享的输出 slice，再生成控制二者同时非平凡的输入；LLM 最适合局部判断重复语义是否应消去，不宜自由生成整个测试。

## P4：有完整 roundtrip，但输入一直让表示转换退化为恒等

**明确证据。** step 26 “comprehensive test script”，step 27 “edge cases: error conditions, overwrite behavior, context manager, and validation errors”，step 28 又在真实 IPython subprocess 验证交互 magic。step 31 正式 `test_magic_start_stop_roundtrip`：

```python
bundle = tmp_path / "demo.ipybundle"
shell.run_line_magic("session_bundle", "start %s" % bundle)
status = shell.run_line_magic("session_bundle", "status")
assert status == {"recording": True, "path": str(bundle)}
...
assert bundle.exists()
```

magic、direct API、save/load/replay、overwrite、redaction 都有测试，但 generated magic paths 用 `demo.ipybundle`、`a.ipybundle` 等。step 27 的 whitespace 是“空白 cell 不记录”，不是路径含空格。扫描 agent message、reasoning（本例无 reasoning）及 command，未找到 quoting/shlex/含空格路径测试。不能虚构一个已被 agent 验证的“quoted paths 测试 B”。

**验证演化。** step 32 修测试的 `%` 拼接；step 67–69 为 nested run_cell 加帧状态修复及测试，step 69 输出 `46 passed`。step 84 再写 “Final verification: each requirement ... checked explicitly”，依旧 `spec.ipybundle`。step 85 “Every requirement verified” 后提交。

**事后解释及限度。** 相同路径在 direct API 中是 Path，在 magic 中是命令字符串。普通路径使 encode/decode 边界几乎不可见，因此返回 path 和真实文件断言虽然强，也无法暴露 quote 字符被保留或空格拆分。没有证据 agent 主动认定“不需要支持 quoted path”；这是域代表选择的缺失。也不能说只是两个现有 tests 的 permutation，至少要引入一个能让字符串表示转换非平凡的值。

**算法启发。** API 适配层的 test lifting 应围绕同一语义参数跨两种表示的往返，而不是文本上拼两段测试。候选 grammar 可从 CLI tokenizer/argument parser 的特殊字符分支恢复；既有 direct API roundtrip 充当语义锚点，生成的 magic command 必须由明确编码器产生，例如 shell quoting，而非随意加双引号。程序证明不了实际 parser 所接受的 quoting 规则时应限定假设。

## P5：大量真实组合仍没有跨过正确 producer 边界

**明确证据。** step 21 已明确理解 closure 的 `Free` mutable cells 与 globals 分离，并计划递归处理 composite callables。step 49 要做 broader test，step 50 `/tmp/tengo_broad.go` 让 source globals 的 `arr=[fn]`、map、clone、跨 script Set、callback、module export 都参与验证。step 51/53 真实观察 cross-script 调用 panic，后续修复。**agent 会组合，并且组合已经发现过缺陷。**

step 90 `TestCompiledFunctionGoCall` 从 `compiled.Get("holder")` 得到 `{"nested":[{"fn":fn}]}`，再 `callInt(nested.Value["fn"])`。同批 transfer test 先变更 capture，再 Clone/Set，再验证 source 不受影响。step 103 又明确发现并修复“transferred source function ... called inside destination function”的 constant-pool/frame 边界。这些不是独立 happy-path 的堆砌。

step 121 临近结束才补 returned closure：

```go
returned, err := compiled.Get("make").Object().Call(callableIntObject(3))
require.NoError(t, err)
require.Equal(t, int64(19), callInt(t, returned, callableIntObject(1)))
```

这里 return 是**单个 closure**。nested callable 的容器始终由 `Get` 取得；没有返回复合结构后访问其 callable 再调用的测试链。step 124 总结 “direct/returned/nested callables” 全覆盖，step 126 `go test -race ./...` 通过，step 128 完成。

**验证演化中的 oracle 修正。** step 90 的首次测试 step 91 出現 `Expected:18 Actual:19`，同轮另一个 cross-instance 期望错误也失败。后续一方面修测试计算，一方面修真实 VM 边界。不能把所有 assertion change 统称为“迎合实现”，要看它是否有脚本语义支持。

**事后解释及限度。** 其缺失项不是词汇集合里的 `returned` 和 `nested`，而是把可观察操作链 **Call→composite→member→Call** 放到同一个 runtime 生命周期中；同构形状通过 Get 得到，与通过 Call 返回，不一定具备相同绑定/栈所有权。不能只比较 object 类型来证明等价。原 trajectory 没有明确说复合返回不需要验证。

**算法启发。** 以 producer-sensitive 的 typed context 展开现有测试：保留访问/调用后缀，把前缀 producer 从 Get 的已存在实例替换成同类型 Call-return，或把 factory 的返回表达式包在已有 array/map constructor 里，再复用 access/call。这是可枚举的程序语法构造；只记录 `contains(callable)` 无法导出它。

## P6：隔离被当成“多复制”，遗漏保持内部共享

**明确证据。** step 27 用简单 add 函数复现 Call no-op。step 33 `reasoning_content` 已谈 alias/identity 和浅拷贝 Free；其中把多个 global 指向同一个常量函数拆开，判断 “doesn't matter for equality checks or TCO”。**这段讨论的对象是常量函数 identity，不是两个 closure 共享捕获 cell，不能将其偷换为 target 的直接决策。**

step 40 强调 Clone 要 deep-copy `Free ObjectPtrs`，以避免跨实例状态泄漏。step 55–59 真实遇到共享 imported module map 的 race，再改为 copy-on-change。step 63 comprehensive requirement tests 包含：

- clone isolation：一个 `inc` 写 global counter，调用两次，检查 clone=2、source=0；
- transfer closure：一个已经把 captured `n` 加到 2 的 counter，Set 后验证 destination 用自己的 global，source 继续到 3；
- nested transfer：容器中多个函数，但它们读 global `g`，不共享一个局部 capture。

step 73 新增 repeated Go calls/state persistence，再 step 85 整合到 `TestGoCall_StatePersistence`；依旧是同一函数反复更新 global。轨迹没有构造 `writer`、`reader` 两个不同 closure 指向同一个捕获单元，随后 clone 后 write/read 的序列。

**验证演化。** step 63 transfer panic，step 65 保留 origin constants；step 66 还剩错误期望和脚本 trailing comma；step 69 查出 array out-of-bounds 返回 undefined，step 70 选择真实 runtime error 替代错误测试假设。step 77–84 又实测跨池函数调用并修复。step 86 all 17 tests pass，step 93 完整测试通过后提交。

**事后解释及限度。** agent 做了隔离、持续性、共享组件 race 的测试，但缺的形状是“外部不共享且内部仍共享”。因为只有单捕获闭包，复制所有 cell 和保持源 heap alias class 的复制在这些输入上观察等价。语义差异是 heap topology，不是语句执行次数。

**算法启发。** 只做 test concatenation 不够。应对包含 reference/capture 的测试抽取 small heap shape（根、边、alias partition），生成“两个不同根汇到同一可写 cell”的最小形状，再在 transport/Clone 两侧布置 write/read。写→读后缀可从已有同闭包 state-persistence 测试提取，但必须生成另一个读根，不能只换变量名。这个分支可能值得独立研究，用图同态/别名保持的复制契约给算法具体约束。

## P7：组合已有，验证投影却让差异不可见

**明确证据。** step 114 全库原测试通过后说 “write actual tests ... runtime behavior”。step 132 明确按 `array/record/map/set/pipe/intersect/object` 列举 runtime cases。step 134 runtime pipe 使用：

```ts
const TreeSchema = recursive(
  pipe(object({ value: string(), children: array(Recur) }), readonly())
);
const input = { value: 'a', children: [{ value: 'b', children: [] }] };
expect(parse(TreeSchema, input)).toStrictEqual(input);
```

这个 input 确实到达递归 child，另有 placeholder identity 断言，所以不能归为“没执行递归层”。但 `readonly()` 不造成运行时 value 的可见变化，输出与输入相同。

step 139 “All 7 pass. Now ... compile-time type inference checks”。step 140 的 `.test-d.ts` 已实际构造：

```ts
object({
  value: pipe(string(), transform((input) => input.length)),
  children: array(Recur),
})
```

并用 `expectTypeOf<InferOutput<...>>()` 验证输出 `value:number`。step 142 修 `minLength` 不适于 object 后，类型测试通过。step 143 “async variant tests, mirroring these”：step 144 async runtime 仍 readonly+输出等于输入；step 145 async type test 再次包含 length transform，仍无 parse+concrete-value 观察。

**验证演化。** step 135–138 runtime 初始失败来自 wrapper `.wrapped` 访问和 Set 数据形状；agent修了测试访问并得到 7 passed。这是合理修测试，不是删除 target 失败，因为 target transform 当时不在 runtime test。后续大量 step 159–250 围绕 TS 递归深度/type identity，最终 step 253 `2905 runtime tests pass`。step 281 再做多独立 schema、嵌套 schema、deep invalid input；step 295/301 跑文档例子，仍以 unchanged input 作为预期。step 363 最后相关 44 runtime tests pass。

**事后解释及限度。** 最强支持的是“非恒等 transform + recursion 的组合 schema 已经生成，却只由类型层观察”；不是没有想起组合，也不是完全没有 runtime recursion coverage。P7 没有 reasoning_content，不能进一步说 agent 有意偏好 identity 来让测试更容易通过。

**算法启发。** 发现两个测试使用相同 schema constructor path，却分别只观察类型和 identity runtime output；将 type-only schema 实体接入 runtime parse 的输入/断言骨架，生成一个 child 到达 transform 且 `f(v) != v` 的区分值。可从 transform AST `input.length` 直接算具体结果；LLM 仅在表达式语义不可直接解释时补局部预期。这个搜索比“任意两测试组合”窄得多，也更能利用现有证据。

## 对单一解释的反例与研究约束

1. **“agent 从不组合”不成立。** P1 有相位+text+alternate，P5/P6 多种真实跨边界组合且抓住 bug，P7 type-level组合已在源代码。
2. **“只要保证共享对象即可”不成立。** P6 缺的是新 alias shape；P7 对象与递归深度已正确，还需非恒等值变化；P1 是 producer grammar family。
3. **“只要加强断言即可”不成立。** P2、P4 原 tests 的断言足够精确，但输入没有挑战例外/表示边界；P5/P6则缺目标对象图/操作链。
4. **“测试已经包含所有素材”不成立。** P4没有agent生成的 quoted path witness；P6没有双闭包共享cell的构造。算法需允许从code/issue产生最小新结构。
5. **“所有 wrong expectations 都来自模型迎合实现”不成立。** P6 step69明确查语言语义，out-of-bounds不应报错；这是有依据的 oracle 修正。
6. **“已见17例可证明泛化”不成立。** 本文件是事后解释。依此制定的生成规则必须在新任务与控制样例中冻结验证，不能把17例的语义标签当算法输入。

## 两个可推进、但尚未证明创新性的算法切口

### A. 用“上下文的可替换性”产生搜索空间，不用关系标签产生搜索空间

借用程序语义的 contextual equivalence/congruence 和 typed term/context 构造思想。已有test只证明一个表达式在特定观察上下文内满足性质；我们有意寻找一个**可从代码枚举的最小上下文**，让原本看似等价的两条生产/传输路径变得可区分。

可落地的生成单位是带类型与效果边界的程序洞 `C[□]`，而不是自然语言 `ρ`。抽取现有test的 producer、access/call suffix、观察；沿 API/AST 明确存在的返回、容器、wrapper、serialization/decode 边界作一层 context extension，然后以到达观察的def-use路径裁剪。P5可产生`Call→map→member→Call`；P7可将已有type-only transformer schema接入runtime parse；P4可得到Path经command string的适配边界。每次extension都须给具体rewrite、类型/definite-assignment条件和oracle来源。

这种表示的收益是**算法可以直接枚举并比较构造代价**，但还远不足以统一17例：P1协议grammar需额外前端，P6共享heap需生成新alias shape。仅说“用类型匹配拼接”仍是已有研究常用技术，论文贡献必须来自我们定义的最小判别上下文及其搜索/裁剪机制，经对照验证，不可重新命名就称创新。

### B. 从“两个实现本来在该测试下观察等价”出发，生成判别实验

借用 mutation testing 的 RIP/传播条件、distinguishing tests 的思想，但不要泛泛造任意mutant。把 agent 已作、尚未被验证区分的**局部语义选择**当作竞争假设：P2 shortcut是否允许text例外；P5 containers是否只在Get路径绑定；P6clone是否保持内部alias；P7wrapper是否保留runtime transform。

具体搜索目标不再是“执行过两个因素”，而是寻找让两个局部选择在同一个现有观察位置产生不同结果的最小输入/上下文。P7选择非恒等transform和child输入就是可求值的区分约束；P6生成shared writer-reader topology；P2给text非空；P1到另一编码branch。可以用双执行/有界符号执行计算差异传播，失败时区分未触发、触发但未到观察、到了但断言没区分；这为反馈搜索提供真实梯度。

**必须解决的难点。** 若候选程序已经就是错误简化版本，不能只对它再做同一简化mutation，否则mutant等价、没有反馈；要从 issue+已有片段形成有依据的竞争语义或测试层干预。少量LLM可以提出局部竞争选择及契约依据，但不能任意“更正确实现”。怎样机械构造可信的竞争假设、避免退回按pilot写patch，是这一切口真正未解的核心，不应藏进 `derive_hypothesis()` 伪代码。若这点做不到，应缩小为可机械产生假设的一类边界问题，而非声称统一算法。

这两条是研究候选，不是本轮已有结果。尤其第二条并不意味着“用mutant输出当oracle”：区分能力只负责找输入和观察，正确期望仍必须由独立规格/已有有效断言/可解释表达式支持。

## 原始源 SHA-256

- P1 trajectory `5a9a15daafec9f38ffa87f145e48ad1b5e476894d557765eee4a4a77491e508b`；issue `2f76894c4bb887b9adf64b64a38521265fcfea812ff9155a44dc118f4919a35f`。
- P2 trajectory `2fd46afc16c8bd2dcd8809f2203ca9aad92941ae17a910f1e13119195ad185aa`；issue `154028ab23733b34eec0900ec11f480c2dec52c838655cd5b1e03d35785c5f2a`。
- P3 trajectory `fa570ab9d0a66d42382527b2da630341c441bfd66fd41a20767bf7fa13408fb6`；issue `2f76894c4bb887b9adf64b64a38521265fcfea812ff9155a44dc118f4919a35f`。
- P4 trajectory `e09ea7d783a82e53c615fa6f22b6b3d30795418c45fd50a048bdbc98bc9675c1`；issue `a9391445198a6a75372c1413a52f7c97ae4f5d5fead8bf45903792a69ccd5c2e`。
- P5 trajectory `8a1db3f967d1169eb2b3234182373ad5b53d5918b37d34de92f552cfc064fe9a`；issue `7c0bb4cf325fe7a3bc80a94f1c5d29fd3bb54d7749e2e5cfe430482fa9446ca6`。
- P6 trajectory `006769e2e288b14f9b9122a101cc6b26ed37499646a09d528401cb7d8f5e63da`；issue `224aed6e3cd8b8b4ee4ccf8bccd8b855c8dd1669131eec6280672a89457d40cb`。
- P7 trajectory `f821e5379cb262dfba0f2073bbe5e6c7eda2c332377153e2428a17271ada9ca3`；issue `a6e91d4261d1ab9774238d4bedb67dcb022a03bcbd8a53a3fe69e46dc22c787d`。
