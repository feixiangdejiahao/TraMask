> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../../research/trajectory_logic_20260928/scope_design_critic.md) · [旧路径映射](../../../../results/path_map.tsv)

# Effect scope 与可执行解释：设计反审

结论：**限定 effect placement 确实能把“让 LLM 随便造 rival”缩成有限图搜索，但当前证据不支持用它作为统一核心。尤其 N09 不是简单的 block 移动，N06/N08 是直接反例。** 比较程序、找区分测试也已有强先例；创新必须落在 hypotheses 如何由 trajectory 稳定地产生，以及如何形成正确可观察判别，而不是更换名称。

本轮仅设计和阅读公开 primary sources，没有实验或外发 repository。六例原始证据见 [go_ts.md](go_ts.md)。

## 两个方向究竟解决了什么

| 问题 | 任意可执行语义解释 | 限定 effect scope |
|---|---|---|
| 候选从哪里来 | 历史版本、程序变异、LLM局部程序 | 已有 effect + CFG/AST 合法位置 |
| 生成操作 | 任意替换局部程序，难以界定 | 跨一个 region 边界移动或重路由 |
| 搜索空间 | 需要DSL/模板约束，否则不可控 | 给定 m 个 effects、每个 h 个祖先边界，单次移动至多 O(mh) 候选 |
| 反馈 | 现有 tests 下经验等价，新 tests 区分 | 相同；额外知道分歧应位于边界选择 |
| oracle | rival 不保证正确，仍需独立依据 | scope 也不保证正确，仍需独立依据 |
| 表达力 | 可包含默认值合并、边界谓词等 | 只覆盖确有同一 effect 不同执行区域的差异 |

O(mh) 只约束**一个已有 effect 的一次位置变异**，不约束组合多次移动、跨调用建模、输入合成或等价判定的总成本。

## 可真正实现的最小 scope 演算

先限于单个函数、同一个具体对象、无并发。effect 是一个现存的 call/write 及它所需的不可分割定义切片，不是自然语言“应用默认值”。给定 CFG、控制依赖树、SSA def-use 与保守的 heap read/write 集合。

1. **Guard-lift/sink。** `if(g){ E }; K` 与 `E; K`，或反向把 E 放入同层已有 guard 分支。只枚举 E 所在路径上的直接父边界，不枚举任意布尔表达式。保留被删/复制定义关系，原 guard 可保留空分支作为定位。
2. **Exit-route。** `try{ A; E } finally{}` 与 `try{ A } finally{ E }`。E 的 receiver/实参必须在 try 前有定义；若只有 A 成功后才赋值，不允许把依赖它的 E 移到异常出口。该规则改变 E 是否发生于异常路径。
3. **Loop-lift/sink。** 将 E 在一个 loop 的内外移动，但 E 的 free variables 必须在新位置定义；依赖 induction variable 的 E 不能直接 lift。这个限制会排除许多“每字段 vs 整体”的口头例子，不能借同一个词掩盖新增语义。
4. **调用边界暂不作为基本规则。** 跨 caller/callee 移动需要参数替换、alias映射、调用次数、异常语义与多个 callers 的处理。它可作为一次有界 inline 后的前述规则，不能假称 type matching 已解决。

只用类型和 def/use 还不够：它们保证的主要是可构造/可编译，不能保证移动不改变计算值、异常、资源所有权或重入行为。对于 crossed statements，至少检查被搬定义不会被后续覆盖、receiver identity 可追踪；产生的新 crash 也不能自动认作有价值的语义解释。我们**有意**允许跨控制边界改变执行次数，所以不能套用要求语义保持的 compiler code motion 合法性，否则只会得到等价程序。

例子：`if(enabled) s=normalize(s); return s` 的两种 placement，在全部 `enabled=true` tests 下无法区分。移动规则直接给出 `enabled=false` 的差异控制条件，再从现有 normalize 的非平凡输入复用 s。无需生成全新 reference implementation；但是否 disabled 仍该 normalize 必须由契约裁决。

## 省搜索应来自哪里

对于两个相邻 placement，可计算它们 execution guard 的对称差 `G_old XOR G_new`；从已有进入 E 的 test 出发，先改动该 guard 的反向依赖输入。比随机改整个 test 更具体。若这个条件满足而 effect 的值没有改变，需要已有非平凡 operand；若内部值变了但输出没变，转向 forward slice 上的观察构造。

可依次剪枝：输入不可赋值／heap位置不匹配；现有 tests 已区分（无需新组合）；scope对称差不可达；effect被后续覆盖；所有可达公开 observations 相同。最后两项只能在有限分析能力内证明，否则保留 unknown。最短区分 test 可定义为在已知 test skeleton 上最少 AST edits；它有明确优先队列，却不保证全局最短可执行程序。

该算法确实减少**候选程序位置**与**首先改变的输入节点**，而非一句“先静态分析再LLM”。但 observer 链与复杂输入生成依然要有实在的构造操作；不能把这些再次命名为 `materialize_witness` 就认为解决了。

## 六例的反例审计

| 案例 | scope 是否自然表达 | 不能省略的困难 |
|---|---|---|
| N05 | 弱支持：early return 绕过 token processing | reopen 在解析循环中，依赖 active style、token；不存在独立 `reopenAll(s)` 可直接前移。搬整循环/去early return还会受 tail预算影响，可能改变已有 fitting+tail 语义 |
| N06 | 不支持核心bug | actual `isStructural(a) || isStructural(b)` 对比 AND/精确footprint；不是同一 effect 位置。已有target脚本只需恢复并重跑 |
| N07 | 不支持直接生成 | 要换扫描冲突检测的区间关系，移动输出 effect 不能自动构造 overlap 算法或输入 |
| N08 | 明确反例 | `target <= high` 对比 `<`；所有effects位置不变；普通 relational-operator mutant 已足够提供 rival |
| N09 | 看似scope，实际不成立 | candidate 是 `if(hasParams)return params; return defaults`；将 defaults return 移进/移出不存在的 per-field loop，不会得到 `{...defaults,...params}`。需要新的合并运算、字段投影或presence谓词 |
| N10 | 有限支持 | default normalization 在别的工具消费raw mode；可移/接已有normalize但不是新guard自身位置，跨helper参数流需要实际连接 |

因此即便对本组六例，scope不是“同一个简单操作解释大多数现象”。若为 N09 添加 fieldwise merge，为 N08 添加边界变异，为 N06 添加AND/OR，就退回多个 fault templates 的集合。这样的工具可以有用，论文主贡献却不能还叫 effect placement。

## 已有技术会怎样质疑创新性

1. **Statement movement 和 type-compatible donor 已是 APR 构件。** TBar（ISSTA2019）FP14 就是 Move Statement，其模板体系也包括替换、条件与表达式变异；因此“搬语句+类型过滤”本身不是新贡献。[TBar 原论文](https://www.darkrsw.net/papers/ISSTA2019.pdf)
2. **区分经验等价的候选程序也不是新核心。** Fix2Fit（ISSTA2019）联合生成 patches/tests，以测试区分候选patch行为，用crash-freedom裁决。我们不能把它描述为首次用 version space 指导测试；我们的 oracle 也远弱于 crash oracle。[作者工具与论文说明](https://github.com/gaoxiang9430/Fix2Fit)
3. **2026已有直接相邻工作。** Beyond Coverage（OOPSLA2026）中 SUNG 用LLM生成语义mutants，RAGTIME用survived mutants指导测试增广，包括non-standalone methods。因此“LLM产生少量局部解释，再找杀死survivors的测试”已非常接近现有路线。[正式论文 §3](https://doi.org/10.1145/3798251)
4. **按已有输入保持等价也是旧思想。** EMI将相对于一组输入等价的程序变体用于编译器验证；我们的目的不同，但“只在已知tests上相同”不应被包装成新抽象。[作者 EMI 项目与 PLDI2014 论文](https://web.cs.ucdavis.edu/~su/emi-project/)

这些来源支持相似技术已经存在，不支持它们能直接解决本任务；反过来，现有技术存在也不等于新场景无学术价值。应明确提出并验证新增机制。

## 我更推荐的收敛方式

保留“区分测试”作为**搜索目标**，暂不把它当新学术贡献；不把 scope 强推为全部17例的抽象。首先让 hypotheses 只来自可复原的实际代码编辑和明确到代码/数值的历史分歧，对这些解释先做一次可复查的自动转换闭环。scope只作为其中一个可严格定义的受限构造器。

这会自然区分两个工作，而非混合评价：N06是失效历史证据重验证；N07是把已出现的反例约束转为真实执行；N05是契约歧义裁决；N09才需要合成未出现的字段混合。若论文目标仍是自动提高combination覆盖，必须证明程序分析能够从**成功验证的共同偶然前提**产生新的构造，而不能只靠历史agent已经说过答案。

一个值得另外验证的窄核心是“共同来源坍缩”：成功tests把两个应独立的来源总赋同一种role或同一种值形状，程序因此把它们合并判断。N09 hasParams代表整条record就是候选。但如果把发现这样的前提交给LLM，仍有原先问题；最低要求是以 def-use 恢复输出各field来源，以两条tests的AST anti-unification产生可执行部分record，而不是列出语义标签。N08/N07不自然属于此核心，应承认边界。

最强建议仍是：**先选择能给出低成本、可复现生成操作的现象簇，再用剩余cases反驳其适用边界；不要为了17/17把多个根本不同的问题揉成一个万能抽象。** 目前 scope 可以成为可验证的窄子方法，尚不足以替代旧方案的统一核心。
