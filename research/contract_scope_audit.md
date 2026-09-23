**v6 生成范围与信息边界审计（2026-09-23）**

结论：在本次检查的生成路径中，没有发现读取人工目标、handbook、reference patch、隐藏 verifier 或执行结果来构造测试的行为；没有发现按 pilot ID、目标测试名或固定目标行号分支的生成规则。当前证据支持“冻结生成器的输入隔离和原断言保留”，**不支持“没有开发集过拟合”“关系已经证明”或“7/7 代表零误报”**。

审计对象是 [contract_v6/generation.json](../results/combination_testing/contract_v6/generation.json) 对应的冻结实现，生成时间为 09:18:28–09:18:29 UTC，Git 基线 `c097f68ba8b0fecab3f24f3ee1355667a3e1a331`，另有冻结文件哈希记录工作区修改。只读检查代码、请求/响应缓存和生成产物；使用原缓存在内存重新生成，没有重新调用模型、执行被测仓库或读取 reference patch。

**实际验证**

| 检查 | 结果与边界 |
| --- | --- |
| 冻结完整性 | 16 个 implementation snapshot 文件、7 个 case manifest 和全部生成文件均与记录的 SHA-256 一致；审计时当前实现也与快照一致。 |
| 重新生成 | 7/7 case 的生成文件与冻结文件逐字节一致。对生成及 evidence 构造开启 Python `open` 审计，禁止人工目标、handbook、reference/verifier 和执行结果路径；没有触发禁止读取。此检查覆盖本次实际执行路径，不是对任意输入的隔离证明。 |
| 模型实际输入 | P1–P3 缓存请求均只有 issue、检索前十测试、候选 API docstring、公开 wire facts 和排除项说明；`implementation_bodies_included=false`，没有 `candidate_sources`。重新构造 evidence 与缓存完全一致，测试也与检索产物前十项一致。 |
| 原断言保留 | P1/P2/P3 的 98/90/21 条准入 obligation，均能在静态 facts 中找到完全相同的源输入、来源跨度、field、op 和 expected。模型只返回准入布尔值，未改测试的 expected。 |
| 全部已有 predicate 缓存 | 审计时共 20 份 `predicate.py`，均与相邻 `response.json` 按保存规则去除 Markdown 围栏后得到的字节一致；有 manifest 的 17 份全部哈希匹配。v1 三份缺少 manifest，因此只能核对响应一致性。失败的 v6 首轮请求没有 predicate，不计入 20 份。 |

本轮实际使用的是 `results/combination_contracts/v6_retry/`。三份请求哈希也均匹配；predicate 字节及哈希与冻结 manifest 内嵌内容完全一致：

| 缓存 | predicate SHA-256 |
| --- | --- |
| P1 | `e186fae09a11e08d0b127dd50ecbfddf2144c4b40032b286141b145273985c3d` |
| P2 | `1dbbe3c5accc2aedbb5bb97c4a357a7475fe087fe2cf17bf85292362cf0b0525` |
| P3 | `26100f0b2cb328c678617c121edb237fbccdbe73fdbd0a0ad56c45132f992146` |

P1 缓存最初因 `NamedExpr` 被旧解释器拒绝；后来解释器增加局部赋值表达式支持并重新验证，没有重写模型字节。该解释器变更有独立的短路求值和输入不变测试，但应保留最初拒绝记录，不能称为首次直接成功。

**边界与适配器先验**

`contracts.build_evidence` 默认仍在本地读取候选 patch 以定位文件；`contract_documentation` 解析这些文件，只把匹配观察字段的 docstring 发给模型。候选实现还在本地用于提取调用方式、输入常量和键表。因此准确表述是“默认不向模型提供实现正文”，不能表述为“方法不使用候选实现”。API 文档也来自候选仓库，并非独立可信规范。

CSI 分词、Unicode scalar/phase/modifier 范围及官方 producer 不为 functional key 生成 alternate，属于公开协议域适配器；没有给出目标输出值。`unsupported` 只表示缺少所支持的 producer 域，不要求接收器拒绝该输入。依据见 [Kitty 协议](https://sw.kovidgoyal.net/kitty/keyboard-protocol/) 和 [producer 编码](https://github.com/kovidgoyal/kitty/blob/master/kitty/key_encoding.c#L253)。这些链接中的 producer 指向可变的 master，复现实验应使用本轮缓存的 facts，不能假定未来源码行号仍相同。

IPython 的 `run_line_magic/run_cell_magic` 参数位置、Tengo 的 host/guest/clone 接口、Valibot 的 `recursive/recursiveAsync` 和有限展开规则，属于**人工编写的库适配器及关系假设**。它们按语法/API 匹配，未按案例身份匹配；但不是自动从任意仓库发现的通用语义。case ID 只用于读取仓库、检索产物和对应缓存。前十断言的来源行号是检索结果动态传入的位置，不是固定目标行号规则。

仍有明确覆盖限制：`protocol.py` 在输入域检查之前已排除 non-u 形式携带 alternate 或 text 的候选，因此不能声称 v6 覆盖所有 functional-key + text 输入。`protocol_inputs.py` 本身没有全面禁止 functional + text 或 code-zero + modifiers。一次只改一个坐标、128 条候选预算、形状采样、有限语法识别和库模板也都会造成漏报。

**语义准入仍是未证明的假设**

三份 predicate 没有案例 ID、测试名或样例专用 codepoint 常量；数字主要是协议位掩码和 Unicode 范围。但它们包含具体 API 字段、相位字符串、按键名映射及 shift/alias 规则。尤其 P3 的整张标点命名表、P2/P3 的 Unicode `upper()` 规则、部分“base_key 不受 modifiers 影响”的 guard，没有被程序分析证明对新输入域成立。没有样例枚举特判，并不等于这些语义假设能够泛化。

保持 expected 原样，确实避免了把候选执行结果直接当作正确期望；但模型 predicate 内部会计算相位、字符或按键名再与 expected 比较。因而它承担了**部分输出语义推断**，不能宣传为“模型完全不涉及 oracle”。AST 限制只约束可执行能力；现有断言一致性检查只做有限反证。`not_falsified` 不等于 sound。允许的 alternate 空位也可能让某些 predicate 的 `int("")` 报错，当前实现会记录后放弃该提案，而不是自动获得可靠语义。生成 harness 另有单包产生单事件的适配器前提及 tuple/list 规范化，它们也不是模型证明的性质。

结构适配器通过同一候选实现的两条执行 route 比较观察值，不读取独立 reference 来生成 expected；因此能检查不一致，但两条 route 同时出错时仍可能通过。

**论文可以与不可以声称的结果**

可以报告：在这 7 个 discovery cases 上，冻结版本生成后统一评价，known-target detection 为 7/7；默认模型输入不含实现正文，实际生成器没有读取评价目标或 reference 信息；固定缓存能够逐字节重放。

不能据此报告零误报、所有遗漏组合均被找到、跨项目泛化、live-model 输出确定性或 issue resolution rate 提升。[原始评价](../results/combination_testing/contract_v6/evaluation.json) 仍记录 3 个 reference alarms、9 个 reference control failures、22 条被控制条件阻断的比较。reference alarm 也不自动等于真实误报，须独立裁决；本审计不据这些差异修改或删去 obligation。

这些案例参与了方法发现；prompt、语义条件和输入域是在多轮观察后调整的。公开协议依据使新增域规则可检查，却不能把这种开发历史变成预注册盲测。还需要冻结适配器与 prompt 后的独立案例评价，以及分别统计适用域、准入错误、生成覆盖和真实缺陷检出，才能讨论泛化与可靠性。
