# 续轮独立评价协议

本轮时间固定为 **2026-09-29 03:12:36—08:12:36 UTC**，代码基线为
`254ca6111340728a256807c60121b551ae00329c`。分母保持 17 个开发 trial；旧轮文件保持不变。
评价器不调用模型、不生成输入或修订断言、不向生成端传递隐藏 verifier 或参考补丁。

截止前最终补充：`evaluation/uniform_fresh_v2/checkpoint_11.json` 于08:12:35完成独立核验，
新增N09，v2为 **10/17、13例完整完成**；N10、P2、P4、P5在该快照未完整完成。
下文保留先前检查点的具体诊断。实际停止因脚本重试及自动审批超时延至08:18:32，
其间新增完整N10、P2不计入窗口成绩；停止记录及Git收尾见[五小时报告](relation_search_timebox_20260929.md)。

原始探索汇总 `checkpoint_07.json` 历史记录为 **17/17 见证**；本次复查发现 N08
旧见证带有未经契约保证的额外前提。随后 v2 自动生成的净化前缀新测试
`04e6ed47ff5921a625aa` 已通过独立复核，**当前累计恢复 17/17 可靠见证**；
旧 N08 测试本身仍待契约重审，不能用新测试替它背书。
旧记录的本轮新执行为 7/17、固定配置自动检出为 0/17。
本轮 P1、P3、P6、P7、N03、N04、N05 已通过独立复核。相较旧累计 11/17，补齐的是
6 个原来缺失案例；N03 是已知案例的新闭环执行。该结果混合旧见证与局部探索，
仍不能写成统一配置自动检出 17/17。

统一 warm v1 已完成全部 17 例，独立评价封存在
`evaluation/uniform_warm_v1/checkpoint_07.json`：**已确认准确检出 16/17**，唯一未确认命中为
N08。17 例完整语料、同一配置和实际阶段参数均通过核验。命名结果库存为
585 通过、1320 失败、897 执行错误、70 未观察、28 其他状态；已独立确认其中
16 条正确目标见证和 1 条错误 oracle，另 1303 条失败未裁决。这不是整体精度或
误报率估计。warm 查询了 2955 个程序候选的历史缓存，命中 17 个 parent 并恢复
17 个修订；当前 provider 调用为零。

已确认的错误 oracle 是 N05 原始 width5→100 变体仍期待短 `ba`；正确实现应保留
完整 `bar`，所以该原始失败不能报警。其模型修订副本才提供正确预期。N07 虽然
已有有效 unequal-start/equal-end 重叠见证，另外两个严格 partial-overlap 变体被
同组其他 Go 候选缺少必需参数的编译错误阻断；没有把“选中”当作“执行并检出”。

新模型请求的统一 fresh v1 已完成全部 17 例并通过配置和阶段核验，
`evaluation/uniform_fresh_v1/checkpoint_11.json` 确认 **12/17**：N01、N02、N03、
N06、N07、N09、N10、P2、P3、P4、P5、P7。P7 本轮模型产生正确预期并实际检出；
其余 11 条目标见证保留源断言，不能把它们都归功于模型修订。fresh 固定每轮
最多 16 条语义候选；P1/P6 未获得正确目标预期，N04/N05 目标 parent 未进入
语义预算，N08 旧完整前缀仍有额外前提未确认。最终阶段清单为
`evaluation/uniform_fresh_v1/stage_diagnosis_03.json`。N05 width100 仍期待短 ba 和
P1 错误键名 equal 的真实失败，均已独立确认是错误 oracle。下一轮只选新程序
候选，使未进入语义预算的旧候选失去再次被选择的机会。未审查的其他失败保留
unknown，不能由这组已确认命中直接估计总体假阴性率。

另一个 Python 低预算消融（每轮 8 条、4 轮）已完成 profile 臂的独立复核：
`evaluation/ablation_python_v1/profile/checkpoint_01.json`，**4/8**，为 P3、N01、
N02、N03。它只选择了事先声明的 8 个 Python trial，不等同于 17-case 完整实验；
其余 9 个 trial 没参加该消融。rotation 臂也完成独立复核，封存于
`evaluation/ablation_python_v1/rotation/checkpoint_01.json`，同样 **4/8**，命中集合相同。
当前证据没有支持 profile 选择比轮转有更高检出率。

后来单独冻结的异常绕过 writer 排序消融使用相同完整候选池，每例一轮、8 条程序
候选、相同 physical-edit 调度，零模型与缓存。两臂全部 8 个 Python trial 完成：
fair **3/8（N02、P3、P4）**，writer_then_fair **4/8（增加 N01）**。P4 的新有效
见证直接观察 quoted path 被保留引号，不能仅因旧 canonical ID 没入选就漏算。
N01 在本次实际调度中为 35→2；原数组的 6→2 是另一排序，不能混用。每臂都存在
一个 P4 不合格报告，其他失败没有被全量裁决。见
`evaluation/exception_write_ablation_v1/checkpoint_01.json`；该小样本结果不能推广为
总体误报/漏报率或 issue resolution rate 的改善。
整合到实际 CLI 的独立执行也完成 8 例，全部 64 个已选程序材料与 standalone
writer 臂一致，同样 **4/8**，模型调用为零；证据为
`evaluation/writer_priority_integrated_v1/checkpoint_01.json`。这是实现复现，
不是新增任务泛化证据。

N08 旧见证 `a9212ca40d6edaa912da` 的主体以两条 Sync 写入建立 `seqNum+2`
这个未写入序号，随后验证 close 唤醒，主体关系合理。但完整复制的前缀还要求
**首次提交之前** `WaitForDurability(0)` 成功；issue 仅保证零在任意提交之后成功。
源测试在候选实现上通过不能证明这个额外前提。审查记录位于
`evaluation/semantic_reassessments_v1.json`，旧 checkpoint 保持不变，新 checkpoint
将历史累计字段与 `currently_supported_cumulative_witness` 分开。新证据封存在
`evaluation/uniform_warm_v2/checkpoint_01.json`：净化前缀只保留两条 Sync 写入及
批次序号，订阅首个未写入序号后关闭 DB；实际收到 nil 而不是要求的关闭错误，
独立源控制通过。它的每测试进程、原生 Go 结果、源码哈希均已核验。随后
`evaluation/uniform_warm_v2/checkpoint_12.json` 已关联全部 17 个完成案例，固定 warm v2
为 **17/17**，完整语料、同配置、各阶段参数和真实控制/失败均已核验。此结果
使用历史模型缓存，查询 2934 个程序候选、命中 32 个 parent、恢复 34 个修订，
没有新 provider 请求。另确认 P3 加入 Alt 却仍要求 `ctrl+plus` 的源 oracle 错误；
1552 条失败候选未裁决，17/17 不代表没有误报。fresh v2 在
`evaluation/uniform_fresh_v2/checkpoint_10.json` 中确认 **9/17（N08、P1、P3、P7、N01、N02、N03、N06、N07）**，
12 例已完成，N09/N10/P2/P4/P5 仍未完成；P1 本轮
新模型请求产生了正确 END 预期，三个事件阶段都实际无事件而失败，原控制通过。
两条 N08 新测试都保留源断言，所以它们不是新模型 oracle 的增益证据。
同轮另一个 P1 模型修订错误地要求键名 `equals`，稳定的原命名应为 `equals_sign`；
它在同源控制通过后真实失败，已确认为误报，不能用正确 END 修订推断整体 oracle
准确率改善。已完成的 P6 目标进入程序与语义预算且实际发送，但批次与 singleton
均因 length 截断得到空正文；这是缺少有效模型预期，不是程序候选没有生成。
P7 的新 singleton 请求也产生了正确数字树预期并实际检出。
完整阶段证据见 `evaluation/uniform_fresh_v2/stage_diagnosis_06.json`；未完成案例
只记录当前阶段，不判漏报。

N04 已完成时，既有目标 parent 没进入语义预算；但另三个 composed 候选获得了
修改 status/name 断言的模型预期。独立检查发现这些预期在 emitted 测试中被旧
源断言覆盖，实际仍执行 `exit_code == 0` 和 `name == "X"`，所以实际 PASS 不能
评价模型提出的断言。其中 e852… 还绑定了一个失败 donor control，另两例的
全部关联控制通过。
冻结旧版本证据在 `evaluation/uniform_fresh_v2/N04_semantic_emission_gap_v1.json`；
生成记录、发射文件和实际执行必须分别核验，不能只检查 candidate JSON。
随后 main 修复后对原完整 8 候选重新发射执行，三个新 oracle 都在实际修订断言
处检出 status 错误；b7a921… 与 189747… 全部控制通过，构成两条有效 focused
见证，e852… 仍缺合格 donor 控制。独立记录为
`evaluation/semantic_emission_fix_v1/checkpoint_01.json`，不回填冻结 fresh v2 命中。

静态诊断另行封存，不混入执行命中。持久语义队列的离线反事实在已有两轮程序输入的
6 例上，目标父候选覆盖仍是 **2/6→2/6**；没有新的模型请求或检出。合并固定两轮
程序候选后，总语义判断预算 16/32/64/128 对应覆盖 **2/2/4/4（分母 6）**。
N04 目标排第 53，N05 排第 170；后者前面有来自 95 个 seed 的 161 个 shape
首代表。保存旧候选能恢复排队机会，却不自动解决这种排序饥饿。
证据为 `evaluation/semantic_backlog_counterfactual_review_v1.json` 和
`evaluation/semantic_budget_curve_review_v1.json`。

独立的 q→writer 静态原型在预先固定的 8 个 Python corpus 上，只能对 3 例的
目标 A/q 建立可排序证据。源码顺序破同分时 A Hit@10 和 q Hit@10 都是 **2/8**；
同证据层任意排序的稳健下界均为 **1/8**，可能上界均为 **3/8**。P1/P2 的解构
返回绑定、P4 的 fixture/方法结果、N03 的标量与集合长度、N04 的嵌套资源和查询
结果尚不支持。这是源测试定位评价，不代表生成测试有效或真实同对象流得到证明。
完整目标映射见 `evaluation/assertion_write_origin_census_review_v2.json`。
把同类源码绑定与路径信息渲染为输入上下文的新原型，自动处理 4625 个观察，
有 243 个可渲染上下文、245 个支持字段读。其中仅 48 个观察有 prior test-operation
路径，全部来自 N01/N02。独立核验全部原 q 和引用函数逐行及源哈希一致，
见 `evaluation/assertion_path_context_source_fidelity_review_v1.json`。这只确认
源码信息可确定性摘取；尚未给模型使用并检验推理改善，也未证明静态路径真实执行。


数值关系分桶使用另一个预先固定的 17 例完整程序候选池；其 baseline/delta/context
语义选中目标父候选的 @16 都为 **9/17**，不是执行 Hit。N05 从第 170 提升到
109，N03 从 53 降到 54，其余 15 例不变；所有例的前 16 集合保持相同。加入
上下文关系没有超过仅数值变化方向的效果。不同输入池的这项结果不能与上述
6 例预算诊断直接相减。见 `evaluation/numeric_relation_buckets_review_v1.json`。

关闭 thinking 的 32 请求诊断也只评价模型输出，不新增 pipeline Hit。独立核验
实际 payload 除 thinking 外相同：21 个请求由 enabled 改为 disabled，另 11 个
原本就是 disabled，是同参数重复。10 个独立 accepted 修订中，5 个完整 oracle
静态可成立、3 个明确错误、2 个前提未确认。对其中历史上已经独立确认正确的
5 个目标 oracle 配对，仅 P7 原样恢复为可用修订：P1 把 END 错认成 Backspace；
N05 未改变原错断言；P6 返回空修订；N04 的正确核心提议因删除诊断 message
违反 guard 而未接收。这是一次条件样本，不能把 JSON 成功率当语义正确率，也
不能据此估计总体因果效应。见 `evaluation/disabled_oracle_independent_review_v1.json`。
对同一批 32 响应离线重验，把模型省略的原诊断 message 补回后再使用原结构 guard，
只有 N04 新增一个可接收修订；其完整输入和断言与原正确见证一致。这个 admission
版本的配对保留率为 **2/5**，原冻结版本仍为 **1/5**；独立修订变为 6 个正确、
3 个错误、2 个未确认，没有新增调用、执行或 pipeline Hit。证据为
`evaluation/disabled_oracle_diagnostic_restoration_review_v2.json`。

后来另选 32 条先前已经完成但 JSON 无效的 singleton，仅关闭 thinking 重发，
32 条都得到有效 JSON；其中 16 条返回空修订。结构上接收的两条却均不正确：
N03 无质量字段应为 `None`，模型写成空串；P6 理由正确写出 5004，代码却写成
104。另一个 P1 原始提议完整有效，但被结构 guard 拒绝。完整逐条评价在
`evaluation/singleton_fallback_disabled_review_v2.json`。这次恢复了可解析输出，
没有恢复任何正确的 accepted oracle，更没有新增执行命中。

单候选 expected-slot 新 prompt 对同 32 个父样本有 14 个可请求、15 个没有可编辑
槽、3 个完整上下文超预算；未请求样本保留在分母中。14 个返回都能解析，但唯一
adapt 将旧错误 want 原样内联，11 个 preserve 的完整测试仍不合理，另 2 个回答
unknown。N03 的错误空串提议变为弃答；P6 仍保留错误 103；P1 反而丢失旧版本
正确的原始推断。此版本提高了程序对编辑位置的控制，尚未提高完整 oracle 的
正确性。证据为 `evaluation/singleton_expected_slots_review_v3.json`。
随后保持这 14 个完整 prompt、程序和其他模型参数不变，仅开启 thinking：
14 个请求传输完成，10 个有效 JSON，4 个 length 截断空正文。5 个 adapt 中，
N03 的 None、P6 的 5004、P4 的零重载数量与完整保存文本共 **4 个完整预期正确**；
P1 仍保留错误 character is None，另 5 个 preserve 的完整测试仍不成立。因此
正确 accepted 从同 14 请求的 0 变成 4，但有效 JSON 从 14 降为 10。所有 32 个
父样本仍保留分母，不能把未调用样本删除。这里只有 P6 对应已知目标见证，其他
正确预期不等于新缺陷；后续实际回放单独计量。完整审核与 wire 配对证据见
`evaluation/singleton_expected_slots_enabled_review_v1.json`。该记录也更正旧解释：
P4 detect_autoreload 的 True 表示可安全处理，同 AST 仍可返回 True；disabled
当时的 unknown 仍是弃答，enabled 将数量改成 0 的完整 oracle 则成立。
全部 5 条 accepted 随后均实际回放，并同时执行各自原 parent：原 parent 全失败，
修订后 N03、P4 两条通过，P6 正确在 5004 对 5003 处失败，P1 仍错误地要求
character 为 None。所有关联源控制通过。因此去除了 3 条 stale-oracle 报警，
得到 1 条有效 focused 目标见证，并保留 1 条误报；不能写成 4 个新缺陷。
实际发射断言与原生结果证据见 `evaluation/singleton_slot_replay_v1/checkpoint_01.json`。
进一步仅删除同 14 个 prompt 的 source_context，其余 payload 保持相同，结果仍为
10 个有效 JSON，但 4 个 accepted 只有 N05 的完整预期正确，N03 空串错误，
P1 虽推断字符值 a 正确却被固定比较符发射成 `is 'a'`，另一个 N03 长脚本只修好
日志计数，后续文件变化与子进程稳定性观察的时间前提仍未建立。对照是有上下文
4/14、无上下文 1/14 个完整正确 accepted；每条仅各一个随机样本，不足以排除
输出随机性，更不能证明未知任务泛化。这个例子也说明值推理、断言构造和完整
测试适用性需要分别评价。证据为
`evaluation/singleton_expected_slots_no_context_review_v1.json`。
无上下文版本的全部 4 条 accepted 也统一实际回放：N05 正确预期通过；N03
空串误报仍失败；P1 的 `is 'a'` 本次碰巧通过，但不能因此证明对象身份契约；
长 N03 在修好计数后推进到未同步的 stability 断言并失败，且原控制已在计数
断言失败。该回放没有有效新目标见证，见
`evaluation/singleton_slot_no_context_replay_v1/checkpoint_01.json`。





在固定全池上先排除没有 expected 槽的模型请求，并不删除其程序执行候选。
需要修改预期的五例，语义预算 @16 覆盖仍为 3/5；N04 从 48 到 43、N05 从
170 到 129，仍未进入预算。其余保留源断言即可检出的案例退出模型队列，不等于
新增执行漏报。见 `evaluation/expected_slot_eligibility_review_v1.json`。

低 reasoning effort 对照在固定启动窗中只启动并完成前 9/32 个请求，3 个严格 JSON，
4 个截断空正文、2 个纯空格，0 个 accepted 修订。不能由此说模型全错：第 3 个
请求有 7 个静态可成立的 N05 完整预期，被 helper 观察位置或诊断文本结构约束挡住；
另两个边界预期尚缺规范依据。P7 的数字树预期正确，却同时改了观察路径而被拒绝。
五个历史正确 oracle 的精确配对请求均未启动，因此其保留率未定义，不能写 0/5。
证据为 `evaluation/low_effort_oracle_independent_review_v1.json`。

真实写入来源的两组 smoke 与 baseline 的逐测试结果一致。N01 的 24 条标量读均
绑定到此前最后一次同对象、同字段写入；但五条可对齐的生成观察和控制具有相同
writer 与值，尚未出现目标预期的同 q 写入来源分歧。N02 六条复杂 headers 读全部
标为 unknown。它们验证了观测和源 q 对齐，不证明搜索改进；见
`evaluation/observed_write_smoke_review_v2.json` 与对应 native binding 记录。
随后扩展到全部 32 组，独立复核了 10 个有新 writer 的 group-q、73 条对应读，
全部有通过的同源控制，原断言和原生逐测试结果保持一致。N01 的 c8e…、N02 的
17b… 在同一原 q 处确实由正常 close 写入变成初始化 False。另两条 N02 失败控制
不属于这些观察，不能作为合格控制。73 条读包含重复及未裁决 oracle，不是 73 个
缺陷；这些观测还没有用于已执行的在线反馈搜索。证据为
`evaluation/observed_write_full_review_v2.json`。

对这些已完成 trace 作确定性状态保留，得到 14 个生成代表。独立重算投影和保留
顺序后，逐个审查完整测试：7 个 oracle 合理、6 个只是修改 status_code 输入却
仍期待 200、1 个 invalid charset 后必须先消费流的前提待确认。N01 旧目标自身
被同状态压掉，但首代表 c3a… 也正确暴露异常后未关闭；N02 目标直接保留。
这是两个已见案例上的离线压缩；不是 14 个新缺陷，也没有测量在线搜索收益。
见 `evaluation/observed_write_frontier_review_v1.json`。只有被预算实际观察到的状态
集合有限，使用精确标量值的抽象域本身并不有限。
再将状态 key 中的 writer 身份单独移除，保留 q、分配位置、对象字段与标量值，
独立从 297 条原始观察重算后，两臂全部保留决定及 14 个代表完全一致。
这批 trace 没有证明 writer 身份比标量反馈带来额外搜索保留收益；解释能力与
新增检错收益应分开。见 `evaluation/observed_writer_key_ablation_review_v1.json`。


初始化已核验旧 checkpoint08 的记录文件与哈希。初始
`results/relation_search_20260929/evaluation/checkpoint_00.json` 的状态是：
**累计正确见证 11/17，本轮新执行正确见证 0/17，固定配置自动检出 0/17**。
旧 11 例未被伪装为新配置运行。

下面表格保留 `checkpoint_07` 之前的探索状态；正在运行的统一 campaign 进度以上述
单独评价文件为准。

| Trial | 继承正确见证 | 本轮正确见证 | 本轮统一配置 |
|---|---|---|---|
| P1 | 无 | 源构造 + 局部 oracle | 未运行 |
| P2 | 有 | 无新执行 | 未运行 |
| P3 | 无 | 源构造、保留断言 | 未运行 |
| P4 | 有 | 无新执行 | 未运行 |
| P5 | 有 | 无新执行 | 未运行 |
| P6 | 无 | focused oracle | 未运行 |
| P7 | 无 | focused oracle | 未运行 |
| N01 | 有 | 无新执行 | 未运行 |
| N02 | 有 | 无新执行 | 未运行 |
| N03 | 有 | 两轮小预算闭环 | 未运行 |
| N04 | 无 | 全 5 候选 oracle 子流程 | 未运行 |
| N05 | 无 | focused oracle | 未运行 |
| N06 | 有；历史关系重建 | 无新执行 | 未运行 |
| N07 | 有 | 无新执行 | 未运行 |
| N08 | 有 | 无新执行 | 未运行 |
| N09 | 有 | 无新执行 | 未运行 |
| N10 | 有 | 无新执行 | 未运行 |

## 三个统计不可混用

1. **累计正确见证**：旧确认见证与本轮确认见证的并集。用于追踪交付是否完成。
2. **本轮新执行正确见证**：必须提供本轮实际执行 manifest、准确测试源哈希、命名结果和独立语义复核；原源控制必须通过。受限 fixture 或人工编写测试可以单列交付，但不能据此声称自动 pipeline 成功。
3. **固定配置自动检出**：在上一项之外，必须来自登记的完整输入 corpus、同一全局配置与代码快照，并在该配置的候选列表及执行索引中出现；由独立证据确认测试未经人工语义修补。人工修改 assertion 后重跑不得计入此项。

“完整 corpus”指本轮登记的每例现成 `batch7/<case>/corpus.json`，不是声称穷尽公开仓库或全部历史中任何可能存在的测试。需要扩充 corpus 时另登记统一版本，不能静默替换个别案例的输入。各语言采用相同全局配置中声明的语言前端和执行规则。单例定制选择、不同 budget 或临时修补 oracle 不得混入同一配置。

N06 即使由自动算法重新生成并在新配置执行，仍标为“历史已经验证过的关系”。不得计作首次补出从未存在的 combination。N05 必须验证语义输出或其他有契约依据的判别，不能只用输出长度或成功状态。不得用 candidate 的实际结果构造正确期望。

## 现有结果接入

新的 `scripts/evaluate_relation_search_continuation.py` 复用旧评价器的命名报告与语义证据检查，不修改任何旧冻结脚本。交付和 review 沿用旧格式：测试源码、实际 Docker manifest、`runs_json`，以及 `scenario_hit / correct_oracle / target_failure_match` 三项带证据的独立结论。

新交付的执行 manifest 必须位于 `results/relation_search_20260929/` 下。
旧轮见证只在 ledger 的 `inherited_witnesses` 中出现。自动来源另增加独立评审字段
`automatic_provenance: {verdict, reason, evidence}`；生成器自称 automated 不能替代此检查。

统一运行直接使用 `run_relation_campaign.py` 输出的 `campaign.json`（下面为一行的简写）：

```json
[
  {
    "case": "P1",
    "source_corpus": ".../batch7/P1/corpus.json",
    "execution_configuration": ".../campaign/P1/configuration.json",
    "rounds": [{
      "round": 0,
      "program_prepare_manifest": ".../round_000/prepared/prepare.json",
      "prepare_manifest": ".../round_000/semantic/prepare.json",
      "candidates": ".../round_000/semantic/candidates.json",
      "runs_index": ".../round_000/executed/runs.json"
    }]
  }
]
```

评价读取旁边的全局 `configuration.json` 与 `algorithm_snapshot/`。逐例配置必须除
`case/source` 外与全局完全一致；再比较每轮实际 prepare、semantic、emit、run
stage 中的参数。仅抄写相同全局 SHA 不够：预算、源目录、模型模式、语义请求分组、
并发、运行超时都需要实际阶段记录一致。源 corpus、程序候选、模型修订后候选、
跨轮 feedback、执行报告与完整算法快照各自核对哈希。原先单轮封装格式继续兼容。

候选文件包括该配置最终选择和语义修订后的候选；其来源和断言正确性仍由独立 review
判定。相同候选 ID 在旧 focused 执行中成功，不能替代本 campaign 内的实际报告。
不同配置分别输出结果；只有 17 行同配置都完成时才标记完整 campaign。提前穷尽
候选须提供显式停止原因与空候选准备记录，缺少后续轮次不会自动当作完成。

固定配置指标进一步按本轮模型模式拆开：`warm_replay` 重用既存模型判断；
`fresh_model` 使用本 campaign 发出的新请求；`no_current_model` 本轮不调用模型。
warm replay 即使达到 17/17，也不能写成新模型请求的端到端 17/17。第三类只描述
本轮行为，并不声称历史验证测试从未使用模型。每种模式还记录实际请求次数、语义
候选数、程序候选数和已索引执行数；执行索引存在本身不等于测试正确。

目前 warm 对全部程序选中候选查找缓存，fresh 才先执行每轮 16 条的语义选择。
因此二者差异还包含语义选择覆盖范围，不能只解释成模型输出稳定性的差异。
`cache_consulted_count / cache_hit_parent_count / cache_revision_count` 分别记录缓存
咨询输入数、匹配的父候选数和重放的修订数；warm 的新语义选择数为 0，不表示它
没有使用历史模型信息。不存在缓存正确性筛选，错误的历史修订也会保留。

```bash
.venv/bin/python scripts/evaluate_relation_search_continuation.py audit \
  --deliveries results/relation_search_20260929/evaluation/new_campaign_deliveries.json \
  --reviews results/relation_search_20260929/evaluation/new_campaign_reviews.json \
  --previous results/relation_search_20260929/evaluation/checkpoint_07.json \
  --campaign results/relation_search_20260929/evaluation/campaign.json \
  --output results/relation_search_20260929/evaluation/new_campaign_checkpoint.json
```

所有结果用新文件名写入，不覆盖旧 checkpoint。`--previous` 保留本轮此前已确认的交付；固定配置命中仍只来自本次 campaign 的实际生成报告，不继承 focused 的运行成功。没有新 campaign 时可省略 `--campaign`，此时不能产生固定配置命中。评价自检同时覆盖继承证据、人工修补、缺少自动来源、受限 corpus、N06 历史轴、多轮阶段参数、报告篡改、模型模式和代码快照；这些是评价器单元验证，不是新的 trial 实验。

运行失败不等于检出缺陷；编译错误、环境错误、未执行 assertion 和不适用 oracle 分开记录。尚未复核的失败保持未知。全仓库表示在真实候选项目内执行所选测试，并不表示全套测试。抽查裁决不能估计总体误报率；单轮开发案例也不能支持总体漏报率。资源并发后来按封存调度记录调整，各 campaign 自身 worker 参数不变；并行阶段的耗时不能当严格隔离的速度对比。

17 例都是已经查看过的开发集。源码没有 case/API 特化、rename/跨实例/finally 控制
通过，只能支持这些局部机制检查，不能证明不存在对开发案例的过拟合。程序候选
能否生成、预算排序是否有效、模型 oracle 是否准确、最终是否改善 issue resolution，
需要分别评价，不能由其中一个指标替代另外三个。

## N04 oracle 子流程的完整审查

全部 5 个原候选与 5 个既存模型修订均用冻结执行器运行，没有按目标筛选。
`oracle_b3ad1954abd9e3ff05dc18d0` 的初始 row 满足 COUNT/MIN 不变量，
失败的第二次 insert 回滚后，bulk 改动同一 row 的 name，必须退出非零并恢复原状态。
实际 exit0 违反该契约；原源控制分进程通过，测试失败在修订后的 status 断言。
随后 name-one 断言未到达，不能宣称它已经观察回滚状态。

`oracle_6ab...` 虽先触发同一 status 错误，但后续 observer 对 generator 用下标，
且源控制本身失败，所以未交付为正确完整测试。`oracle_e8d...` 合法修改了初始状态，
使后续 UPDATE 没有匹配行，修订测试通过；这是无目标交互的有效对照。
其他 fixture 与旧 oracle 的失败均在 `N04_oracle_proof_review.json` 逐条记录。
修订 AST 文本与存储的 provider validation 逐字一致，无人工修测试；仍仅支持
oracle 子流程，不支持完整语料同配置的 17-case 自动检出率。

## N05 focused oracle 审查

宽度从同源测试的 5 换成 100，输入仍含内部 reset，Output 默认仍开启 preserve。
issue 要求重开 enclosing style，没有针对 fits 的例外；全部 foobar 都应保留，
bar 前重开 bold，结尾关闭活动样式。硬 if guard 实际比较完整预期字符串。
原窄宽控制分进程通过，生成测试实际缺少重开和末尾 reset，候选 early return
与失败相符。修订来源与 provider validation 完全一致。错误消息仍打印旧的短
want 变量（ba），因此诊断文本有残留；它不是执行时比较的 oracle，已明确区分。
此 focused 请求证明新增见证和 oracle 修订可行性，不计统一配置自动检出。

## P3 源构造组合的两个候选

完整登记 corpus 机械生成两条候选，全部执行，原源控制分进程通过。
`constructor_a6ca3df360181aacc56d3010` 同时给 modifier list 和 key string 加入 Shift，
保持 `shifted_key="plus"` 及原 `ctrl+plus` 断言。[Kitty 官方协议的 key codes 说明](https://sw.kovidgoyal.net/kitty/keyboard-protocol/#key-codes)
明确把 ctrl+shift+equals 与 ctrl+plus 对应起来，issue 同样要求 shifted alternate
shortcut 可匹配。实际 aliases 仅包含 ctrl+shift+equals_sign 与 ctrl+shift+plus，
因此失败确实暴露目标错误。无需改动 oracle 或调用模型。

另一个 `constructor_a7e20c3af0357f7eb45f1831` 加入 Alt，却仍断言 ctrl+plus。
它错误丢弃了 Alt 修饰键，不能算缺陷发现；原控制通过也不能使该断言合理。
两条候选的正负结论分别冻结在 `P3_constructor_reviews.json`，没有只保留失败中的正例。
这一结果证明源构造子流程可生成有效测试，并不证明统一自动闭环配置已经覆盖全部案例。

## P6 捕获状态的共享与转移

`oracle_66628a829ffed4a2e7a01eae` 将 `[counter, counter]` 整体转移到 B，
在 A 中先调用两次，转移时捕获状态为 n=2。B 的全局 g=5000；依次调用两个数组成员，
应观察同一份捕获状态的 n=3、n=4，即 5003、5004。实际第二次仍为 5003，
说明递归转移把共享捕获拆开了。这个 oracle 是从 issue 的脚本调用语义、捕获快照和
跨实例隔离要求推导的，并非把实际输出当真值。原源控制分进程通过。

局部修订精确匹配成功的 `oracle_attempt2/P6_request/validation.json`；
attempt1 的 JSON 失败没有被当作模型批准。候选已把最后一个调用从 A 改为 B，
所以它本身不再验证 A 状态不变；源码中的旧 A 注释不能当执行证据。

## P1 事件阶段与功能键编码

全部两条源构造候选与一条模型 oracle 修订均执行。合法的 End 编码与事件阶段组合
`CSI 8;1:<type>~` 在 press、repeat、release 三个参数下均没有产生事件。
修订测试 `oracle_4be3957f8a93b8d277a32f8e` 将 key 期望从 a 改为源测试定义的 end，
保留所有 phase 断言；[官方协议](https://sw.kovidgoyal.net/kitty/keyboard-protocol/)
支持功能键编码和 modifier 中的 event-type。其原源控制三个参数均通过。
实际失败是保留的单事件解包条件，因此只声称检出合法事件丢失，不能声称已直接
观察到错误 phase 字段：后续 key 和 phase 断言均未到达。

未经修订的同输入候选仍期望 a，完整 oracle 不正确，拒计。另一条将 text-only
CSI-u 帧迁到 End CSI-tilde 的候选不满足原 text-only oracle，同样拒计。
第二条候选的模型输出未形成合法 JSON；这一失败完整保留，不当作模型认可。

## N03 实际在线反馈的双臂检查

`N03_profile_v1` 与 `N03_rotation_v1` 均执行 2 轮，完整 corpus，首轮预算 8。
真实 runner 的顺序是控制、原测试采样、生成测试，分别使用独立进程；不再依赖
事后把原测试 trace 排到变体之前。source-stable 的 3 个观察位置证实 d1/d2
两绑定变为 d1/d1 同绑定，exitcode 仍为 0，moved 长度从 2 变为 1。
这里测量的是 Python Path 对象 identity，不是一般文件系统资源等价。

两臂均执行 10 个变体、10 个原测试采样与 6 个控制，第二轮由实际合格父候选生成
2 个复合变体。失败控制的候选不具备父候选资格。两臂选择的变体 ID 相同，
第二轮新增 profile 均为 0，因此没有观察到 profile 引导的收益。48 个总 profile
包含不合格 fixture 的观测，不是正确性或检出率。独立可重算检查及 SHA 位于
`N03_closed_loop_audit.json`，已知目标 f993… 的新执行另计入本轮见证。

## P7 执行非恒等变换的递归组合

`oracle_ebb135944d952ba191c86d90` 对整个递归 object 包含的 pipe 加入非恒等变换，
把每个 value 字符串变成其长度；Recur 指向完整 schema，所以根、子和孙层均需
执行该变换。输入的四个字符串长度都为 1，显式数字树期望由输入与 pipe 语义推导。
原控制独立通过；生成测试先通过自引用 identity 检查，再在 parse 结果断言失败。
原生 JSON 直接显示根值仍为 a，未变成 1；省略的后代差异不能称为逐个直接观测。
后续 invalid nested safeParse 断言未到达。源码 resolver 用 object runner 覆盖
pipe runner，是支持缺失变换的因果证据。局部修订与 attempt3 validation 完全相符。

08:06 的跨 campaign 汇总封存在 `evaluation/timebox_0806_snapshot.json`；
其中未完成案例不记为漏报，成本限定为已核验轮次，不把预取但尚未进入该轮次的请求混入。
