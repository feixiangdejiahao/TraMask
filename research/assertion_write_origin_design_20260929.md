# 从实际反例收缩核心：跟踪断言读取的状态由哪次写入产生

**现有 profile 在 N01、N02 上产生“新形状”，但记录的状态根本没有包含实际失败的字段。** 这不是猜测，两个实验都只记录 `response.is_stream_consumed=True`；原控制也记录同一个 True。新形状来自 `phase` 从 `source_observation` 改成 `after_expected_exception`。实际失败的是下一条断言读取的 `response.is_closed=False`，它没有进入 trace。

精确候选、原控制、trace、失败报告、源码片段和 SHA 在[证据附件](assertion_observation_projection_evidence_20260929.json)。N02 目标 `17b06f2b558956ac7c31eb80` 的原断言位于 `tests/test_multipart_response.py:116–117`；N01 目标 `c8e075c82686eb21c4222575` 对应 `tests/models/test_responses.py:940–941`。两者都为已独立审查的实际目标失败。不能由此声称此前 profile 完全没有帮助：它保留了这些候选，但没有辨识它们为何接近目标缺陷。

## 用 N02 推导一个可执行的抽象

我们关心的是“同一个 response，在异常被测试捕获之后，关闭状态来自哪里”，而不是任意位置上布尔值、列表长度和引号外形的新组合。

从断言 `q: assert response.is_closed is True` 反向分析得到两处有关的写入：`httpx/_models.py:554` 的构造器初始化 `is_closed=False`，以及 `close:1005` 的 `is_closed=True`。原正常测试沿 `iter_multipart:946` 到 `self.close():968`，再到 q；异常输入使 `yield from decoder.iter_parts():967` 异常退出，测试捕获异常后仍到 q，`close` 的 True 写入被绕过。`is_stream_consumed=True` 在 964 行已经执行，所以它不是关闭成功的替代观察。

可把搜索状态收缩为 **q、q 绑定的对象、q 读取的字段最后一次写入位置，以及 q 对该值的实际判断**。对象以测试中的构造位置及局部别名绑定；观察阶段就是实际 q 的执行点，不用构造器预先填写的 phase 标签代表已到达。初始化和关闭是两个有限写入位置，程序可以从 AST 找到，不要求模型填写自然语言关系。

```text
原测试：Response 构造写 False → 正常消费 → close 写 True → q(True)
组合后：Response 构造写 False → 异常消费 → 捕获异常       → q(False)
```

核心搜索操作是：**找一个现有上下文，使原来到达 q 的写入被替换、绕过或覆盖，同时让同一对象仍到达原 q。** 在 N02 中，另一个现有测试的 `pytest.raises(DecodingError)` 和 malformed bytes 提供异常上下文；已有输入构造器已经能搬运它们。新程序分析应优先选择与 `is_closed` 的 True 写入存在这条控制依赖的组合，而不是先枚举所有调用再靠宽泛形状选父节点。

最小算法可以写成三步：

1. 从每条断言的真实读取解析接收者类型和局部别名，反向找到同一字段的写入以及测试操作到写入的源码调用路径。只有字段名相同，不能认定为同一资源。
2. 在这条片段上查找现有 donor 能触发的控制出口；优先执行那些可能改变 q 的 reaching definition、且保留 q 可达性的已有候选。排序依据是源码证据和有限编辑数，不能用案例 ID 或已知失败标签。
3. 执行后在真实写入和真实断言读取处记录对象与写入位置，不额外调用 getter；只有 q 实际执行才登记覆盖。按 `(q, 对象绑定, 最后写入, 断言谓词结果)` 保留代表，避免仅 phase 名称不同就宣称看到了新的状态。

静态“可能改变”不是动态“已经改变”，最后一次写入不同也不等于 oracle 正确。已有 q 是否适用于异常场景仍要靠契约判断；本原型不生成新的期望，不把模型未判断或执行失败自动标成缺陷。

## N01 验证同一机制，也暴露最小分析边界

N01 初始化在 `httpx/_models.py:733`，`close` 写 True 在 1194，q 在测试 941 行。调用链的源码边是 `iter_json:1050 → iter_bytes:1121 → iter_raw:1183 → close`。但不能把这些生成器调用当作立即执行的普通调用：`iter_raw:1178` yield 后控制返回 JSON 消费者；`parse_line:220` 可以抛出 `DecodingError`，使生成器后面的 close 尚未执行，而测试已经到 q。

因此，最小静态原型必须明确区分**生成器创建、恢复执行、耗尽以及被消费者中止**。能找到源码调用路径，不代表已经证明其运行时完成；若没有迭代器绑定与恢复边的支持，应返回 `unknown`，最少需要一次原测试的调用/写入事件来连接实际的 iterator 与 response。用不精确的“call graph 中存在 close”代替完成性分析会重新漏掉本例。

## 它能解决什么，不能假装解决什么

这是一项可证伪的研究假设，不是已验证的创新结论。Reaching definitions、程序切片和对象绑定都是已有基本工具；可能的贡献是把它们用作**组合搜索的目标和转移准则**，并证明比一般输入外形更有用。

8 例消融已显示其适用边界：P1、P2、P3 没有实际 profile，不能把缺失记录当等价状态；P4 的记录主要位于序列化消费者之前，尚未与最终观察建立联系；N03 能记录输入别名和最后 moved 的长度，但不同阶段的快照没有表示二者间的生产关系；N04 的 profile 臂无测量，rotation 的额外三个形状也没有有效来源基准。新分析不会自动补齐这些跨进程、数据组合与别名语义。

P3 是必须保留的反例：Shift 与 Alt 两个构造变体都写同一个 `Key.aliases` 字段、在同一源码写入点结束，原 membership 断言却只有 Shift 场景适用。仅记录写入位置不足以区分这类数据构造语义；字段读写分析也不能证明两个 oracle 的适用性。这里需要另行验证断言相关值谓词的收益，不能直接把这个局部原型宣称为完整新算法。

最小可证伪实验应固定原有候选池、缓存与预算，仅比较基于 q 的写入路径优先级/反馈和当前策略。预期首先是 N01 的目标由当前第 26 个程序提案前移、N02 不再把 consumed 当作 closed；N02 已在第 3 个提案命中，本来就没有新增案例收益空间。若 N01 没有前移，或为了得到路径花费的分析与采样成本超过节省的执行，就应否定该局部收益。形状压缩的独立贡献还需要两臂共享相同的可测 q 和候选来源，不能再把“有无 trace”混进反馈消融。

本节依据冻结实验和源码只读分析写成；尚未实现/运行上述搜索，不报告新 Hit、精度或 issue resolution rate。

## 独立静态原型与实际输出

[experimental/assertion_write_origin.py](../experimental/assertion_write_origin.py) 实现了上述第一步的受限原型，未接入生产 pipeline。输入是现有 corpus 的源码、原测试路径与断言行号；输出全部由 AST 计算，包括 q 的原字节范围、构造位置、导入/局部别名解析后的类、字段写入位置、调用位置与控制上下文。它不导入或执行被分析仓库。

真实材料的结果为：

| 原断言 | 接收者类 | 直接字段 writers | 测试操作到 close 的源码路径 |
|---|---|---|---|
| N01 `test_responses.py:941` | `httpx._models.Response` | `__init__:733`、`__setstate__:1096`、`close:1194`、`aclose:1335` | `iter_json → iter_bytes → iter_raw → close` |
| N02 `test_multipart_response.py:117` | 同上 | `__init__:554`、`__setstate__:883`、`close:1005`、`aclose:1135` | `iter_multipart → close` |

所有 writers 是同一已解析类中的直接赋值；列出 `__setstate__` 或 `aclose` 不意味着当前测试能够调用到它们。输出将完整 writer 清单与当前测试操作的有限源码调用路径分开。N01/N02 具体结果分别见 [N01_static_v2.json](../results/relation_search_20260929/assertion_write_origin_v1/N01_static_v2.json)、[N02_static_v2.json](../results/relation_search_20260929/assertion_write_origin_v1/N02_static_v2.json)，旧 `static_v1` 是补充绑定阴性控制前的原型输出，保留用于追踪代码变化。

原型支持直接局部构造、已解析的 import/reexport、局部对象别名和 `@property` 直接返回另一字段的别名；同字段不同类、同类不同对象不会贡献对方的操作路径。构造器符号被参数/赋值/函数遮蔽、条件赋值、任意 factory、复杂 property、自定义 `__new__`/metaclass 等返回明确 unsupported；继承分派、外部修改、可能异常的可行性和实际最后写入仍保留 unknown。路径状态一律为 `syntactic_path_not_execution_proof`。

[25 项测试](../tests/test_assertion_write_origin.py)验证了源码改名、字段同名不同类、对象别名、导出/遮蔽、property、finally 保护、字节范围和两个真实 corpus。被分析源码里的顶层代码不会执行。测试与静态抽取只验证分析器的局部行为，**没有新增 trial 执行或检出**。N01 至少还需要为实际生成器记录创建/恢复/耗尽与该 response 的绑定；否则不能从找到调用路径推导 close 真正执行。

另用冻结 `frontier.py` 对附件中两例原始 trace 逐字段计算 `canonical_profile`，差异键均严格等于 `["phase"]`，这一复算也已写入证据附件。它精确支持开头的诊断，不依赖肉眼比较日志。
