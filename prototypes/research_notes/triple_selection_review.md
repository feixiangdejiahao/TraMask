# 三元组选择与语句对齐的独立评审

本评审只依据生成器、corpus/def-use 实现及独立 toy；未读取 pilot 执行结果、reference 或目标标注。下面的排序建议尚未实现。新增回归为 `tests/test_generic_triple_review.py`，5 项通过；其中明确检验当前方法的限制，不是成功检测真实故障的证据。

## 当前筛选不是 core 的必要条件

核心需要三项语法重构和可解释的替换来源；同文件、同 scope、相同参数接口、三者共享 producer 都不是反统一的数学必要条件。

- 同文件/scope 是当前直接克隆完整测试时的一种绑定限制。它降低导入、fixture 和外部局部变量迁移成本，但仍不能证明类型、状态或 oracle 正确；也会漏掉位于不同文件/class/describe 中的可迁移关系。
- 共享 producer 是搜索启发式。当前 `_producers` 收集 actual-only value trace 中的所有调用，所以两个测试只共享远端 factory，也可能被放入同组。callee identity 的 `scope_key` fallback 只表示同文件中的拼写，不能当作已经解析的同一运行时方法。
- 三者都必须共享某 producer 比 core 更严格。B 可能更换观察 route；只要求 A/C 的观察具有清楚对应关系、更仔细检查 A→B 的改动，比要求三者始终使用同一调用更符合运输方向。
- skeleton 近邻使 A/C 较易反统一，但不表示它们观察同一行为。B 按 skeleton 类别轮转能增加形状多样性，也仍可能枚举只有常量或局部名称变化的 A→B。

因此，这些限制应作为明确报告的支持范围或搜索优先级，不能在论文中解释成“已建立语义关联”。

## 建议一个简单的排序：先找观察一致的 A/C，再找相关的 A→B 改动

将三元组视为两条有方向的边：A→C 提供输入/预期的对应替换，A→B 提供需要运输的改动。无需再增加自然语言字段。

1. **观察键 F(t)**：从每个 capsule 的 actual 表达式出发，沿 `slice_edges.kind == value` 反向走，遇到第一个调用即停止；记录其已解析 callee identity，以及到 actual 的 field/index 投影。helper 使用现有 caller actual 绑定作为根。多个分支保留多个键。expected 常量不进入这个键；不能把一般 assertion slice 当 actual slice。无法唯一绑定的调用保留 unknown。
2. **相关改动 E(A,B)**：用现有有序语句对应提取新增/删除/修改的调用、断言 predicate/projection 或输入构造结构。若改动在 B 的 actual value slice，或其读写通过现有 def-use 到达该观察，则标为 value-connected。若仅有 may-effect/receiver 关联，则标为 may-connected；不能称为确定依赖。只改变常量或 alpha 名称的对应对排在这种结构差分之后。
3. **按字典序排序**：`(A/C 的 F 匹配强度, E 的观察关联强度, -结构改动大小, -A/C 对齐代价)`。无需拟合权重。对不同检索测试/producer 保持轮转，仍共用原始预算。

这里的 F 是“离断言最近的观察调用”，不是“任意共同上游调用”。例如共享 `make()`、分别检查 `.left()` 与 `.right()` 的两个测试，不应获得与观察同一 `.left()` 的测试对相同的优先级。

这只能改进优先级，不能作为充分条件：状态写入可能只有 may-effect 边；fixture/闭包和字符串中的程序仍不完整。当前 `capsule.calls` 主要来自 assertion slice，未纳入该 slice 的新增操作还需从完整 body AST 找回；不能声称现有 calls 列表包含所有操作。未解析或只有值变化的候选应保留较低优先级桶，而非全部过滤，否则会人为漏掉状态组合和纯参数组合。

## 已验证的两项覆盖问题

**所有 Python assert 共用一个 key，造成不必要的歧义。**

```python
A: assert f(1) == 2
B: assert f(1) == 2; assert metadata() == 3
C: assert f(5) == 10
```

当前 alignment 把 B 的两个 assert 都视作 A 的候选锚，返回 ambiguous。toy 从 corpus 的 actual-call identity 得到 `f` / `metadata` 标签后，能够重构 `assert f(5)==10; assert metadata()==3`，没有使用 expected 常量作锚。

修正应**优先 exact observer signature，必要时回退到共享 actual value producer 的改动对应**。若把 exact observer 当硬要求，则 A 的 `f(...)` 变为 B 的 `wrap(f(...))` 时又会漏报。可以在同一单调匹配动态规划中给 exact 对应更低代价，保留有限个最优对应；新增断言作为 residual/edit 留下。此对应仍是语法假设。

**完整语句嵌入不能替代原树类比。**

```python
A: setup(1); assert f(3) == 6
B:           assert f(3) == 6
C: setup(9); assert f(5) == 10
```

raw v2.1 能给出 `assert f(5)==10`，三项重构成立，丢弃的 setup 参数被明确报告；alignment 要求 A 每条语句都嵌入 B，因而返回 missing_anchor。独立 toy 还确认 assignment→call 的语句种类变化也存在这种回退。

建议统一接口仅做一件事：**每个 ABC 在一个预算单位内尝试 raw view，以及可选的 aligned view（至多两种 gap 顺序）**。所有输出进入同一个去重、绑定检查、128 项选择和 gate。记录 view 与各自的重构证据；alignment 的 residual 恰一次保证只属于 aligned view。这样扩大表示能力，不牺牲 raw 已支持的删除/改写，也不引入按库定义的操作。

任何一个 view 的三重重构，都不证明 oracle、效果交换、捕获安全或内联表达式不会被复制。语义 gate 的边界保持不变。
