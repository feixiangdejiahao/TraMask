> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../../research/archive/method_design_context_lifting_pilot.md) · [旧路径映射](../../../../results/path_map.tsv)

# 保持观察的上下文提升

> 状态纠正（2026-09-23）：本文描述 `combination-v0.1-pilot` 开发集原型。其中协议、路径、闭包及递归变换是在已知 pilot 缺陷之后加入的，存在方法设计层面的过拟合；7/7 不构成泛化证据。新一轮改进必须从测试来源学习编辑，禁止复用这些领域算子，约定见 [通用化计划](../generic_generation_plan.md)。新算法尚未完成独立评价，不能宣称已经解决过拟合。

2026-09-23，实验原型。现已实现入口检索、组合构造、oracle 准入和隔离执行；没有测量修复成功率提升。检索细节保存在 [观察前沿方法](../observation_frontier_method.md)，最终结果见 [组合实验报告](../combination_generation_experiment.md)，负结果保存在 [开发记录](../context_lifting_execution_notes.md)。

**核心抽象：把已有观察提升到尚未检验的上下文。** 一个闭包原来位于 global，现在位于 factory 返回的容器中；一个动作原来作用于普通对象，现在作用于递归结构。要检查的是：进入新上下文后，应保持的观察是否丢失。

设 t 为种子，a 为观察，C 为上下文变换，B_C 为独立的基准构造，g_C 为适用条件。生成一个义务：

\[
g_C(t)\Rightarrow \mathcal O(C[t])\equiv_a\mathcal O(B_C[t]).
\]

≡ₐ 只比较相关观察，不要求所有状态相同。右侧可以是原断言，也可以是同一输入经另一条等价路径得到的结果。**程序依赖帮助找到 C 的位置，不能证明 g_C 或 oracle 正确。** 将候选实现中的不变性直接当作需求，还会排除恰好缺失依赖的缺陷。

**算法**

```text
A ← observation_frontier(assertion_slices(tests, patch))[:k]
for a in A:
    for C in bounded_contexts(a, tests, bindings, input_grammar):
        (followup, baseline, g) ← lift(a, C)
        if unsupported(g) or contradicted_by_existing_assertions(g): continue
        emit controls and (followup, baseline, g)
freeze artifacts
execute candidate; report violations whose own controls and premises hold
```

参考实现只在冻结后执行，用于评价。生成器及模型不读取参考补丁、隐藏 verifier、手工目标或执行判定；参考失败不能反向成为删除生成测试的规则。

**1. 快速找到可提升的断言**

AST 识别 assert、断言库调用及输入绑定。局部定义—使用和有界跨过程字段来源查询构成依赖足迹 D(a)。同一测试中优先处理足迹的极大元，再按参数化期望多样性和源码位置排序；跨测试轮流分配断言预算，避免大量重复 validation 占满前十。测试顺序沿用补丁/标识符基线。

切片包含相关输入、调用及状态操作，但不等于任意 fixture 都可独立运行的完整程序。生成阶段通过受限 AST 改写、辅助函数提取和专用入口构造可执行上下文。分析边界及 7/7 Hit@10 消融见 [检索报告](../observation_frontier_experiment.md)。检索命中不代表缺陷已检出。

**2. 由程序构造上下文和基准**

| 变换 | 自动构造及观察 | 核心前提 |
|---|---|---|
| 路径表示扩展 | 修改同一 Path 绑定的 setup 和命令插值，保留引用该绑定的原断言，增加空格与合法引号 | 绑定未重写，路径是完整命令 token；不能冻结旧文件名 oracle |
| 全局→局部捕获，再从 host 调用 | AST 提取 guest 程序，装入返回复合值的 factory；同参比较 host 与 guest 调用 | 比较提升后的同一程序，不假定提升前后所有语义相同 |
| 捕获状态进入 clone | 为识别到的顶层标量绑定生成 observer；比较 clone 与 fresh 的同一序列，同时检查源实例不变 | 初始化确定；clone 保持内部共享并与源隔离；尚无完整 guest 写集合分析 |
| 非恒等动作进入递归 | 从已有测试迁移纯对象扩展 donor；比较 μF 与 F⁸(bottom) | 闭合构造表达式；显式检测是否触底；donor 在展开路径有实际效果 |
| 协议输入坐标扩展 | AST 提取 packet 与字段断言；把 donor 值迁入一个坐标或 modifier bit | 新输入在支持域内；原断言的保持条件成立 |

这些是同一义务的有限实例，不是覆盖任意仓库的通用组合器。Go 限制 arity、参数、返回深度和调用次数；TS 的仓库纯度注解是契约证据，不是纯度证明。实际发现的变换错误与修复见 [适用性审计](../structural_applicability_audit.md)。

**3. oracle 从哪里来**

结构关系优先使用程序构造：递归 oracle 是同一 schema 的有限展开；clone oracle 是同源 fresh 实例的配对观察，不需要模型写每个节点的期望输出或 counter 数值。

协议语义仍是主要难点。目前比较两种受限辅助：模型选择程序已生成的具体 proposal ID；或提出纯布尔保持条件 `preserves(a, source, followup)`。后者经受限 AST 解释，再用已有一坐标变化的正反事实检验。输入变换、最终断言期望值和测试体均由程序生成；模型请求、输出和哈希固定保存。

这是**契约辅助的条件提出**，不是从有限测试证明不变量。模型可能过宽、过窄、复制候选缺陷或误读语法。现有事实能否决条件，没有反例不意味着正确。最终分支默认只向模型提供 issue、已有测试、API docstrings 和公开协议事实，不提供候选实现正文；文档仍可能不完整。模型虽然不改 expected，但其条件内部可能计算输出语义，不能声称模型完全不涉及 oracle。ID 筛选另混入自动标注的正反校准对，答案不发送给模型。公开协议/producer 的输入约束独立于候选代码，不能把候选缺失的解析分支误当作非法输入。

协议候选按断言、变换坐标和输入类别轮换，当前统一预算 128。类别只用于采样，不能把代表值上的许可外推到全部同类输入。未采样、静态不支持、条件错误和执行失败分别记录。

**4. P7：为什么需要新的 oracle**

原测试的动作是 `readonly`，运行时几乎不改变对象。即使递归解析忘记动作，原断言也可能通过。程序从其他测试找到纯 donor，本轮为 `value => ({...value, key2: 123})`，把它迁入同一递归孔，比较：

```text
递归构造 + donor ──parse(input)──→ actual
同一构造有限展开 + donor ──parse(input)──→ expected
```

属性、常量和输入来自已有测试。先确认恒等控制通过、展开没有触底、donor 确实改变展开结果。若候选递归路径丢失新增属性，两边结果就不同。关键不是找两个名字相近的 test，而是构造动作进入递归上下文后应保持的观察。

**5. 怎样评价成功**

| 指标 | 回答的问题 |
|---|---|
| Test / Assertion Hit@k | 正确入口是否在预算内？ |
| 已知目标检出率 | 多少已知缺陷机制有有效生成证据？发现其他差异不能抵消目标漏报 |
| Candidate alerts | 候选上满足前提与来源控制的失败数；不查看参考 |
| Reference alerts | 相同规则下参考的失败数；不能直接等同真误报 |
| 差分证据与 oracle 审计 | 候选失败/参考通过是否仍违背 issue？输入及保持关系是否有依据？ |
| 不适用、控制失败、未执行与模型成本 | 放弃了哪些输入，付出了多少成本？ |

早期实验出现了“候选失败、参考通过，但断言违背 issue”的实例，见 [screening v1 审计](../screened_v1_oracle_audit.md)。因此成功条件不能只是两个实现的 pass/fail。最终统一 v6 生成 263 个组合及 168 个控制，检出 7/7 个已知目标；49 条候选报警的独立审计没有发现错误 oracle。另有三条需求支持的参考报警和九个参考原始控制失败，均保留。固定缓存在 14 个新容器重放一致，独立模型重抽样也保持 7/7 和相同报警集合，但新增一条双方通过、关系尚未独立确认的测试。这些结果不能证明未见组合上的可靠性。

**6. 2026 软工论文的 insight**

MR-Coupler 用签名、调用及状态交互限制功能耦合对，再构造、放大和检验关系。借鉴的是**用可计算结构缩小关系搜索空间，并独立验证关系有效性**，而非要求所有问题都必须采用 MR。[FSE 2026 官方页面](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/200/MR-Coupler-Automated-Metamorphic-Test-Generation-via-Functional-Coupling-Analysis)、[论文](https://arxiv.org/html/2604.10126v1)。

ArrayDiff 跨框架迁移 API 输入要求，生成序列时维护这些要求，避免组合破坏后续调用前提。对应这里，**输入域和 oracle 保持条件应随变换一起构造**；调用依赖、类型相同或一个通过的 seed 都不足以保证正确组合。[FSE 2026 官方页面](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/107/LLM-Assisted-Input-Requirement-Aware-Differential-Testing-of-Array-Programming-Framew)、[作者论文](https://jhe16.github.io/files/FSE26.pdf)。

潜在贡献是以“观察尚未覆盖的上下文”组织搜索，通过保持绑定的改写或独立构造产生比较基准。放大、切片和差分测试本身不是新贡献。七例只有四个 issue 家族，且已人工分析，是发现集；适配器和假设的开发受到这些例子启发。synthetic checks、名称改写和冻结重放不能代替未见 issue 的验证，也不能证明普遍零误报、零漏报或更高 issue resolution rate。
