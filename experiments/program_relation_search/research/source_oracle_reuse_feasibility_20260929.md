# 原测试的 expected 能否减少组合测试的模型推理

结论：**可以自动提供精确到观察的 source anchor；可以对有限的同观察前缀情形机械提出 expected；不能仅凭相同 callee、实参和 projection 自动认定新组合的 expected。**现有代码已经实现了大部分所需基础，不宜再建立一套测试合成流程。

这次只读了源码与既有通用 toy，新增了 5 个通用边界测试；没有读取目标标签、隐藏测试、参考 patch、Oracle 回答缓存或新运行结果。

## 已有能力及实际含义

| 已有实现 | 可以复用的部分 | 不能据此推出的结论 |
| --- | --- | --- |
| `generic_composition/corpus.py:expected_atoms` | 将字面量 expected 容器分成带 projection 的原源码片段 | 不是实际对象字段语义的证明；未知对象可能重载 equality 或 getitem |
| `experimental/semantic_transport/proposals.py:_expected` | 取出明确 expected、受限局部绑定及模板字面量，记录来源 | 未知调用生成的 expected 不能被无条件化简；参数行或绑定变化仍需检查 |
| `experimental/semantic_transport/source_witnesses.py:attach` | 同作用域，完整测试前缀含 setup、参数、decorator；只挖 input 和 whole-expected 洞后做 AST 精确匹配 | 它验证有限源例子约束，不证明新输入的关系；当前不支持 projection 和 helper oracle conversion |
| `experimental/oracle_symbolic/core.py` | 对已知 builtin 值做受限线性上下文代入，机械算出 expected | 单独给相同 API 观测增加 `+1` 等包装通常不增加缺陷检出；不会推出新 API 输入的行为 |
| `experimental/generic_v3/alignment.py` | 源 statement 的唯一序列对齐、保留额外操作、绑定标签运输 | 不证明额外操作不影响观察，也不证明 expected 适用于新状态 |
| `relation_search/oracle_evidence.py:_control_tests` | 同解析 callee、匹配修改后实参的来源测试检索 | 当前只需某个修改实参相同，其他参数仍可能不同；角色是 source evidence，不能直接搬 expected |

## 最简单的可计算抽象：一个观察的支持前缀

把一个观察看成：**在这些初始化、对象绑定与操作已经发生后，检查这个 projection。**要复用源 expected，比较候选和 donor 到该观察为止的程序前缀，而不是只比较调用名字或 expected 字面量。

存在两种不同的问题：

1. **已有点的复用**：候选经过修改后，这个观察的输入、绑定、操作前缀和 projection 恰好对应某条 donor 观察。直接给出 donor 的 expected 作为来源明确的提案，不需要模型重新猜那个点的结果。
2. **新点的外推**：只知道其他输入或其他状态的源观察，想推导新组合的 expected。完整 frame 的相似性仍不能替代语义推理。

现有 `source_witnesses` 属于第二种的有限一致性检查。下一步最小扩展应复用其 frame 规范化，增加**候选修改后的观察 frame 对 donor frame 的直接查表**，不再拟合一条跨输入关系。初版用同作用域、直线观察前缀和完整 expected 槽；再逐步接入可证明不影响观察的纯局部语句消除与局部变量重命名。未知 heap/callback/控制流不靠缺失依赖来证明等价。

可以用这样的通用例子理解局部收益：

```python
# donor 的已有直接观察
box = Counter()
box.step(3)
assert box.read() == 3

# 一个组合候选：从 donor 借来 step(3)，保留原来的第二次操作
box = Counter()
box.step(3)
assert box.read() == 1  # 第一个前缀与 donor 对齐，可机械提出 3
box.step(2)
assert box.read() == 3  # 增加了第二次操作，不能从前面的 anchor 直接搬值
```

对第一个观察，程序可以提供精确 expected 来源；第二个观察仍是需要解释的新状态。模型只需要处理剩下的观察及其交互，完整测试继续随请求保留。若某候选的所有相关观察都有同前缀 source anchor，可以先产生无需模型的源 expected 提案；如果使用它来跳过模型，需要明确这是继承源测试的判断，不是证明源测试绝对正确。

这里暂未新建自动 expected 搬运流水。已有 frame 实现在 `attach` 的局部函数内；合理实现路径是将它抽成共享原语，再增加点到点查询，而不是复制另一份 AST 模式系统。

## 通用边界实验

新增 `tests/test_source_oracle_transport_boundaries.py`，与原 source-witness、symbolic-oracle、analogy-review 测试合计 **36 passed**。

1. **有限 frame 样例不决定新点。** 构造 `render("a;")="a;"`、`render("a!;")="a!;"`、`render("b;")="b;"`，但规定 `render("b!;")="SPECIAL"`。现有源 witness 可接受关系 `arg[0]` 为与源例子一致的提案，却给新点算出 `"b!;"`。三个源测试均成立，说明一致性检查不能升格为新点的 oracle 证明。该结果符合旧模块本身的 hypothesis 定位，不是其承诺失效。
2. **完整前缀相等也会过严。** donor 额外包含 `unused = 0` 时，现有 frame 不再对齐；实际观察未受影响。这给出进一步做受限纯语句消除的理由，但不是允许删除任意“看上去无关”的调用。
3. **expected 的容器语法不推出 projection 语义。** 真实对象可以满足 `result == {"count": 7}`，同时自定义 `result["count"]` 返回 99。`expected_atoms` 能提取 `count→7`，但不能独自把它变成有效的字段断言。
4. **相同 callee、显式实参、projection 仍可能不同。** 两个 Counter 的 `read()["count"]` 调用签名相同；一个对象发生过 `step()`，另一个没有，结果分别 1 和 0。同一个对象在不同观察阶段也不同。receiver history 和观察阶段必须保留。
5. **当前来源检索不是完整参数对齐。** 候选 `render("b", 0)` 可以检索到 donor `render("b", 1)`，因为修改实参 `"b"` 匹配。程序真实结果分别是 `"b0"`、`"b1"`。这支持继续把 donor 当上下文，但要求自动搬值时比较全部实参到形参的绑定，包括默认值，而非只看 donor 输入值。

## 为什么不能把“没找到依赖”当成免模型条件

候选 patch 本身可能有错，缺陷可能正是它遗漏了某个应有的数据或状态依赖。若用这个实现的依赖图断言“新操作不影响 projection，所以旧 expected 不变”，就可能把缺陷合理化。

程序依赖在这里有两个合适的用途：找出正向关联并缩小语义问题；为**已有源观察的执行上下文对齐**提供可检查证据。对于只有部分相似的新组合，留下未对齐部分让模型解释。还要注意，agent 写的原始测试也可能含错误 expected；精确搬运继承这个问题，因此 source anchor、source-consistent proposal 和正确 oracle 是三个不同的证据强度。

实际减少了多少模型请求、能否改善目标组合检出，需要在冻结候选上统计匹配率并做后续对照。这次没有测量这些收益，也没有把新规则写入正在运行的主实验。
