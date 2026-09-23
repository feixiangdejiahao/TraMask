**2026 年软工研究论文依据与本课题的贡献边界**

方法修订：当前方案已收缩为 [关系残差切片](method_design.md)。下文保留 2026 文献的审阅依据，末尾补充与新算法直接相关的早期工作。

核验日期：2026-09-23。以下六篇均在 ICSE、FSE 或 ASE 2026 官方 Research Track / Research Papers 页面中列出。ASE 2026 尚未召开，本文将其表述为已收录、已列入议程，不表述为已经报告。这里只做针对本问题的文献审阅，不是覆盖全年论文的系统综述，也不保证某个设计能够被顶会接收。

**1. MR-Coupler，FSE 2026：从程序耦合恢复可测试关系**

论文：*MR-Coupler: Automated Metamorphic Test Generation via Functional Coupling Analysis*。[官方收录](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/200/MR-Coupler-Automated-Metamorphic-Test-Generation-via-Functional-Coupling-Analysis)，[作者预印本](https://arxiv.org/html/2604.10126v1)。本次阅读了全文相关方法、验证和局限段落，重点为 §3.1–3.3。

原论文机制：通过签名相似性、调用联系和字段读写关系选择方法对，再由 LLM 生成 metamorphic tests，以输入扩增和 mutation 辅助筛选。它已直接覆盖“程序分析找关联，LLM 生成测试”的主线。

本课题的推论：必须超越方法对的相关性，判断现有 suite 是否已经在特定 guard、对象和顺序下检验该关系。P3/P7 还需要区分能力分析。另一个关键差异是 candidate 可能已错：不能把它的输出当真值，或自动删掉所有在 candidate 上失败的生成测试。论文的原版本/mutant 通过率筛选也有无法区分的情况，不能迁移成 oracle 正确性保证。

**2. SAINT，ICSE 2026：操作顺序必须有依赖依据**

论文：*SAINT: Service-level Integration Test Generation with Program Analysis and LLM-based Agents*。[官方收录](https://conf.researchr.org/details/icse-2026/icse-2026-research-track/143/SAINT-Service-level-Integration-Test-Generation-with-Program-Analysis-and-LLM-based-)，[作者预印本](https://arxiv.org/html/2511.13305v2)。本次阅读了全文相关模型构建和生成部分，重点为 §3。

原论文机制：针对 Java 服务建立 endpoint model 和 operation dependency graph，表达参数、资源、生产消费及数据库交互造成的约束，结合 LLM 生成端点和场景测试。

本课题的推论：test 的连接必须携带实体身份和先后关系。P6 的 write/read 必须访问同一 cell；LangChain 补充样本还需要区分同 key 的不同执行世代。单有调用先后不够。本方案拟从服务工作流扩展到语言库的字段、堆关系与观察义务，但“有状态序列生成”本身已有充分先例。

**3. Feature-Focused Test Generation，ASE 2026：特征需要可追溯的形式来源**

论文：*Feature-Focused Test Generation*。[官方收录](https://conf.researchr.org/details/ase-2026/ase-2026-research-track/183/Feature-Focused-Test-Generation)，[作者说明](https://jzamudio.com/feature-focused-test-generation/)，[DOI](https://doi.org/10.1145/3832783.3837479)。本次依据官方摘要和作者方法说明，未对全文所有细节作审阅。

原论文机制：Compás 从输入规格的备选项、可选项提取 feature model，按所选特征约束并裁剪规格，使生成输入保持有效，并建立特征与代码覆盖的联系。

本课题的推论：feature 不应只是 LLM 写出的标签。P1 的编码家族应指向语法分支，P3 的 shift 应指向位运算，P6 的共享应指向 capture binding。许多 repository 没有正式输入规格，因此从测试和实现恢复部分域及约束是实际难点；恢复不到时应标 unknown。不能据此声称 Compás 完全不涉及特征组合。

**4. Every Scenario Matters，ASE 2026：需求与实现提供互补信息**

论文：*Every Scenario Matters: Scenario-Guided White-Box Testing for Static Code Checkers Powered by LLMs*。[官方收录及摘要](https://conf.researchr.org/details/ase-2026/ase-2026-research-track/51/Every-Scenario-Matters-Scenario-Guided-White-Box-Testing-for-Static-Code-Checkers-Po)。本次只核验官方摘要，没有将未见全文的算法细节当事实。

原论文机制：ScenSCT 将 checker 实现转成 CheckerIR，结合规则描述提取并验证检查场景，再通过执行反馈对齐测试、进行保持场景条件的扩增。实现提供具体条件，规则描述约束语义。

本课题的推论：建立实际程序关系图与契约要求图，不能只沿 candidate 已有的边找测试。P1 恰可能漏掉所需的 phase 传播边；如果把实现正则当完整合法输入规范，会提前排除应该发现的缺口。契约恢复仍可能不完整，需记录原文与不确定性。

**5. NESA，FSE 2026：让神经辅助位于可组合的小问题边界**

论文：*NESA: Relational Neuro-Symbolic Static Program Analysis*。[官方收录及摘要](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/103/NESA-Relational-Neuro-Symbolic-Static-Program-Analysis)，[作者 artifact](https://github.com/chengpeng-wang/NESA)。本次依据官方摘要及 artifact 说明。

原论文机制：用受限 Datalog 策略分解分析问题；语法事实交给解析，较小的语义子问题交给 LLM，并按需增量求值。其经验效果不能解读为通用静态分析的 soundness 保证。

本课题的推论：LLM 可以给未知 API 提议局部摘要或把 issue 句子映射到契约候选；符号解析、数据流连接、对象身份和 witness 检查应由可审计程序完成。模型建议与精确 AST 事实必须使用不同置信标记。本轮用户禁止代码外发，因此这种辅助只是方法设计，未调用。

**6. Evaluating LLM-based Regression Test Generation，FSE 2026：变更意图与生成预算是强基线**

论文：*Evaluating LLM-based Regression Test Generation*。[官方收录](https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/54/Evaluating-LLM-based-Regression-Test-Generation)，[作者预印本，含 2026 修订](https://arxiv.org/abs/2501.11086)。本次核验官方摘要和预印本摘要/版本信息。

原论文机制：Cleverest 将变更描述、代码变化和结构化输入格式用于回归输入生成，并结合反馈；ClevFuzz 用生成输入进一步驱动 fuzzing。论文也研究变更描述表达能力的影响。

本课题的推论：不能只对比没有 issue 信息的随机生成器。直接 LLM、依赖引导和 DCC 应拥有同样可见信息及可比预算。最终必须比较真实 issue 修复收益，不能把更多 coverage 或更多失败测试直接等同于更高 resolution。

**7. 从这些工作提炼“值得研究的 insight”**

以下是本次审阅后的判断，不是会议官方接收标准：

1. **解释一个稳定的失效机制。** 例如“孤立验证通过，但关系在同实例/同世代下未被有区分力地检验”，需要多个独立 issue 支撑。
2. **给出决定算法行为的抽象。** P6 的 alias 等价类和 P3 的位集合直接改变候选是否有效；如果移除抽象仍能得到同样结果，它就不应成为中心贡献。
3. **让抽象解决具体技术障碍。** 例如减少无意义组合、恢复合法前置条件、保留真实 bug 所触发的失败测试、在可控预算内构造序列。
4. **提供可证伪的实证链条。** 从候选精度、关系 witness、独立 oracle 到真实修复率；失败、unknown、成本和误修复都需报告。

“更多 prompts”“换一个 LLM”“把 AST、PDG、SMT 都接起来”不是自动成立的 insight；也不能把已知的数据流覆盖、条件覆盖、关系测试、mutation 区分能力重新命名后视为新理论。正式立项前还应系统核对 test amplification、combinatorial interaction testing、heap/alias coverage、state-machine testing 及 mutation 的激活与传播准则。本次文献审阅不足以做全球新颖性断言。

**修订后的中心假设：** 对已有可执行测试关系构建残差程序，消去关系两侧共同保持的行为后，剩余输入依赖能够更准确地指出值得组合的上下文；从其他测试迁入这些输入片段，可以继承原关系 oracle 并减少无效搜索。

需通过独立样本回答：相同关系种子下，配对消去与供体重组是否比传统 pairwise、普通切片和关系符号执行减少搜索成本、发现更多真实缺陷，以及是否转化为净 resolution 提升。具体算法见 [method_design.md](method_design.md)。

**8. 方法收缩后必须面对的相关工作**

- [MR-Scout，TOSEM 2024](https://doi.org/10.1145/3656340)：从已有测试提取并参数化可执行 MR。应复用这一种子思路，不能把“从测试恢复关系”当作本方案的原创贡献。
- [MR-Adopt，ASE 2024，作者论文](https://valerio-terragni.github.io/assets/pdf/xu-ase-2024.pdf)：针对硬编码的源输入/后续输入补全输入变换，使用 LLM 和数据流辅助。说明关系种子的输入变换恢复是独立难题，不能用一个未实现的 ExtractRelation 调用略过。
- [Relational Symbolic Execution，作者预印本](https://arxiv.org/abs/1711.08349)：已经支持相关输入上的两次程序执行分析。product program 和关系求解本身不是新贡献。
- [Path-directed source test case generation and prioritization in metamorphic testing，JSS 2022](https://doi.org/10.1016/j.jss.2021.111091)：已有按路径约束生成、排序 MR 源输入的工作。新方法需与它以及直接关系符号执行比较，而不能只对比随机测试。

新的贡献检验点由此明确：**关系保持项的配对消去，能否找到比普通输出依赖更小、更有用的组合因素；将这些因素投影回已有测试，是否能以更少搜索得到有效反例。** 这是一个需要实验支持的算法假设，没有把“残差”或蜕变关系本身声明为新理论。
