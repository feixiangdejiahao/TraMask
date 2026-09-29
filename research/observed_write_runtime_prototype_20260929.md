# 断言字段的实际写入来源：独立运行原型

本原型已经完成本地小程序验证，以及 N01/N02 首轮全部32组的真实仓库验证；尚未接入搜索主线。全部测试的执行结果与原未插桩版本一致。实现为 [`experimental/observed_write_runtime.py`](../experimental/observed_write_runtime.py)，插桩计划完全来自现有静态分析器，没有模型生成字段或人工 phase 标签。

对静态可绑定的断言读取 q，程序找到构造位置、接收者类、存储字段及直接赋值位置。AST 变换只做三件事：包装已解析的构造调用返回值，成功赋值之后记录写入，在原 assert 之前记录同一实例的存储值和最后一次观测到的写入。构造调用只执行一次；原 assert AST 不变。实例以弱引用及 `is` 区分，别名共享实例记录，不同实例互不借用写入证据。

真实 toy 得到了以下区别，q 和构造源码位置相同：

```text
正常路径：初始化写 False → 完成操作写 True → q 读 True；最后写入=完成操作
异常路径：初始化写 False → 操作抛异常     → q 读 False；最后写入=初始化
finally ：初始化写 False → 操作抛异常 → finally 写 True → q 读 True
```

运行记录包含 `(q 原源码 span, 实例 token, 构造 span, 最后观测的写入 span, 直接存储值)`。实例 token 只负责本进程内关联，不是跨运行的覆盖标识。原型不计算 assertion 的真假，也不改变期望；失败仍由原测试报告说明。

## 支持边界

只支持 Python 中已解析的局部直接构造、局部对象别名、同一类的单目标直接字段赋值及静态直接 property→storage 别名。断言限定为立即求值的简单字段、`not` 或单比较；可能短路或带调用的表达式不提前读取。`python -O` 删除断言时，观察也被删除。

取值只使用实际实例的原生 `__dict__` 描述符，不求值 property 或任意 getter，不调用对象的 `repr`、比较或转换方法。仅完整记录内建标量；复杂对象保持 unknown。非原生 `__dict__`、动态属性协议、未注册运行类型、不能弱引用的实例、缺少写入事件、未观测到绑定构造，以及存储值在上次事件后发生未记录变化，都保留 unknown。

**这里的 last writer 是插桩范围内最后观测的直接写入，不是开放 Python 世界的完整 reaching definition。** 相同值的未插桩写入无法被本原型发现；继承/动态替换、外部/native 修改、线程并发和源码反射不在保证内。AST 输出重新排版，真实 traceback 行号会变化，所有证据 span 与 SHA 指向变换前源码。不能因为两条 unknown 记录相似，就认为它们覆盖相同状态。

## 从复制的测试找回同一个源断言

生成测试中的行号不同，不能直接把两个行号当作不同观察。独立模块 [`experimental/emitted_q_origin.py`](../experimental/emitted_q_origin.py) 使用候选保存的字节修改区间、原源码和现有 emitter 的复制/重命名操作，重新构造实际 emitted 文件，并要求字节内容精确相同。只有能从未修改片段或整个 AST 节点替换的边界，准确映射到原 `Assert` 和构造 `Call` 的观察，才进入跨测试比较。它不通过自然语言、文本相似度或目标标签猜对应关系。

比较的键为：源 q 的 span 与源码 SHA、源构造位置与源码 SHA、解析出的类、断言字段和实际存储字段。原断言经过整体替换时单独记录 `source_assertion_edited`；新增且无法证明来源的断言不强行映射。写入位置也必须来自未变动的源文件。运行对象 token 只在本进程内匹配写入，跨测试通过源构造位置比较，不把对象地址当作跨运行身份。

[`scripts/prepare_observed_write_overlay.py`](../scripts/prepare_observed_write_overlay.py) 对传入 emitted artifacts 的全部已选择 control/source-profile/generated 测试统一枚举，不读取目标标签或执行结果。版本 v1 只准备插桩，v2 增加准确源映射。以下按独立 phase 内的断言实例累计，包含跨组重复控制，不是去重测试数或实际运行覆盖率：

| 输入 | 组数 | 选择测试实例 | 枚举 q | 静态可插桩 q | 有确定源映射的 q |
|---|---:|---:|---:|---:|---:|
| N01 | 14 | 200 | 521 | 153 | 144 |
| N02 | 18 | 245 | 710 | 198 | 198 |

N01 的9项不能证明 q 的修改来源，因此排除。所有未插桩及无法映射原因保存在每个 phase 的计划与映射审计中。160份 overlay Python 文件通过编译检查；86份修改的 subject/test 文件中的全部原 assert AST 与变换前文件相同。准备结果在 [`observed_write_overlay_v2`](../results/relation_search_20260929/observed_write_overlay_v2)，原 artifact 未被修改。

## 真实执行与全量比较

先按固定规则运行每例第一个同时包含 control/generated 共同 mapped q 的组，得到2组 smoke；它们没有测到新的可比写入来源，N02 只有复杂 headers 对象，保持 unknown。随后**另行冻结扩展 protocol**，按目录顺序运行全部32组，包括无 mapped q 的组，复用已完成的2组结果。每次仅1个新增容器，容器为2 CPU、8 GiB、network none，无模型请求。两阶段的选择和结果均保留，不能将扩展后的阳性结果写成初次 smoke 成功。

[`observed_write_full_v2`](../results/relation_search_20260929/observed_write_full_v2) 保存每组原未插桩执行副本、插桩执行的完整原生报告、源码快照/运输清单、trace 和逐 test 对照。全部32组、74个 phase 的通过/失败/错误/跳过数量及每个测试结果均保持不变。N02 原控制中已有2次失败，插桩后仍失败；这不等于所有控制都合格，后续搜索必须继续使用原控制资格规则。

[`scripts/audit_observed_write_full.py`](../scripts/audit_observed_write_full.py) 验证原执行封存的1,585份文件 SHA 后，对每组全部共同源 q 比较 control/generated，不使用目标、verdict 或测试结果筛选。结果封存在 [`observed_write_full_analysis_v2`](../results/relation_search_20260929/observed_write_full_analysis_v2)：

| 输入 | 有效 mapped read 事件 | unknown 事件 | 可比 group-q | 出现新 writer 的 group-q | 出现新值的 group-q |
|---|---:|---:|---:|---:|---:|
| N01 | 143 | 0 | 27 | 3 | 7 |
| N02 | 188 | 6 | 16 | 7 | 9 |

`group-q` 是组内同一源 q/构造/字段的比较，不是独立缺陷；不同组可能重复同一源 q。N01 新 writer 涉及2个不同源 q，N02 涉及6个，历史 `_rh` 文件保留各自身份，没有声称语义去重。静态 q 数与运行 read 事件数也不能直接相除作为覆盖率：参数化执行会重复观察，提前失败会跳过后续断言。

具体来说，N01 的两组在源 `tests/models/test_responses.py:941` 的 `is_closed` 断言上测到：control 最后写入是 `httpx/_models.py:1194`，值 True；generated 最后写入是初始化的 `:733`，值 False。同一组中另一个 `is_stream_consumed` 断言也出现完成写入与初始化写入的区别。N02 的7组在 `is_closed` 上测到相应区别：`httpx/_models.py:1005` 的 True 与初始化 `:554` 的 False。共73条 generated read 具有新 writer，另外6条只是 `status_code` 的值改变，writer 没变。所有79条新 writer/value 事件对应的原断言均未被编辑。

这证明原型能在真实仓库里观测到“组合让原断言看到另一个写入来源”。它没有证明新状态应当满足哪个断言，也没有证明所有新状态都是缺陷。`status_code` 的取值变化尤其说明，仅有新值不足以构成缺陷证据。6条 headers 观察不能无副作用地转成可比较标量，全部保持 unknown。每个比较都可沿 trace 文件 SHA、原始行号、完整事件与源码 span 回查。

独立复核结果见 [`observed_write_full_review_v2.json`](../results/relation_search_20260929/evaluation/observed_write_full_review_v2.json)：10/10个新 writer group-q、73/73条新 writer read 均有通过的同源 control；前述2个 N02 失败控制不属于这些观察。复核还检查了原断言 AST、源 SHA、同一对象的最后写入事件和原生测试状态。其余生成场景没有逐一作 oracle 正确性裁决，因此这个结果仍是写入机制证据。

相关运行和映射测试合计 **49 passed**：16项运行原型、7项准确映射、1项真实本地 pytest phase 集成、25项静态分析回归。覆盖异常跳过写入、finally、真实生成器异常、别名与不同实例、字段/变量/类型改名、property 只由原断言求值一次、RHS 抛错不伪造写入、无写入保持 unknown、弱引用不延长寿命、无法证明来源的复制断言排除，以及原 assert AST 保持不变。

## 将观察变成确定的算法状态

[`experimental/observed_write_frontier.py`](../experimental/observed_write_frontier.py) 只实现一个小的集合算法：有效 mapped read 被投影为 `(源 q, 源构造, 解析类/字段, 源 writer, 内建标量值)`，上述源码位置包含文件 SHA。首次出现的键加入集合，保留固定数量的最早测试代表；未知观察不登记。实例 token、候选 ID、执行顺序号和人工 phase 标签都不参与键。标量保留类型，True、1、1.0 不混同；有限浮点以十六进制表示，保留正负零；NaN、正负无穷和复杂对象保持未知。

固定源码快照中的 q、构造位置和 writer 位置集合有限，但当前值分区采用精确标量值，整数、字符串等取值域并不有限。因此只有给定执行预算下已经观察到的状态集合有限，不能把它称为有限抽象域。目前没有语义等价或有限域证明，状态数量增加也不能直接证明反馈更有效。

[`scripts/replay_observed_write_frontier.py`](../scripts/replay_observed_write_frontier.py) 对完整32组已有 trace 做离线回放：每例全部 control 先登记，随后按原 group 顺序和 JSONL 顺序登记 generated，每状态保留1个代表。代表通过实际 emitted 源码中包含 q 的唯一测试函数绑定，无未解析代表。新 frontier 不需要旧 source-profile 的阶段标签作为基线。

| 输入 | control 状态数 | generated 新增状态数 | 最终状态数 | 保留的 generated 测试代表 |
|---|---:|---:|---:|---:|
| N01 | 16 | 6 | 22 | 6 |
| N02 | 16 | 8 | 24 | 8 |

checkpoint 恢复后重放全部观察不改变状态；14项独立测试验证投影、类型区别、源码来源、未知值、代表上限和恢复幂等。加上前述49项，相关测试共63项通过。回放保留的是观测代表，不是已经满足 source-control 或 oracle 资格的搜索父节点。

同一脚本还单独检查旧 `relation_trace.jsonl`：保持旧 `canonical_profile` 不变，与仅移除它的 `phase` 字段的投影比较，旧 source-profile 先登记。N01 的2个 generated 新旧 profile 中1个仅因 phase 不同而新；N02 的12个中6个仅因 phase 不同而新。这个差异在同一批旧 trace 上成立，但新旧 logger 的观察范围不同，不能直接把两套状态数当成受控搜索消融。结果、逐事件代表和所有旧 profile 在 [`observed_write_frontier_v1`](../results/relation_search_20260929/observed_write_frontier_v1) 封存。

目前结果支持继续研究以确定源 q 和实际写入来源作为搜索反馈；尚未将其加入候选排序，尚未比较反馈是否节省搜索预算，也不能据此宣称17例缺陷检出率、误报或漏报已经改善。
