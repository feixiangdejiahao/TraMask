> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/anchor_applicability_audit.md) · [旧路径映射](../../../results/path_map.tsv)

**如何检索测试 A，以及七个 pilot 是否支持现有方法**

本轮结论：可以设计确定性的断言检索算法来寻找 A，但现有材料不支持“七个 pilot 都能通过已有关系残差和供体替换自动解决”。P2 最接近；P3 还需要位级输入组合；P1/P4/P5 分别暴露语法、表示转换和跨语言构造问题；P6/P7 缺少能够直接继承的目标 oracle。不能把事后写出的关系公式当成已经存在的关系测试。

本轮只阅读本地候选代码、测试、patch 和 trajectory，并做 AST 清点；没有运行被测代码、replay、生成实验或外部模型调用。以下检索算法是设计，逐例结论是人工适用性审查，不是自动方法的成功率。

**1. A 的单位应是断言及其上下文**

不要求先从数千个 validation tests 中猜中一个完整测试函数。A 定义为一个已有断言，以及使它可执行的 setup、调用和必要状态操作。一个长 test 可以提供多个 A；多个重复 test 可以提供同一个 A。

检索依据是断言观察的生产代码对象，例如 `XTermParser` 产出的 `Key.character`。同样写着 `event.character` 不够：必须区分直接构造 `Key` 和通过 parser 得到 `Key`，并解析 helper、fixture 和访问路径。检索对象用代码位置和绑定表示，不让 LLM 给测试起语义标签。

**第一步：建立断言索引，先清除无关候选。**

纳入仓库测试和 trajectory 中的临时脚本、参数化输入、assertion helper。只打印结果的验证可以提供输入 B，但不能直接提供可执行 oracle A。重复执行同一测试不重复分析；保留参数行、输入常量和代码版本，不能把历史通过当成最终版本通过。

先用 AST 和调用索引做便宜的候选定位，再按需解析符号、调用及字段依赖。断言若观察的是补丁编辑器读取的源码字符串，不能归为被测行为断言。例如 P2 trajectory step 51、71、108 的 `assert anchor in content` / `assert old in content` 用来保护字符串替换，不是在检验 parser。现有 [extract_tests.py](../../../scripts/extract_tests.py) 会把这类脚本收进列表；它目前只是语法提取器和关键词排序器，不是此处提出的依赖分析实现。

索引形式只需：

```text
生产端观察位置 q → 观察 q 的断言及其测试上下文
输入定义位置 z   → 各测试为 z 提供的构造与取值
```

**第二步：从 patch 的影响范围检索断言。**

设生产代码改动为 Δ，`BS(a)` 为断言 a 的跨过程反向切片，包含数据依赖、控制依赖和必要状态依赖。优先检索：

\[
\mathcal A_\Delta=\{a\mid BS(a)\cap\Delta\ne\varnothing\}.
\]

实现时不必先为全部断言各建一张图：从 Δ 的调用范围及可影响的观察位置查倒排索引，对命中的位置共享切片结果，再回到具体断言上下文。生产端改动很大时，候选也会变多；分析不出调用或别名的候选应保留为未解析，不能据此认定没有组合。

**第三步：优先处理“断言只检查了一种依赖取值”的 A。**

在命中的断言上下文中，找到能够影响其观察值的输入位置 z。若该上下文始终把 z 设为空值/默认值，而其他测试给同一位置提供过另一取值，则优先选它。例如：shortcut 的 `character is None` 只在 associated text 为空时检查过，而另一测试提供了非空 associated text。

若以 C 表示同一入口、断言和相关上下文的测试组，可以写成一个简单检索条件：

\[
z\in Inputs(BS(a)),\qquad Values_T(z)\setminus Values_C(z)\ne\varnothing.
\]

这里的取值差只是“值得检查”的信号，不证明 oracle 可迁移，也不证明组合缺失；已有其他断言可能已经覆盖该组合。同一断言文本处在不同语义条件下不能合并，例如 shortcut 的 `character is None` 与功能键的 `character is None`。

输入位置必须来自程序绑定。P2 的原始 API 参数是一个字符串，要通过正则捕获组识别 `text_codes`；不能把整串字符串当一个不可分的常量，也不能仅按字符串相似度拼接。P3 则需要把解码后的 modifier 位拆开。两者是明确的分析需求，不是已完成的通用字符串理解。

**第四步：按观察位置轮流取代表，再判断能否复用 oracle。**

对相同入口、观察位置、归一化断言和相关上下文的重复候选共享分析，保留不同输入行及其来源。优先检查有未变化依赖位置的候选，再按所需构造改动大小排序；各观察位置轮流分配预算，避免大量相似断言挤掉其他字段。返回一小批 A，不声称无需搜索就能唯一选中目标 A。

```text
RetrieveAnchors(P, patch, tests):
    index = IndexAssertionsAndInputBindings(tests)
    observations = AffectedObservations(P, patch)
    for q in observations:
        slice = OnDemandBackwardSlice(P, q)
        candidates = ResolveContexts(index[q], slice)
        yield RepresentativesPrioritizingUnvariedInputs(candidates)
```

节省的是重复阅读、重复切片和任意 test-pair 的笛卡尔积。AST 扫描可按源码规模进行；精确调用、别名及切片分析没有因此变成线性时间，也没有普遍的候选规模上界。后续应测量有用 A 的 Recall@k、候选数、索引成本及查询成本，而不是本轮宣称加速倍数。

**2. 用 P2 说明 A 如何被检索出来**

本地 Python AST 清点得到：`repository/tests` 有 409 个 Python 文件、2,047 个 `test_` 函数定义；`test_xterm_parser.py` 有 30 个这样的函数、104 处函数内 `assert`，其中 6 处直接读取 `.character`。参数化没有展开，未计入 trajectory，也没有执行测试。这是语法清点，不能冒充完整检索算法的消融结果。

patch 修改 parser 的 `Key` 构造以及相关字段，算法应检索所有受影响字段；以下只展开 `character` 这一组，**不是预先把目标字段告诉算法**。

| 阶段 | P2 中的具体对象 |
|---|---|
| 找生产端观察 | parser 输出的 `Key.character` |
| 查断言索引 | 包括 shift-only、alternate、shortcut、text-only、legacy 等上下文 |
| 找 A | [test_xterm_parser.py:440](../../../data/cases/P2/repository/tests/test_xterm_parser.py#L440)，`assert event.character is None` |
| 找输入依赖 | [parser:466](../../../data/cases/P2/repository/src/textual/_xterm_parser.py#L466) 解码 text；[parser:552](../../../data/cases/P2/repository/src/textual/_xterm_parser.py#L552) 在 shortcut 分支传入 `text or None` |
| 查供体索引 | [test_xterm_parser.py:451](../../../data/cases/P2/repository/tests/test_xterm_parser.py#L451) 为同一 `text_codes` 捕获组提供 `97` |
| 形成待验证组合 | 保留 A 的 key/modifiers，只迁入 `text_codes=97` |

人工推导的组合为：

```python
# A: "\x1b[65;4u"       → character is None
# B: "\x1b[0;;97u"      → 提供非空 text_codes
(event,) = _keys(parser, "\x1b[65;4;97u")
assert event.character is None
```

`None` 的可复用性来自 [issue](../../../data/cases/P2/issue.md) 对 non-shift modified printable shortcut 的要求；不能由两个样本自动推出。也不能冻结 A 的整条已执行路径：若把“text 为空”的历史分支条件当作不可改变的前置条件，恰好会禁止这个组合。用于定位 A 的上下文与 oracle 的语义适用条件需要区分。

这里普通断言切片已经足够解释选哪个字段、哪个供体。把断言改写成残差 `[character != None]` 不会凭空增加信息；没有证明配对消去优于普通切片。

**3. 七个 pilot 的逐例审查**

分别检查三件事：是否有现成 A；源码能否给出组合候选的依赖证据；保留 A 的 oracle 并迁移现有输入是否足够。下面的“可复用”均以 issue 支持该适用范围为前提，不是从通过样本证明全称规律。

| Case | 实际已有 A / 观察 | 程序依赖证据 | 关系残差与供体重组的适用性 |
|---|---|---|---|
| P1 特殊键 × phase | parser 的 `event.phase == phase` 参数化断言 | 两种解析分支汇入 `Key.phase`，但扩展分支没有传入 phase，语法也不接收相应 event type | 可以定位相关观察；仅沿已有数据依赖和已有语法，不能恢复漏掉的传播和合法新编码。不是已经闭合的生成实例 |
| P2 shortcut × text | shortcut 的 `character is None` | text 捕获组→解码→shortcut 的 `Key.character` | 最直接；断言可按 issue 复用。普通切片足够，未体现关系配对消去的必要性 |
| P3 alternate × shift 位 | `"ctrl+plus" in event.aliases` | modifier 解码位、shifted_key 共同进入 alias 拼接 | 可沿依赖定位；还需组合 modifier 的位。整型供体原样替换不足以得到所需输入，普通断言切片仍是主要工具 |
| P4 magic × quoted path | status path 与 `bundle.exists()` | magic→参数解析→tokenizer→启动 API→路径/文件 | 路径断言可以复用；引用表示需转换依据。已有测试并没有直接编码 magic/API 的普遍等价关系 |
| P5 Go Call × compound return | 外部返回 closure 的调用结果；另一段读取 nested holder | Go 调用入口→VM frame→guest 返回值→容器 callable | 有候选联系，但需改写 guest 工厂、返回结构及观察路径。不是只替换既有参数、保留全部断言即可完成 |
| P6 clone × shared capture | 现成 clone 断言主要检查源与副本隔离 | closure capture、`ObjectPtr`、clone 的复制映射 | 当前 A 不观察副本内部共享；需新的共享堆结构和 write→read 断言。固定 oracle 的供体重组前提不满足 |
| P7 recursive × pipe | 组合已经存在，运行时断言是 `parse(...) == input` | schema 属性覆盖、`~run` 函数值、闭包捕获 | readonly 为运行时恒等操作；换输入无法观察它是否被跳过。换成非恒等 action 后旧 oracle 又不成立。当前算法前提不满足 |

**P1：缺少的依赖不能只向现有依赖图索取。**

[phase 测试:432](../../../data/cases/P1/repository/tests/test_xterm_parser.py#L432) 给出三种 phase 的对应期望，测试输入都是 `...u`。候选的 [Kitty 正则:40](../../../data/cases/P1/repository/src/textual/_xterm_parser.py#L40) 接受 event type 但以 `u` 结尾；[extended 正则:46](../../../data/cases/P1/repository/src/textual/_xterm_parser.py#L46) 接受另一组结尾，却没有 event type 字段；[extended 分支:525](../../../data/cases/P1/repository/src/textual/_xterm_parser.py#L525) 构造 Key 时也没有 phase。

控制依赖和共同观察能把这些代码放进候选范围，但原型若要求“供体新增因素必须已经通过数据流影响目标字段”，就可能排除这种漏实现。另一方面，直接按候选正则生成输入会继承候选的语法遗漏。需要独立的协议语法依据；不能说残差求解已自动解决它。还应选择 parser 的 phase 断言，不能仅因字段相同就用直接构造 Key 的默认值断言替代。

**P3：取值的内部结构决定供体能否组合。**

[alternate test:457](../../../data/cases/P3/repository/tests/test_xterm_parser.py#L457) 使用 `61:43;5u`，检查 `ctrl+plus`；[shift test:422](../../../data/cases/P3/repository/tests/test_xterm_parser.py#L422) 有 shift 位。候选 [events.py:323](../../../data/cases/P3/repository/src/textual/events.py#L323) 拼接全部 modifiers 和 shifted key。

编码 5 表示 ctrl，6 表示 ctrl+shift，2 表示 shift。在本轮对 `tests` 及 trajectory 工具命令的字面搜索中，没有找到 `;6u` 一类现成供体；这个有限搜索不排除动态构造出的 6。若原算法只允许替换完整 `modifier_code`，不能宣称已有供体必然提供 6。按程序中的 `int(code)-1` 和按位测试拆解后，可以组合 ctrl 与 shift，再编码成 `1 + ((5-1) | (2-1)) = 6`。这要求位级输入建模。选择原来的 alias 成员断言作 A；原测试中其他字段断言是否仍适用必须分别判断。

**P4：找得到 B 不等于可无条件搬入。**

[session-bundle test:73](../../../data/cases/P4/repository/tests/test_sessionbundle.py#L73) 使用简单路径并观察 status 和实际文件。更广的开发者测试中确实有 quoted-path 供体：[test_magic.py:1391](../../../data/cases/P4/repository/tests/test_magic.py#L1391) 把含空格的文件名加双引号传给 `%%file`。这是比仅查看新增测试更完整的检索结果，但两个 magic 的处理契约不因此相同。

[parse_argstring:164](../../../data/cases/P4/repository/IPython/core/magic_arguments.py#L164) 调用 [arg_split:188](../../../data/cases/P4/repository/IPython/utils/_process_common.py#L188)；后者的保留引号行为还被 [test_process.py:74](../../../data/cases/P4/repository/tests/test_process.py#L74) 明确检查。于是 tokenizer 的 oracle 不能直接搬成领域路径的 oracle。应保留 A 对实际 path 的观察，改变命令中的引用表示，并确认目标 magic 的引用契约。可以事后设计 direct/magic 等价测试，但原有两份独立测试不自动构成这条 MR。

**P5：同一个 test 中包含两种行为，也可能没有经过同一条值流。**

[callable_test.go:24](../../../data/cases/P5/repository/callable_test.go#L24) 在 Go 端调用 `make`，获得单个 closure；nested holder 则在 guest 顶层预先构造。让 compound holder 从 Go `.Call()` 返回，需要改 guest 工厂并改变返回值的读取路径。19 和 20 等 expected 也带有初值和先前调用历史，不能复制数字而忽略状态。

[root frame:137](../../../data/cases/P5/repository/vm.go#L137) 与 [内部调用 frame:746](../../../data/cases/P5/repository/vm.go#L746) 的槽位初始化差异给出静态审查线索。分析必须进入 Go 字符串里的 Tengo 程序，理解局部变量、返回形状和调用后观察。Go/VM 的两入口关系可以成为另一个设计，但不是已经从这些测试自动提取出的可执行关系。本轮不据静态差异宣布缺陷已确认。

**P6：外部隔离不蕴含内部共享。**

[CloneIsolation:197](../../../data/cases/P6/repository/gocall_test.go#L197) 观察 clone 修改自己的 global counter 而源不变。trajectory 的额外 StatePersistence 测试也主要读写 global accumulator；所审阅材料没有建立一份可直接迁入的“两闭包共享一个可变局部 cell 并交叉读写”的供体。这里不宣称穷尽证明整个仓库绝不存在这种测试。

[Clone:300](../../../data/cases/P6/repository/script.go#L300) 对各 global 做 transfer；[transfer:203](../../../data/cases/P6/repository/call.go#L203) 新建 seen map，而每个 closure 的 free slot 在 [223 行](../../../data/cases/P6/repository/call.go#L223) 新建 ObjectPtr。这些代码支持检查复制时的共享关系，但普通变量 def-use 不足，需要 capture/alias 分析。

目标观察是“通过副本 f′ 写，副本 g′ 能读到，同时源 g 不变”。原先“源不变”的断言即使始终成立，内部共享仍可能被破坏。因此找到原 clone A 只是入口，必须新增观察和相应堆结构。把新测试人工写成 clone/source 的关系，并不补上关系自动获取的缺口。

**P7：找到正确的 A，也未必已有可继承的检测能力。**

[recursive test:71](../../../data/cases/P7/repository/library/src/methods/recursive/recursive.test.ts#L71) 已组合 recursive、pipe、readonly。[readonly:42](../../../data/cases/P7/repository/library/src/actions/readonly/readonly.ts#L42) 直接返回 dataset；只改变合法树的值或深度，不能用输出相等区分 readonly 执行和未执行。这不表示该测试对所有其他错误的残差恒为零，只表示它对目标遗漏没有区分力。

仓库有 [非恒等 transform 的运行时测试](../../../data/cases/P7/repository/library/src/actions/transform/transform.test.ts#L18)，但迁入这种 action 后，正确程序也可能违反旧的 `output == input`。必须建立与 action 语义及递归层次一致的新 oracle。另一个 [recursive 类型测试:65](../../../data/cases/P7/repository/library/src/methods/recursive/recursive.test-d.ts#L65) 不能替代运行时 oracle。

依赖也不能只看 `.pipe` 属性：[resolve:63](../../../data/cases/P7/repository/library/src/methods/recursive/_resolveRecur.ts#L63) 复制首项属性，[117 行](../../../data/cases/P7/repository/library/src/methods/recursive/_resolveRecur.ts#L117) 合并覆盖；[pipe:2701](../../../data/cases/P7/repository/library/src/methods/pipe/pipe.ts#L2701) 的执行方法捕获的是闭包变量 `pipe`。这里需要函数值与闭包捕获分析，而不是两个测试调用了同名方法便建立一条边。

**4. 对 method design 的修正**

“两个测试之间存在依赖”应改为更精确的说法：两个测试提供的输入或构造，能否在被测程序中影响同一个观察，或形成有语义意义的状态/表示关系。独立运行的测试本身通常没有数据依赖；只共享调用名太宽，要求实际直接 def-use 又可能漏掉 P1 这种应有依赖尚未实现的情况。

对任意断言定义 `D = not(assertion)` 在形式上总能做到。真正有用的条件是：目标观察已存在、关系的适用范围有根据、供体构造可迁移、依赖模型覆盖相关语义，而且残差确实能减少搜索。当前七例没有共同证明这些条件，更没有证明配对消去是必需贡献。

因此保留“按改动和观察位置检索 A”作为明确的自动化设计；以普通断言切片和输入重组作为可比较的基线。关系残差暂时只是一项针对已有双执行关系的优化假设。P6/P7 应明确作为当前固定 oracle 方法的边界，不能靠在解释中补写新关系后计入适用成功。下一步选择研究核心时，应在“复用已有 oracle 的组合”与“需要新增观察/oracle 的组合”之间明确研究范围，而不是再增加一套覆盖所有情况的 schema。
