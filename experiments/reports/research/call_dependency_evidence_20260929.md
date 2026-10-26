> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/call_dependency_evidence_20260929.md) · [旧路径映射](../../../results/path_map.tsv)

# 供模型阅读的原源码依赖证据（本地原型）

程序分析在这里做的是替模型找到代码关系，而不是替模型猜正确输出。新接口 [call_dependency_evidence.py](../../../prototypes/call_dependency_evidence.py) 把frontend已经计算的事实整理成源码片段和带类型的边。它没有模型生成的自然语言关系字段，也不产生期望值。

例如原测试先写 `input = 1`，再调用 `result = twice(input)` 并检查 `result == 2`。候选把第一处的1改成3。接口通过已有 `value.input_slots` 找到受输入改动涉及的call，再展示：

```
input编辑 → 原input-use → twice(input)
实参 input → 原actual/formal映射 → 形参 value
twice(input) → 原静态切片may边 → assert result == 2
```

每个节点都能回到具体文件、字节区间和原始代码，函数声明和局部定义也一起展示。这个图不声称新预期必须是6；模型仍需结合issue契约推理。`may`表示静态近似可能包含多余边。

入口是 `candidate_evidence(corpus, frontend, candidate)`，纯函数式返回nodes/edges/unknowns；`render_evidence(evidence)`将相同事实确定性渲染成文本。调用方仍需附完整修改后测试及issue，此接口不裁掉状态前缀或取代完整测试。

程序先找编辑与原call相交的位置，或用frontend已有的value/input-slot和局部binding记录找到受编辑涉及的call。由这些call的 `observation_ids` 取全部关联q。这里只展开这些输入改动所涉及的call，不逆向扩成q的整个切片；q的其他生产者仍需在完整测试中阅读。对唯一源码target，显示原actual/formal映射；对receiver显示局部定义及原binding，显式保留object identity未知。相互包含的源码片段只打印一次，节点位置和边全部保留。

如果callee语法已变、更换receiver或编辑了receiver的定义，旧target与参数binding不会被当成新调用的绑定；新callee只标unknown，不按名字猜函数。若仅改变实参值，原参数位置映射仍只标“原源码事实”，不声称变换后的参数数量或运行时状态已重新验证。新callee、动态分派、别名、跨线程先后关系和缺失声明都没有被这个接口解决。

独立review另确认两个覆盖边界：`box.value = 2; result = box.read(); assert result == 2` 只把字段写入2改成3时，目前原value/input-slot事实无法接到read，得到空seed/q和明确unknown；这需要字段写入路径分析补充。整调用 `f(a,b)` 替换成 `f(b,a)` 时，编辑span覆盖callee会保守失效旧解析，尽管名字f未变；它丢失可利用证据，没有编造新目标。本轮不靠案例名补规则，也没有把这两个未知当正确结果。

八项测试中七个集成toy使用真实frontend，覆盖Python/Go/TypeScript的setup→call→formal→q链、receiver定义、改callee、在callee边界插入receiver以及更改receiver定义，另一个检查源码去重不丢节点或边；与运输接口及现有guard/oracle共162项相关回归通过。固定32父程序的本地渲染存放在 `results/relation_search_20260929/singleton_call_evidence_focused_v1/`；此前逆向扩出同q其他call的初稿也留存在 `singleton_call_evidence_v1/`，其最大318KB揭示了保守切片边容易膨胀的问题。最终接口只整理编辑涉及的call和全部关联q，仍不宣称完整切片；没有读目标标签、没有模型调用或执行测试案例。

这32父程序都有种子call，30个能从原frontend链到关联observation q；N08的两项没有此链接，保留未知。按候选计重复site，实际选中182个call、197个q、818个节点、1385条边，其中164条actual/formal、148条局部binding、69条源码target、721条call→q may边。与原facts审计的1245个call/10838条call→q边区别在于，这里明确只整理输入编辑涉及的call前沿。

| 实际文本/图大小 | 最小 | 中位数 | P90（向下取整分位） | 最大 |
| --- | ---: | ---: | ---: | ---: |
| UTF-8 bytes | 1092 | 8524 | 16401 | 41059 |
| 节点数 | 3 | 19 | 46 | 95 |
| 关联q数 | 0 | 5 | 12 | 19 |

这些是补充证据大小，不包括必须单独提供的完整modified test及issue。未知列表沿用完整原source_context，可能包含未展开call的未知项；没有为了缩短而丢弃完整测试或静默宣称闭包完整。尚未验证把这些文本交给模型后的预算和推理效果。

这是整理已有程序事实的接口原型，尚未证明能提高模型准确率。此前source-context消融发送的是完整声明，没有发送此renderer的边；不能把那组实验结果归因于本接口。另一个独立原型处理Python q→字段写入的深层路径，两者证据来源不同，尚未组合成统一算法。
