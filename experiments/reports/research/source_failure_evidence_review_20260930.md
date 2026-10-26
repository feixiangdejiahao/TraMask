> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/source_failure_evidence_review_20260930.md) · [旧路径映射](../../../results/path_map.tsv)

# 自定义 Go 断言的失败源码证据：独立审查

日期：2026-09-30。本文形成于实现前，以下设计判断保留其当时语境。后续独立原型已实现并完成源码census，见[实现报告](source_failure_evidence_20260930.md)。审查不请求模型，不执行被测仓库，不读取隐藏 verifier 或参考补丁；不能把设计中的效果当成语义或检出收益。

## 判断

从真实 `*testing.T` 的失败操作回溯静态调用，是一个有针对性的源码证据补充。它能够回答“这次 helper 调用在哪些检查下失败，这些检查依赖本次调用的哪些参数”，从而减少模型追踪自定义断言的工作。它本身不能回答“哪个参数是允许修改的 expected”，更不能证明新的 expected 正确。

这属于经典的跨过程控制依赖、数据依赖与调用实例化的应用。当前可以主张分析任务更明确、证据更可核验，不能仅把它重新命名后主张学术创新。其效果需要比较同一候选、同一模型预算下，增加这些证据是否减少错误参数修改和错误完整 oracle。

## P5/P6 的具体帮助与限制

源码：`data/relational_gap_v1/P5/repository/eval_test.go:11` 与 P6 同位置。局部 helper 为：

```go
eval := func(expr string, params map[string]interface{}, expected interface{}) {
    ctx := context.Background()
    actual, err := tengo.Eval(ctx, expr, params)
    require.NoError(t, err)
    require.Equal(t, expected, actual)
}
```

`require` 是仓库内的 `github.com/d5/tengo/v2/require`，不是 testify。现有 local-helper 分析已恢复独立调用的形参与实参绑定，但由于自定义包的断言角色未知，没有开放 expected 参数边界。这个限制是准确的，不能添加一个包名例外解决。

检查 `require/require.go` 后可见：

* `NoError` 在 `err != nil` 时调用 `failExpectedActual`，后者最终调用 `t.FailNow()`。这是 `Equal` 的前置终止检查，不能在完整 oracle 审查时丢弃。
* `Equal` 不只是一个二元比较。它先检查 nil 与类型，再执行 type switch；不同分支使用直接比较、slice 比较、递归 `Equal` 或接口 `Equals`。`default` 还会 panic。这些区别必须保持为具体源码事实。
* `expected` 与 `actual` 两侧都能影响失败条件。仅从失败谓词的依赖集合无法判定 expected 角色；对称相等条件尤其没有这个信息。

因此，新增分析的直接收益是：使模型看见 `err` 来自本次 `tengo.Eval`，先前 `NoError` 是否终止，以及 `Equal` 两个操作数分别来自本次 helper 的第三实参和被测调用结果。不同 `eval(...)` 的第三实参必须独立绑定，不可修改共享 helper 的 formal 或把不同调用归成一个 oracle。

当前有限 cohort 的 P5/P6 候选删除了脚本使用的参数 `a` 或 `b`。failure evidence 能指出更早的错误检查需要被考虑；它不能仅通过修改第三实参，使这个前置检查变得正确。该结论来自原有程序结构，不是根据候选程序运行结果推定 required behavior。是否允许改错误预期，需要 issue、语言行为契约和完整测试共同判断。

## 最小分析应输出什么事实

不需要另建自然语言关系框架。最小实现可直接保存源码片段与位置，并完成以下步骤：

1. 用 Go 导入和类型/词法绑定确认失败接收者确实源于 `*testing.T`。区分 `Error/Errorf/Fail` 与 `Fatal/Fatalf/FailNow` 的继续/终止效果；同名其他方法不是测试失败锚点。
2. 从这些锚点在同包内沿已解析的直接静态调用向上回溯。跨包测试调用通过实际 import 到达自定义包，包内 wrapper 继续静态回溯；动态方法派发、反射和不可解析边明确未知。递归使用有限摘要或明确截断，不能静默删去未知分支。
3. 保留每个失败调用的控制分支与前置调用顺序。分别追踪失败条件所依赖的 formal、传入日志/诊断的 formal，以及失败接收者来源。仅进入日志的值不能被归为控制失败的参数。
4. 把上述 formal 依赖沿每一个实际调用实例向上传递，保留 actual 的完整源码表达式和声明链。使用静态 may-dependency；不能把“可能影响失败”说成“必然失败”，也不能把多个分支条件拼成一个未经证明的精确失败公式。
5. 在测试 helper 实例处保留所有更早的失败检查、观察及参数其他用途。对结果谓词、输入/状态用途、诊断用途分别列源码引用，不从函数名、变量名或参数位置宣布角色。

这里的有限保证是：已解析调用与语法控制关系可由源码复核；同一 helper 的各次调用不会共用实参位置。它不是完整 Go 行为摘要、完整失败条件，也不是正确 oracle 证明。特别是 panic、接口调用、反射、循环路径和副作用可能留下未知。

## 六个必须能反驳过强推断的反例

这些是设计要求，本文没有运行它们。一个有用的实现应提供证据或显式未知，而非猜出可编辑 expected。

### 1. 对称比较没有 oracle 方向

```go
func Check(t *testing.T, a, b int) {
    if a != b { t.Fatal("different") }
}
Check(t, runA(x), runB(x))
```

两参数都控制失败，但两者都可能是被测结果。变量改名、交换形参名字或重排实参，不能凭名字把其中一侧开放为 expected。需要完整调用的数据来源和任务语义；证据不足时角色未知。

### 2. 诊断数据不是失败条件

```go
func Check(t *testing.T, label string, n int) {
    if n < 0 { t.Errorf("%s: %d", label, n) }
}
```

`label` 到达失败方法的日志实参，但不控制失败。把所有 backward data slice 都叫作 oracle 依赖，会错误开放 label。源码能区分 `n < 0` 的控制依赖与消息依赖。

### 3. 更早终止不能用后续比较修复

```go
func Check(t *testing.T, input string, want int) {
    got, err := Run(input)
    if err != nil { t.Fatal(err) }
    if got != want { t.Fatal("different") }
}
```

合法组合可能应返回 error；只把 `want` 改成某个值仍不能得到完整正确 oracle。这里要保留早期 `Fatal` 和后续比较的阶段关系。更换成 `t.Error(err)` 时后续执行行为又不同，不能把两类 sink 视为一样。

### 4. 比较参数也可以是被测输入或状态操作

```go
func Check(t *testing.T, p int) {
    got := Run(p)
    if got != p { t.Fatal("different") }
}
```

`p` 是比较的一侧，但也决定 `Run` 输入。修改调用处的 `p` 会改变验证场景，不能称为仅修改 expected。通过闭包捕获、指针或对象字段使用的情况同样需要检查，不能只统计直接 identifier 出现。

### 5. 自定义比较不保证纯函数或数学相等

```go
func Check(t *testing.T, a, b Item) {
    if !a.Equals(b) { t.Fatal("different") }
}
```

`Equals` 可能动态派发、修改接收者、忽略字段或调用被测实现。失败条件确实依赖 a/b，不代表观察语义已知或该边可安全编辑。P5/P6 的真实 `Equal` 包含这一类分支，也包含 typed-nil 与 panic 分支；不能以函数叫 Equal 宣布统一语义。

### 6. 失败接收者和执行阶段可能变化

```go
func Check(t *testing.T, other *testing.T, bad bool) {
    dst := other
    go func() { if bad { dst.Fatal("different") } }()
}
```

实际被标记的测试来自 `other`；goroutine 内的 `FailNow` 也不能当作当前调用同步终止。别名、闭包、异步或动态 reporter 无法被最小同步静态分析解析时，必须保留未知。只按 `t`/`Fatal` 的拼写找 sink 会得出错误阶段关系。

## 把 LLM 的问题缩小到参数角色，而不是让它重做程序分析

程序先给出一次具体 helper 调用的实参绑定、被测结果来源、各失败谓词与前置 guard；模型只回答一个有限问题：在这个调用中，哪些具体源码表达式仅承载预期值，哪些同时承载输入/状态/诊断，哪些证据不足。答案以已有源码位置为对象，不要求模型发明新的关系标签或修改测试体。

最小问题可以是：

> “依据下面完整调用、其 helper 及失败控制片段，第三实参是否仅表示该次调用的预期结果？列出支持或反驳这一角色的已有源码位置；若更早 guard、输入用途或未知副作用妨碍判断，回答 unknown。不要计算当前实现的输出，也不要修改任何代码。”

对 P5/P6 可以不依赖名字进行判断：表达式与参数 map 传入被测 `Eval`；另一实参只进入结果检查；`Eval` 的返回值进入比较另一侧。但这只是调用角色判断，仍不能直接确定正确的 expected。

如果之后生成新预期，另一个小问题才依据 issue 与明确契约推理新输入的 required outcome，并联合检查早期 error 断言及全部后续观察。源码中的候选实现只能解释调用和类型，不得用其执行值作为正确答案。对于契约不足的例子，应 unknown；对于多个输入实例，不共享预期结论。模型角色判断没有静态正确性保证，机械验证只能确认引用位置存在、输入操作没有改动、所有检查仍保留。

## 可评价的最小效果

固定同一调用、同一候选与模型预算，比较现有证据和增加 failure-source 证据两个版本。先评价 recovered call/sink/guard 是否能源码复核，再独立人工评价单次参数角色、错误开放输入参数、遗漏前置检查及完整 oracle 正确率。不能以提取 sink 数量、token 压缩或接口接受率替代语义效果，也不能将 P5/P6 的一个自定义包规则推广为通用算法。

这条方向值得实现为窄而可反驳的分析补充。它直接针对当前证据的真实缺口，但既不解决组合候选生成的核心抽象缺口，也不消除自动 oracle 正确性问题。

实现后独立审查发现并修复了range、分组var/const、局部type对失败接收者或静态callee的遮蔽，以及block和if initializer短变量作用域泄漏。共享local-helper导入解析也修复了同类声明名遗漏。修复采用语法声明与作用域规则，没有增加案例或包名例外。诊断与控制依赖分离、分组/variadic实参映射、递归有限固定点、源码未知运输均已用独立fixture复核；相关本地检查110通过，没有调用模型或执行被测仓库。这只能支持源码绑定与所述边界，不能证明expected角色或正确oracle。
