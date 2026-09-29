# 续轮独立评价协议

本轮时间固定为 **2026-09-29 03:12:36—08:12:36 UTC**，代码基线为
`254ca6111340728a256807c60121b551ae00329c`。分母保持 17 个开发 trial；旧轮文件保持不变。
评价器不调用模型、不生成输入或修订断言、不向生成端传递隐藏 verifier 或参考补丁。

原始探索汇总 `checkpoint_07.json` 历史记录为 **17/17 见证**；本次复查发现 N08
旧见证带有未经契约保证的额外前提。随后 v2 自动生成的净化前缀新测试
`04e6ed47ff5921a625aa` 已通过独立复核，**当前累计恢复 17/17 可靠见证**；
旧 N08 测试本身仍待契约重审，不能用新测试替它背书。
旧记录的本轮新执行为 7/17、固定配置自动检出为 0/17。
本轮 P1、P3、P6、P7、N03、N04、N05 已通过独立复核。相较旧累计 11/17，补齐的是
6 个原来缺失案例；N03 是已知案例的新闭环执行。该结果混合旧见证与局部探索，
仍不能写成统一配置自动检出 17/17。

统一 warm v1 已完成全部 17 例，独立评价封存在
`evaluation/uniform_warm_v1/checkpoint_07.json`：**准确检出 16/17**，唯一未检出为
N08。17 例完整语料、同一配置和实际阶段参数均通过核验。命名结果库存为
585 通过、1320 失败、897 执行错误、70 未观察、28 其他状态；已独立确认其中
16 条正确目标见证和 1 条错误 oracle，另 1303 条失败未裁决。这不是整体精度或
误报率估计。warm 查询了 2955 个程序候选的历史缓存，命中 17 个 parent 并恢复
17 个修订；当前 provider 调用为零。

已确认的错误 oracle 是 N05 原始 width5→100 变体仍期待短 `ba`；正确实现应保留
完整 `bar`，所以该原始失败不能报警。其模型修订副本才提供正确预期。N07 虽然
已有有效 unequal-start/equal-end 重叠见证，另外两个严格 partial-overlap 变体被
同组其他 Go 候选缺少必需参数的编译错误阻断；没有把“选中”当作“执行并检出”。

新模型请求的单独增量评价 `evaluation/uniform_fresh_v1/checkpoint_05.json` 确认
N01、N02、N03、N06、N07，当前 **5/17**，已经完成 N01—N07。这五条目标见证保留原源断言，
所以不能据此声称模型修订带来检出增益。fresh 固定每轮最多 16 条语义候选；
N04 未获得有效 oracle 修订，不能用 warm 的缓存命中代替 fresh 检出。N05 目标
原始变体进入程序列表，却始终未被 16 条语义队列选中；其 stale oracle 的当前
失败已单独确认是误报。下一轮只选新程序候选，导致这条未修订候选失去再次被
语义选择的机会。

另一个 Python 低预算消融（每轮 8 条、4 轮）已完成 profile 臂的独立复核：
`evaluation/ablation_python_v1/profile/checkpoint_01.json`，**4/8**，为 P3、N01、
N02、N03。它只选择了事先声明的 8 个 Python trial，不等同于 17-case 完整实验；
其余 9 个 trial 没参加该消融。rotation 臂也完成独立复核，封存于
`evaluation/ablation_python_v1/rotation/checkpoint_01.json`，同样 **4/8**，命中集合相同。
当前证据没有支持 profile 选择比轮转有更高检出率。

N08 旧见证 `a9212ca40d6edaa912da` 的主体以两条 Sync 写入建立 `seqNum+2`
这个未写入序号，随后验证 close 唤醒，主体关系合理。但完整复制的前缀还要求
**首次提交之前** `WaitForDurability(0)` 成功；issue 仅保证零在任意提交之后成功。
源测试在候选实现上通过不能证明这个额外前提。审查记录位于
`evaluation/semantic_reassessments_v1.json`，旧 checkpoint 保持不变，新 checkpoint
将历史累计字段与 `currently_supported_cumulative_witness` 分开。新证据封存在
`evaluation/uniform_warm_v2/checkpoint_01.json`：净化前缀只保留两条 Sync 写入及
批次序号，订阅首个未写入序号后关闭 DB；实际收到 nil 而不是要求的关闭错误，
独立源控制通过。它的每测试进程、原生 Go 结果、源码哈希均已核验。这个首个
v2 checkpoint 尚未关联完成的 campaign 索引，所以不能当作 v2 统一实验完成。

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

运行失败不等于检出缺陷；编译错误、环境错误、未执行 assertion 和不适用 oracle 分开记录。尚未复核的失败保持未知。全仓库表示在真实候选项目内执行所选测试，并不表示全套测试。抽查裁决不能估计总体误报率；单轮开发案例也不能支持总体漏报率。Docker 总并发最多两个执行槽，由生成/执行者与评价者协调。

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
