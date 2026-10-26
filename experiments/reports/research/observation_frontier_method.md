> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/observation_frontier_method.md) · [旧路径映射](../../../results/path_map.tsv)

**观察前沿：面向遗漏组合测试的断言入口检索**

版本：2026-09-23，算法 v0.2。当前已实现并验证的是已有测试 A 与其断言的检索。七个发现集 pilot 的 Test Hit@10 和 Assertion Hit@10 均为 1；完整数据、消融和局限见 [实验报告](observation_frontier_experiment.md)。此前的关系残差方案保存在 [归档](archive/method_design_v2_residual.md)，不再用它解释当前已实现的排序。

**1. 一个核心抽象：观察前沿**

一个测试经常连续断言对象创建成功、中间字段正确、组合计算正确。这些断言可能都关联到同一补丁，但对组合行为的观察能力不同。方法的核心假设是：**寻找组合测试入口时，应优先考虑消费了已有行为结果的观察，而不是按到达了多少修改函数排序。**

这里使用一个可计算的抽象——断言的依赖足迹 D(a)。在同一测试内部，如果一个观察的足迹严格包含另一个观察的足迹，优先选择前者。由此得到的极大元集合称为观察前沿。算法不需要 LLM 给断言生成“重要性”“测试意图”等自然语言标签。

这是检索假设，不是逻辑定理：D(a) 包含 D(b) 不意味着 a 逻辑蕴含 b。后续计算可能屏蔽错误。我们保留所有断言，只改变预算内的访问顺序。

**2. 足迹如何从程序中计算**

输入是候选代码、candidate patch、已有测试与可解析的 trajectory 脚本。检索器不读取人工目标标签、handbook、隐藏 verifier 或参考补丁。

先用 AST 提取断言，再从实际观察表达式做后向依赖查询。局部图包含赋值、调用、控制及可能的状态边。用于前沿比较的测试局部查询只跟随值边：可能修改对象的调用顺序不能单独成为“一个观察包含另一个观察”的证据。

D(a) 由两种程序事实组成：

| 程序事实 | 作用 |
|---|---|
| 测试内、值依赖上的受补丁影响调用发生位置 | 区分一次调用和把它的结果传给后续调用；相同 API 在不同位置调用仍是不同事实 |
| 被观察字段的生产者形参来源 | 区分简单字段与汇合多个字段/参数的计算结果；给不同字段的依赖提供可比较的来源 |

调用发生位置包含作用域与语法位置，不根据方法名称的自然语言含义打分。字段来源由生产函数内的字段赋值后向切片计算，当前仍是可能包含控制和状态依赖的保守摘要。跨过程查询有界，不能称为完整、精确的 SDG 或 points-to 分析。

实际值与期望值根据生产值来源区分。例如 `result == {'path': str(path)}` 中，右边含调用并不说明它是被测输出；若两侧都有生产值来源，则保留关系两侧。如果所有已解析分派目标都正常返回同一个字面量，接收者和参数不作为该返回值的来源。

**3. 前沿偏序与算法**

对同一测试中的两个断言 a、b，定义 a 在 b 之后处理，当：

```text
D(a) 严格包含于 D(b)
    或
D(a) = D(b)，且 a 只检查错误/空值状态，b 检查返回值
```

第二种情况沿用已有断言提取器的 outcome/incidental 分类，解决 `NoError(err)` 与返回值断言来自同一次调用、足迹相同的问题。它是局部检索偏好，不代表错误断言无用；仅有错误断言的测试仍保留。

反复取偏序的极大元，得到第 0、1、2……层前沿。同层断言按参数化期望能区分的结果数 q(a) 降序处理，再按源码位置稳定打破平局。q(a) 来自参数表和受限常量表达式解释，不执行仓库代码。例如 `phase == expected_phase` 的三个不同期望比单个固定期望提供更多区分。本实现仅恢复能够静态解释的 Python 参数化期望，未知按 1 处理。

```text
for each test t:
    extract assertions and value-dependence footprints
    repeatedly remove maximal observations to form frontier layers
    order assertions by (frontier layer, descending expected diversity, source order)

order tests using the existing patch/keyword baseline
emit one assertion from each test in order
repeat until every assertion has been emitted
```

跨测试顺序复用既有基线，不引入新的训练参数：改动测试 +200、改动文件 +100、历史脚本来源 +15、调用名与补丁新增标识符匹配计数。每轮每个测试贡献一个断言，防止一个大测试先耗尽断言预算。基线与预算轮换属于实验支撑，不作为新的学术贡献。

实现入口：[frontier.py](../../../anchor_retrieval/frontier.py)。旧的输入差异数量、观察字段全局轮换和受影响函数计数不参与新算法的断言优先级。原供体分析仍输出为后续生成阶段的候选证据。

**4. P3 示例：为什么能选到组合观察**

同一测试依次检查事件数量、`key`、`shifted_key` 和 `aliases`。

```python
assert len(events) == 1
assert event.key == "ctrl+equals_sign"
assert event.shifted_key == "plus"
assert "ctrl+plus" in event.aliases
```

局部解析调用是这些断言的共同来源。生产代码中，`key` 来源于构造参数 key，`shifted_key` 来源于 shifted_key，而 aliases 的计算汇合了 key、modifiers、shifted_key 等来源。于是 aliases 的足迹包含前面中间观察的足迹，处在最前一层。算法选择这个断言不依赖“alternate”“metadata”等测试名词。

P2 中 character、modifiers、base_key 都是不可相互包含的前沿候选，当前根据源码顺序选择 character。这里必须承认：算法没有证明 character 比另外两个候选更适合组合；首次命中的效果也受到既有测试书写顺序影响。

**5. 与软工论文 insight 的关系**

MR-Coupler（FSE 2026）从程序中可恢复的功能耦合出发缩小方法对空间，再生成和验证关系。这启发我们让抽象直接决定选择操作：本方法用观察依赖的偏序决定先检查哪些断言，而不要求所有测试都先转成蜕变关系。[官方论文页面](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/200/MR-Coupler-Automated-Metamorphic-Test-Generation-via-Functional-Coupling-Analysis)

断言切片与 oracle 依赖分析本身已有先例。SELERTION 从断言及其依赖语句构造选择单元；Oracle-Based Regression Test Selection 使用 program chopping 关联改动与内部 oracle。我们复用这些基础，不能把“提取断言加切片”宣称为新的贡献。[SELERTION 作者论文](https://arxiv.org/html/2403.16001v1)、[Oracle-Based RTS 作者页面](https://digitalcommons.unl.edu/cseconfwork/256/)

Dodona 已用交互与依赖排序待观察变量；PSODS 也研究数据依赖下的 oracle 数据选择。因此，观察前沿目前是一个受到实验支持的原型抽象，尚未证明是全新的理论。需要进一步检验的课题是：**对 agent 产生的大量验证断言，依赖前沿是否能比变更优先、直接断言切片和普通 oracle 选择更有效地找到可扩增的组合观察。** [Dodona 作者机构页面](https://pure.kaist.ac.kr/en/publications/dodona-automated-oracle-data-set-selection/)、[PSODS 论文](https://www.mdpi.com/2079-9292/10/2/110)

当前消融支持前沿分析具有独立作用：保留同一测试顺序及预算轮换、去掉前沿关系后，Assertion Hit@10 从 7/7 降至 2/7。它并不证明新颖性或未见数据上的有效性。

**6. 和组合生成的衔接与本轮边界**

A 的观察足迹提供组合发生的位置；现有供体索引提供其他测试在同一输入位置上的取值。未来生成可以围绕同一抽象寻找“某个行为产生的数据被另一个行为消费，但尚未在该观察下共同检验”的输入/调用片段，并迁入 A。

仍需单独解决合法输入约束、oracle 的适用条件、同对象状态与闭包共享等问题。程序依赖不能证明变换后原断言仍成立。P6/P7 的旧测试尤其只有入口价值，不能自动继承内部共享或非恒等转换所需的 oracle。本轮未实现组合生成、未执行被测仓库、未测 issue resolution rate；不把检索指标替代这些最终指标。

**7. 可复现性与防止针对样本修改**

第一次实现前写下 [算法约定](observation_frontier_plan.md)，保留所有开发轮次和 Git 版本。目标标签及原七例代码/补丁/trajectory 哈希保持不变。没有 pilot 名称、目标行号规则、issue 文本模型分类或权重搜索。

38 个回归检查包含独立的聚合字段、后续消费、多态常量、状态顺序、反向断言、参数化 oracle、变量改名和无关语句例子。对七例提取清单做候选顺序打乱和测试名称元数据混淆；另运行完全不读取 trajectory 的版本。它们检验具体稳定性，不构成未见 issue 上的泛化证明。七例属于四个 issue 家族，且均已被人工分析，仍是方法发现集。
