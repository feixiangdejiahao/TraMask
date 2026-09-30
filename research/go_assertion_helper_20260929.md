# 从 Go helper 源码提取候选 expected 实参

现有 frontend 把 `verify(t, o, "...")` 整个调用当成 observed，因而连 expected 字符串也不能修改。本原型先查看实际 helper 的源码，找出可以独立修改的比较参数，再把它映射回调用点的一个实参。它不依赖 `verify`、`exp` 等名字，也不把第三个参数固定当作 expected。

核心分析只有三步：

1. 按实际目录、package 和函数声明唯一解析调用，确认 helper 有来自标准库的 `*testing.T` 参数。
2. 找到唯一的“裸形参与实际表达式比较、条件成立后报告测试失败”的 guard。从实际表达式沿局部赋值回溯到其他形参；候选 expected 若同时影响实际表达式，就无法独立修改。两侧都是裸形参时角色对称，返回 unknown。
3. 根据形参位置找到调用点对应实参的 AST 字节范围。只暴露这个范围；callee、其他实参和完整 helper 源码继续保留。

例如，N05 的源码是：

```go
func verify(t *testing.T, o *Output, exp string) {
    tty := o.w.(*os.File)
    if _, err := tty.Seek(0, 0); err != nil { t.Fatal(err) }
    b, err := io.ReadAll(tty)
    if err != nil { t.Fatal(err) }
    if string(b) != exp {
        // 格式化诊断后调用 t.Errorf
    }
    // 清理临时文件
}
```

分析得到 `string(b) ← b ← io.ReadAll(tty) ← tty ← o.w`，实际表达式依赖参数 `o`，而比较另一侧直接来自 `exp`。在调用 `verify(t, o, "\x1b[s")` 处，候选 expected 范围因此是字符串 `"\x1b[s"`。两个 `err != nil → t.Fatal` 是前置异常检查，单独保存，不能把整个 helper 误说成只有一个 assertion。这里未知的 `ReadAll` 返回值只记录其显式实参依赖，不声称实现了完整的跨过程别名或副作用分析。

expected 的用途也受到检查：如果它流入其他不透明调用、比较前被重新赋值，或者被写入外部状态，返回 unknown。失败分支中的 `testing.T` 诊断及明确解析到标准库的少量纯字符串操作可以保留；同名自定义包、局部遮蔽的 `strings` 或 `len` 不会套用标准库摘要。多个数据断言、复杂控制流、返回值 helper、声明歧义等也保持 unknown。

这些规则只证明了一个结构上可分离的**候选槽**，不能单凭“裸参数对派生表达式”证明程序员的 expected 意图。例如，另一种 helper 可能恰好把实际结果直接作为参数，把预期放进对象。未来应用时仍需调用点来源或语义判断来确定角色。本次 N05 的 45 个候选槽全部接收源代码字面量，提供了额外调用点证据；原型没有用这个事实倒过来选择特定 case。

固定库存的 17 个 corpus 按 `language == go` 自动选出 6 个，包含 N06。最终源代码 census 位于 `results/relation_search_20260929/go_assertion_helper_census_v2/`，在分析前封存协议、语料哈希和源码快照，全程没有模型请求、Docker 或 target 标签输入。

| Corpus | 同包 testing helper 名调用 | 可提取候选槽 | Unknown |
| --- | ---: | ---: | ---: |
| N05 | 90 | 45 | 45 |
| N06 | 312 | 0 | 312 |
| N07 | 216 | 0 | 216 |
| N08 | 137 | 0 | 137 |
| P5 | 1,824 | 0 | 1,824 |
| P6 | 1,804 | 0 | 1,804 |
| 合计 | 4,383 | 45 | 4,338 |

完整分母来自 33,009 个 registered-test 调用，包含 setup helper、返回值 helper 等，不是已标注的 assertion helper 真值集。因此 `45/4,383` 是此类调用的槽提取支持率，不能称为断言召回率或缺陷检测率。第一版 census 没把不支持的 variadic/unnamed helper 纳入分母，第二版修正了这一遗漏；应引用 v2。

实现：`experimental/go_assertion_helper.py`。25 个单元测试覆盖 helper 改名、参数置换、import 别名、对称参数、共享依赖、不透明调用、多断言、遮蔽、声明歧义及 UTF-8 字节范围。`scripts/analyze_go_assertion_helpers.py` 可重跑 census。

本次没有接入 production frontend/oracle，没有增加模型调用或执行组合测试。它为已有 N05 helper 提供了可编辑边界，尚未证明新增了缺陷命中，也没有解决其他 Go 任务的复杂 helper。

2026-09-30进一步只读检查有限模板研究的固定原始候选池（`paired_inputs_v3/protocol.json`所指inventory）。将程序编辑范围与上述已支持helper的原expected实参范围匹配，六个Go池分别有175、174、335、506、370、382个候选；只有N05存在45处可支持的原helper调用，其175个候选均没有编辑这些expected实参，其他五池没有可支持槽。因此，在当前材料上“优先排除只改helper期望的候选”不能释放任何预算，没有实现或接入这种排序。范围匹配仅检查已有支持边界，未匹配不证明任意动态helper编辑不涉及期望；此次没有读取模型回答、执行结果或目标标签，也没有新增模型或仓库执行。
