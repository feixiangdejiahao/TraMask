# 单候选、联合观察的期望槽原型（2026-09-29）

这是独立实验模块，尚未接入生产搜索入口。它是**模型期望假设的输出运输和程序回填接口**，不是核心学术算法。程序分析的研究目标应是整理复杂程序信息、帮助模型推理，而非把强限制本身当方法贡献。此模块不负责发现组合、不证明组合适用，也不证明测试预期正确。

代码：[singleton_oracle_slots.py](../experimental/singleton_oracle_slots.py)。生产 `relation_search/oracle.py` 与原 fallback 基线保持不变。

## 粒度为什么是一个固定程序的全部相关断言

1. **不是整个 issue。** 程序已经决定了输入、调用、对象和顺序。模型每次只解释这一个完整组合测试，避免在多个候选之间串用输入或期望。issue 保留完整规格，只机械去除已知 runner 指令外壳。
2. **不能逐个断言孤立询问。** 同一测试可能先改变状态，再检查多个结果。单看最后的断言会漏掉前缀操作；分别生成期望又可能对同一对象、同一事件采用不一致的假设。因此一个请求包括完整修改后测试、全部前置操作、所有已有断言。无法证明无关的断言仍保留；接口不允许删掉它们。
3. **没有可编辑槽不应花模型名额。** 若程序根本不能把返回值填回已有断言，此时调用模型不会产生可执行的期望修订。资格过滤只调整 LLM 请求队列，原始程序候选继续存在；这不是把不支持的候选判定为正确或无缺陷。

## 只有一个小接口，程序拥有其余代码

程序先使用既有结构 guard 的 AST 规则找到可替换的 expected 表达式。模型只返回 `id → preserve/adapt/unknown`；`adapt` 多带一个代码表达式 `expected`，Python 必要时另给允许的 `comparison`。没有关系描述 schema，也没有自然语言理由参与排序。

例如 `assert obj.code == 0, obj.output` 的模型输出可以是 `{"id":"A0","status":"adapt","comparison":"!="}`。程序保留 `obj.code`、消息 `obj.output` 和测试其他代码，只改变允许的比较符；再运行原 guard。Go 原有 `int64(103)` 若可支持，只开放内部 `103`，转换调用和失败体不能被模型重写。TypeScript 支持的容器期望作为整个闭合表达式填回。

每个可编辑断言必须都有明确决定；缺项、空结果或任何 `unknown` 都不能被当成“保持原断言已经验证正确”。`preserve` 也是模型假设，不是证明。不可编辑断言放入只读背景；模型若认为它们必须修改，只能 `unknown`。

上下文从 corpus/frontend 机械提取：完整 test、input edits 的 before/after、导入绑定、显式 helper/fixture/donor、直接解析到的完整函数声明及一层被调函数声明。相同文件和字节区间去重。未解析调用及深度上限单独记录，动态状态闭包仍可能缺失；代码只能帮助理解绑定和字段，不能把有缺陷实现的输出当正确期望。

独立通用 toy 审查还确认：调用图来自原 frontend，若候选把 `original(1)` 改成 `alternate(1)`，两个冻结模型实验中的版本可能仍只附上 `original` 声明，即使两函数都在 corpus；`missing=[]` 也不代表新程序依赖完整。完整修改后测试确实提供了新调用，但 source context 不是修改后程序的重新解析闭包。这个限制不影响“源片段确实来自 corpus”的绑定证据，却限制了模型推理所需上下文的覆盖；两个冻结实验均保留该实现，不据结果修补上下文。

实验结束后的main最小修复只做可验证的语法判断：原callee表达式被编辑时，不再沿用它的旧调用解析；修改后test AST出现新callee时，明确记 `new_callee_unresolved`。receiver文本变化同样处理；只改实参字面值则保留旧callee声明。遇到覆盖整调用的大编辑会保守失效旧解析，不按名字猜新目标。原helper源码仍可作为原测试背景保留，不作为新调用已解析的证据。对象别名和动态接收者类型仍未解决。纯静态回查32父候选，12项出现新增/编辑callee提示、18个旧call解析失效；没有重新生成两个冻结实验的prompt。

完整请求超过 64,000 UTF-8 bytes 就记录 `unknown_context_budget`，不截断状态操作、不分拆再拼最有利答案。无法表达的断言结构直接记录 `unknown_no_editable_slot`。

## 冻结的同 32 父请求对照

基线：`results/relation_search_20260929/singleton_fallback_disabled_v2/`。

新原型：`results/relation_search_20260929/singleton_expected_slots_v3/`。

准备协议 SHA：`f6682876178e51eb28fc4a548211ad2da626ab1b7e47870766cd180ab585fd15`。

执行协议 SHA：`b0eafad4c98b964e07f32c6b65aa0a03e094b929d76113081b624544df92c200`。

只改变 prompt 接口与机械源码上下文；候选、输入、断言 ID 和 provider 参数均与原库存配对。模型为 `deepseek-v4-flash`，thinking disabled，temperature 0，max output 16,384，0 重试。2 并发、360 秒发起窗口，实际 19.94 秒完成 14 请求。

| 结果 | 数量 |
| --- | ---: |
| 原始父请求分母 | 32 |
| 无可编辑槽，未调用 | 15 |
| 完整上下文超预算，未调用 | 3 |
| 实际调用 / 严格 JSON | 14 / 14 |
| `adapt` 且原 guard 接受 | 1 |
| `preserve` | 11 |
| 模型返回 `unknown` | 2 |

三个超限请求分别为 66,867、70,313、70,199 bytes；它们既没有 exact-source 重复，也没有完全相同代码文本重复，因此没有为了使请求入选而删内容。

这 14 项中，旧请求总 bytes 中位数 7,499.5，新请求 19,517；新请求最大 35,485。实际输入 88,387 tokens，输出 523 tokens。所有14实际 wire payload 都与事先冻结的 payload 相同。

基线在全32项得到32个JSON、2个结构接受；独立审查已认定这两个新期望均错误。新原型的1个适配是 N05 index2。独立 evaluator 已连同只读断言和前置操作审完全部14项：**0个新的正确修订；1个适配错误；11个 preserve 的完整测试均不成立；2个 unknown。** 这不是测试执行后的缺陷检出率。

错误并没有靠小接口消失。N05 把旧 `want` 变量换成原来字符串的字面值，形式上是一次合法改写，语义上仍保留已过时的期望。P6 没有再提出基线错误的新值104，却保留了错误旧值103，仍未恢复需要的5004。N03 从错误新期望变成unknown，这是弃权，未生成正确期望。P1甚至丢失了基线raw response中曾推断正确、但被结构guard拒绝的四字段更新，改为错误preserve。因此不能声称本轮改善了完整oracle正确率，或把“更少新改动”直接解释成减少误报。

**这次同时改变了期望槽接口和 source context。配对实验可以评估这一整套变更，不能分别归因于返回粒度、上下文或某条 prompt 指令。** 32项还来自已经冻结的历史失败/解析困难库存，不是随机的17案例总体；结果不能直接估计总体提高率。

完整语义复核封存于 `results/relation_search_20260929/evaluation/singleton_expected_slots_review_v3.json`。本次没有执行新的测试程序，没有根据答案调prompt或补写案例期望，也没有用重试替换本轮结果。

## 冻结的 thinking 单因素对照

负面结果封存后，另作受控对照：`singleton_expected_slots_enabled_v1/` 完全复用上述14个请求的 system、prompt、源码和父候选。唯一 wire 差异为 thinking disabled→enabled；未指定 reasoning_effort，不增加输出预算。2并发、600秒发起窗口、0重试、上限14，未调用的18项继续留在32父分母。

执行协议 SHA 为 `59c6bd1952cca24d7671beb6b37ec0c02e71138f951c9b5c83cb5e1e68694ea4`。这是新冻结实验，不覆盖v3；不以标签或模型回复选择哪些请求进入对照。运行时使用后述input-overlap修复，其在14个v3回复上的验证结果已证实不变。输出和完整oracle正确性须分别报告，解析成功仍不代表语义成功。

独立复核已封存于 `results/relation_search_20260929/evaluation/singleton_expected_slots_enabled_review_v1.json`。结果如下，18个不支持/超限父项始终保留：

| 同14请求对照 | disabled | enabled |
| --- | ---: | ---: |
| 严格JSON | 14 | 10 |
| 结构接受的adapt | 1 | 5 |
| 完整oracle正确的adapt | 0 | 4 |
| 完整oracle错误的adapt | 1 | 1 |
| 完整假设错误的preserve | 11 | 5 |
| length终止且无可用JSON | 0 | 4 |
| 输出tokens（含推理） | 523 | 145,537 |
| 整批耗时 | 19.94秒 | 326.94秒 |

四条正确修订分别为N03缺省质量、P6共享状态的5004、P4两条保存/重载观察。它们覆盖三个案例，不是四个缺陷检出；其中P6的正确oracle之前已出现过，本次是恢复，并非新发现。P1新修订仍错误地保留 `character is None`。五条preserve中的完整测试仍有错误；独立审查将六条错误完整假设分为1条editable expected错误、2条固定程序本身无效、3条观察位置/结构不再适用。

这个严格配对表明，在这组请求上开启推理恢复了4条正确完整oracle，但付出了明显预算代价，并未带来可靠保证。4/14是已调用请求中的正确修订数，4/32是整个固定父库存中的正确修订数；都不是issue resolution rate。enabled的145,537输出tokens中145,195为provider报告的reasoning tokens；四条请求触及16,384上限而没有可用最终正文。没有提高预算或重试补齐它们。实际测试执行和缺陷证据另由主实验记录。

## 固定请求的 source context 消融

第三轮 `singleton_expected_slots_no_context_v1/` 直接读取上一轮14个冻结prompt，仅删除其中的 `source_context` 字段。system、完整modified test、input edits、imports、assertions、issue、thinking enabled及其他provider参数均保持；没有用修复后的frontend重新生成prompt。每条保存了删除字段和unified diff，协议 SHA 为 `306e5be978baee4c89fe75e8e0f668f4722d97eeede4a9462163e01b26294bab`。

独立复核见 `evaluation/singleton_expected_slots_no_context_review_v1.json`。有context时完整正确修订4/14，删除后1/14（整个父库存分别4/32、1/32）。无context的4条accepted中，N05正确；N03缺省值和P1完整比较错误；另一条N03虽然推断出计数3，却缺乏线程写入与子进程观测之间的同步前提，因此完整oracle未知。另有4条错误preserve、2条显式unknown、4条length无最终JSON。

有context的输入88,737 tokens、推理145,195 tokens；无context的输入降至28,348，但推理升至166,699。两者均有4次length终止，耗时分别326.94秒与385.68秒。此次结果说明源码上下文在这些固定请求上与更好的完整推理结果相伴，同时也有N05从有context的超预算转为无context的正确输出的反例。每个条件只采样一次，不能排除随机波动，也不能据此宣称普遍可靠。消融检验的是已解析声明及未知标记这整个字段，尚未检验下面新实现的依赖边renderer。

## 程序分析目前实际整理了什么

`singleton_dependency_fact_audit_v1/` 保存了无需模型、无需目标标签即可重现的原源码facts。原frontend有call位置、唯一可解析函数、receiver表达式及定义绑定、actual/formal参数映射，以及静态切片链接的assertion ID。因而可以机械展示原源码中的“这个call解析到哪段声明、哪个实参对应哪个形参、它落在哪些观察的静态切片内”，不需要先让模型生成一段自然语言关系。

在固定32父程序中，按候选计重复site，共1245个原call记录：454个有唯一源码target；681个带receiver表达式，其中653个有原binding记录；1141条actual/formal记录；10838条原静态slice call→q边。417个call同时有唯一target和q边，剔除callee语法已编辑的旧解析后为407。静态切片可能保守扩大依赖，source binding也不证明运行时对象同一，故这些数只表示facts可得性，不能当正确依赖数或modified程序覆盖率。

**当前prompt并没有把这些图边送给模型。** 它主要提供完整声明代码，让模型自己重新梳理call→q、actual/formal和receiver binding。修改后callee仍未重新解析；实参个数、receiver别名或动态状态变化也不能靠原绑定证明。实际下一步应研究如何把现有机械facts组织成对推理有用、且不混淆原程序与修改后程序的依赖证据，而不是扩大槽位限制或增加自然语言schema。本轮只做事实审计和受控上下文消融，没有赶制一个未经验证的新算法。

随后把已有facts整理成了独立的本地接口 [call_dependency_evidence.py](../experimental/call_dependency_evidence.py)，具体范围见 [接口说明](call_dependency_evidence_20260929.md)。它从候选涉及的原call及静态input use出发，列出关联q、actual/formal和receiver定义的源码位置与may边；不让模型先写一段关系schema。这个renderer尚未用于模型实验，也未接生产pipeline，不能把上面的4/14归因于它。

## 全候选池的资格过滤

`expected_slot_eligibility_v1/` 对17个固定 corpus 的4,502个程序候选，只用源码统计到2,315个至少有一个可编辑槽，2,187个没有。每例仍给16个名额，原队列272项里181项有槽；先做资格过滤后，272项都有槽，保留181项并替换91项。这只说明减少了无法回填的模型调用。

独立目标核对见 `results/relation_search_20260929/evaluation/expected_slot_eligibility_review_v1.json`：5个确需改变 expected 的目标 Hit@16 仍为3/5；N04 从第48到43、N05从170到129，仍超预算。全17参考 parent 的请求队列覆盖从9到6，有些原在队列中的目标变为无槽，不再查询模型；原程序没有删除，不能直接等同执行漏报，但也是明确的表示覆盖损失。

## 可靠性边界与验证

- AST/byte 槽限制保证的是“允许改哪里”。expected 是否应该改变、应该变成什么，仍是待检验的语义假设。
- 原 guard 只支持部分单比较/断言调用；比较符只能在已有 family 中转换，不能表达任意新关系、复杂连接条件或新观察。Python 的同 family 替换也不证明断言强度。
- Go helper 新摘要原型没有混进这次对照。`verify(t,o,expected)` 若旧 frontend 没暴露 expected，仍为只读/unknown。见 [Go helper 分析](go_assertion_helper_20260929.md)。
- 联合提供只读断言不能保证模型发现其过时；程序既不改它，也不证明它正确。必须审完整 oracle，不能只审改过的槽。
- 当前相关回归共162项通过，覆盖运输接口、原guard/oracle、冻结消融、callee上下文修复及新renderer。它们不是语义正确率实验；此提交后完整main测试集由主协调者统一补跑。root在实验完成后还独立修复了比较符表示边界；三个冻结实验的prompt、adapter和已接受代码均不回填修改。

独立代码审查还发现并修复了通用入口的一个一致性错误：输入编辑若与A0断言重叠，准备阶段把A0设为只读，旧adapter却会重新把它算成可编辑，误拒绝合法A1回复。现在准备和回填共用同一重叠判定，另加回归测试。修复发生在v3封存之后，未改封存快照或响应；纯本地审计确认原32请求的offered中0个此类重叠，14项回复在修复前后验证结果完全相同。证据：`singleton_expected_slots_postfreeze_fix_v1/audit.json`；新增模型调用0。

重现准备：`scripts/analyze_singleton_oracle_slots.py paired`。独立执行器：`scripts/run_singleton_expected_slots_diagnostic.py`。已有实验目录禁止静默重启；准备、请求、raw response、解析、回填验证、代码快照和预算均已留存。
