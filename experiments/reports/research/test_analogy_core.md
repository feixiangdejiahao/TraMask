> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/test_analogy_core.md) · [旧路径映射](../../../results/path_map.tsv)

**研究中的核心：补全测试类比 `A : B :: C : D`**

2026-09-23。这是通用原型 v2 的核心假设，尚不能作为有效性结论。底层算法见 [analogy.py](../../../prototypes/test_edit_analogy_v02/analogy.py)，自动选取来源及构造测试见 [generate.py](../../../prototypes/test_edit_analogy_v02/generate.py)。自动流程已通过独立机械测试，真实案例效果另行评价；v1 的运行结果不归到 v2 名下。

以前的困难在于：修改输入之后，为什么还可以使用旧断言？这里把问题改成：**已有测试 A 到 B 同时展示了输入和观察的变化，能否把这段变化迁移到另一个测试 C？** 程序生成 D 的输入和断言，模型只判断这次迁移是否符合契约。

例如，某 API 的文档规定列表输入逐项计算，已有测试为：

```python
# A
assert f(3) == 6
# B
assert f([3]) == [6]
# C
assert f(5) == 10
```

A→B 展示“输入变成列表，预期输出也变成列表”。A→C 展示另一组输入与预期值。补全得到：

```python
# D
assert f([5]) == [10]
```

`5` 和 `10` 来自 C，两个列表结构来自 B；没有调用候选实现计算 `10`，也没有要求模型编造这个值。若列表语义实际上是“求和”，同样的语法构造就没有可靠依据，必须在契约判断中拒绝。有限的三个实例本身不能证明第四个实例正确。

**一个算法，同时处理输入和 oracle**

把测试体表示为保留源码的语法树。先对 A、C 做反统一：提取共同骨架 P 和两组替换，使：

\[
P[\sigma_A]=A,\qquad P[\sigma_C]=C.
\]

再把 B 中与 `σA` 对应的子树替换为相同的洞，得到 Q，要求：

\[
Q[\sigma_A]=B.
\]

最后生成：

\[
D=Q[\sigma_C].
\]

例子中，`P = assert f(x) == y`，`Q = assert f([x]) == [y]`，`σA={x↦3,y↦6}`，`σC={x↦5,y↦10}`。整个构造没有按库或缺陷种类选择变换。

```text
P, σA, σC = anti_unify(A, C)
Q = abstract_corresponding_subtrees(B, σA)
check P[σA] == A and P[σC] == C and Q[σA] == B
D = Q[σC]
check scope / binding / known call signatures
ask whether the complete D follows the available contract
```

这些等式证明来源与重构，不证明语义。重复出现的相同数值也不一定是同一角色：输入恰好为 `1`，预期计数也恰好为 `1`，不能仅凭相等就把二者一起改掉。应使用可解析的调用参数位置、定义—使用关系和断言位置区分角色；无法区分的对应保留为不支持，不能由模型现场补造程序。

独立测试也给出了明确反例：令 `f(x)=x`，A 为 `f(3)==3`，B 为 `f(3)+1==4`，C 为 `f(8)==8`，三者全部正确；语法算法仍可能补成错误的 `f(8)+1==4`。`4` 虽然来自正确测试 B，却不能原样迁移。这说明“期望值有源码来源”不是 oracle 正确性的充分条件；当前核心不自动归纳算术规律，契约准入必须检查整个 D，而不能只检查输入是否合法。该反例保存在 [独立核心测试](../../../tests/test_generic_analogy_review.py)。

**何时保留，何时更换断言**

保留还是改变由源测试 A→B 的完整差异决定。若 B 中原观察仍在，迁移后相应保留；若 B 展示新的容器结果、关系断言或后续状态观察，这些代码也参与迁移。算法不先假定“改输入，expected 必须不变”。

例如 A 只有 `put(4); assert box is not None`，B 已经检查 `put(4); assert box.peek() == 4`，C 为 `put(9); assert box is not None`。在普通存取契约下，程序可以运输 B 的已有观察，得到 `put(9); assert box.peek() == 9`。这里没有自动证明 A 太弱，更没有发明一个此前不存在的强 oracle；若 B 不存在，当前抽象就可能无能为力。

**程序分析解决的具体问题**

- 检索和调用关联限定哪些测试值得组成 A、B、C，避免无界枚举所有三元组。
- 语法对应与定义—使用关系限定哪些输入、观察及重复出现的值必须一起变化。
- 作用域与可见签名排除明确的未绑定名字、参数数量及返回值数量错误；未知类型不冒充已证明合法。
- 模型处理契约是否支持第四个测试这一剩余语义问题；不生成代码，不看执行结果修改答案。

首次自动集成在相同文件、外层作用域和测试参数接口内，按共同观察到的 producer 分组；至少一个来源来自检索前十。C 优先取语法骨架相近的测试，B 按骨架类别轮转，避免大量仅常量不同的验证测试挤掉新增操作；三元组按来源与 producer 轮转，最多尝试 2000 次，输出最多 128 条。Python literal 单参数表先整行绑定具体化，保留参数共享；indirect fixture 不支持。字符串统一无损分词，不内置输入文法。已有组合和受限局部重命名被去重。

当前确定的结构性漏报是：A、C 的准备语句数不同，第一阶树反统一可能把整个 block 变成一个洞，失去 producer 与断言的对应。当前也不跨文件迁移任意 fixture，不归纳新的算术 oracle。语言适配、作用域检查和模型准入均不使方法变成完整或健全的分析。具体搜索预算和拒绝计数保存在每次生成产物中。

**与已有研究的联系和区别**

MR-Coupler 的启发是以一个可计算的关系组织搜索和验证。本原型的关系是四条测试之间可重构的语法类比，暂不要求建立蜕变关系。类比学习、反统一和测试放大本身已有大量先例，不能把换名当作新颖性。[FSE 2026 官方论文页](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/200/MR-Coupler-Automated-Metamorphic-Test-Generation-via-Functional-Coupling-Analysis)。

ISSTA 2026 收录的 *Towards More Realistic Assertion Generation under Mixed-Assertion Scenario* 强调，多断言通常协同检查一个目标，插入位置也影响断言内容。由此得到的设计启发是联合运输输入、状态操作和已有观察，避免把单条断言当成可任意移动的独立字符串。这是本项目从论文得到的推论，并非论文证明了上述类比算法。[官方摘要](https://conf.researchr.org/details/issta-2026/issta-2026-research-papers/123/Towards-More-Realistic-Assertion-Generation-under-Mixed-Assertion-Scenario)。

ASE 2026 的 *Escaping the Self-Repair Trap* 提醒，按当前程序的执行通过反馈反复修补 oracle 会削弱检错能力。因此本实验不让候选实现的运行结果决定 D 的预期值；这项选择仍需独立的 oracle 有效性评价。[作者论文](https://arxiv.org/abs/2608.05917)。

真正待检验的研究假设是：**源测试中的输入—观察联合差异，能否以少量契约判断补全有用的组合测试，并比仅改变输入而保留旧断言更可靠？** 七个已知 pilot 只能用作开发集。未见项目、正确实现上的负控制、故障控制及完整失败分母，才能检验这项假设。
