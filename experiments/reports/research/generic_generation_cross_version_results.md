> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/generic_generation_cross_version_results.md) · [旧路径映射](../../../results/path_map.tsv)

# 通用生成实验：跨版本独立评价（含模型生成、筛选与协议诊断，成本账本 v10）

所有版本目前均无具备契约支持的候选缺陷证据。以下保留直接生成和两轮模型准入的全部出现次数；不能把运行失败直接视为发现缺陷。

| 版本/变体 | 生成项 | 候选报警 | 错误 oracle / 前提不适用 | 待审差分 | 可信缺陷 |
|---|---:|---:|---:|---:|---:|
| v1 batch5 / gated r1+r2 | 139 | 22 | 5 / 17 | 0 | 0 |
| v21 / direct | 33 | 25 | 15 / 10 | 0 | 0 |
| v21 / gated r1+r2 | 11 | 7 | 6 / 1 | 0 | 0 |
| v3 / direct | 21 | 15 | 15 / 0 | 0 | 0 |
| v3 / gated r1+r2 | 12 | 3 | 3 / 0 | 0 | 0 |
| v4 / direct | 21 | 15 | 15 / 0 | 0 | 0 |
| v4 / gated r1+r2 | 12 | 2 | 2 / 0 | 0 | 0 |
| v5 batch1 / direct | 40 | 25 | 15 / 10 | 0 | 0 |
| v5 batch1 / gated r1+r2 | 24 | 8 | 8 / 0 | 0 | 0 |
| v5 batch2 DS / direct | 40 | 25 | 15 / 10 | 0 | 0 |
| v5 batch2 DS / gated r1+r2 | 4 | 0 | 0 / 0 | 0 | 0 |

候选报警要求其源控制通过且无致命执行错误。v1 batch5 的 22 个报警均已审计，另外固定 SHA 抽查 40 个通过项；v21/v3/v4 全量审计。v1 的无效准入、编译失败、缺失控制，以及各版参考源控制失败均保存在逐项 JSON 中。参考通过不自动证明 oracle 正确，也不据此声明总体误报率。

v2 另有 C02 的 2 个直接生成项，均为错误 oracle；其他 17 个任务零候选。v21/v3/v4 的 3 个跨项目 holdout 均零候选，因此这些结果没有提供跨项目有效性证据。有效的 v3/v4 pilot 项只是原 donor 输入和断言附加不影响被测行为的局部赋值。

| 批次 | 模型 | 外部请求 | 有效/无效准入 | 已报告输入 / 输出 tokens | 已报告总 tokens | 用量未知请求 |
|---|---|---:|---:|---:|---:|---:|
| generic_v1/batch1 | 无调用 | 0 | 0/0 | 0 / 0 | 0 | 0 |
| generic_v1/batch2 | gpt-6-astra | 22 | 0/22 | 0 / 0 | 0 | 22 |
| generic_v1/batch3 | ds/deepseek-v4-flash | 14 | 0/14 | 1,448,590 / 109,208 | 1,557,798 | 0 |
| generic_v1/batch4 | ds/deepseek-v4-flash | 1 | 0/1 | 22,673 / 10,000 | 32,673 | 0 |
| generic_v1/batch5 | closeai/gpt-5.6-luna | 14 | 11/3 | 646,982 / 46,619 | 693,601 | 0 |
| generic_v2/batch1 | 无调用 | 0 | 0/0 | 0 / 0 | 0 | 0 |
| generic_v21/batch1 | closeai/gpt-5.6-luna | 8 | 8/0 | 191,860 / 2,618 | 194,478 | 0 |
| generic_v3/batch1 | closeai/gpt-5.6-luna | 4 | 4/0 | 110,406 / 2,135 | 112,541 | 0 |
| generic_v4/batch1 | closeai/gpt-5.6-luna | 4 | 4/0 | 110,586 / 2,193 | 112,779 | 0 |
| generic_v5/batch1 | closeai/gpt-5.6-luna | 12 | 12/0 | 221,730 / 3,400 | 225,130 | 0 |
| generic_v5/batch2 | ds/deepseek-v4-flash | 12 | 9/3 | 238,498 / 45,334 | 283,832 | 0 |
| generic_instances/batch1 | 无调用 | 0 | 0/0 | 0 / 0 | 0 | 0 |
| generic_edit_square/batch1 | ds/deepseek-v4-flash | 2 | 2/0 | 44,208 / 8,982 | 53,190 | 0 |
| generic_observation_priority/batch1 | ds/deepseek-v4-flash | 14 | 10/4 | 331,958 / 58,859 | 390,817 | 0 |

成本更正：旧版汇总遗漏两次无代码诊断，已核实为 51、125 tokens；另有先前 Luna 诊断 35 tokens，及新 `reasoning_effort=none` 诊断 519 tokens。四次诊断共 730 tokens，均保留。截至当时的正式实验及诊断请求 111 次，服务端已报告 3,657,569 tokens（输入 3,368,088 / 输出 289,481）；另有下述 3 次意外单元测试连接尝试，接收与用量未知；22 次失败请求没有 usage，不能算作零成本。模型列表 GET 另计 1 次 HTTP 请求，不计模型推理请求。无效准入与失败批次成本均未扣除，也不换算未知账单金额。旧摘要和原始请求未覆盖。

DeepSeek 的历史失败不能直接归因于模型或服务能力。冻结请求显示：batch3 的 14 次请求只设置 `thinking.type=disabled`；batch4 的 1 次请求同时设置该开关与 `reasoning_effort=low`。2026-09-23 查阅的官方 Chat Completions 文档说明 `none` 关闭思考、`low` 开启思考，因此 batch4 存在潜在控制冲突；但文档不能确定第三方代理当时如何处理两个参数的优先级，也不能据此解释未设置 `reasoning_effort` 的 batch3。原因应记为未确定，待无冲突协议的独立重跑验证。原请求、失败响应与成本不修改、不删除。[官方接口文档](https://api-docs.deepseek.com/api/create-chat-completion/)、[思考模式指南](https://api-docs.deepseek.com/guides/thinking_mode/)。

当前用户指定模型为 `deepseek-v4-flash`（无 `ds/`），新 `.env` 配置下的正式请求均采用此名称。上表 `ds/`、Luna、Astra 条目仅保留历史事实。

上述版本均未建立有效已知 pilot 缺陷证据；这里的零命中由无有效候选报警推出，并非重新读取隐藏目标后的标签审计。

[当前汇总、逐请求 usage 与证据哈希](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v07/summary.json)；[成本更正 v2](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v02/summary.json)；[保留的旧摘要](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v01/summary.json)。范围至本页列出的独立替代生成实验，另计已识别的协议诊断；此前机制专用实验及尚未完成的新批次未纳入。

v5/batch1 开始获得 holdout/control 模型准入授权；两轮共接受 C06 的 2 个有效测试，C02 的错误 oracle 均拒绝，3 个 holdout 仍零候选。P6 direct 的 7 项因生成代码编译失败未运行，归为无效生成而非环境问题。新 DeepSeek 无代码诊断虽然返回有效 JSON，仍报告 50 reasoning tokens，不能单凭该请求断言代码准入已经可靠。

v5/batch2 保持相同候选代码，只改为用户指定的 DeepSeek 和无冲突协议。12 次实际请求中 3 次准入无效（P1 两轮、P3 第二轮）：各报告 10,000 reasoning tokens、finish_reason=length，无可解析内容，未修复或重试。有效准入仅产生 4 个通过项，无可信缺陷；不能把无效轮次造成的输出减少解释为可靠性提升。

## 新的独立替代实验与审计

模型外发限定：旧配置下、此前用户指定模型后的正式实验请求使用 `ds/deepseek-v4-flash`；本次 `.env` 更新且用户更正模型名称后，新的正式实验请求使用 `deepseek-v4-flash`（无 `ds/`）；另有 3 次误触的旧 unit fixture `gpt-6-astra` 连接尝试，均为 ConnectError，接收、用量及费用未知，已添加全局 unit socket 禁用（626 tests 通过）。这 3 次仅含 synthetic fixture，单列在 [原始事件与归档证据](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/provider_incident_v1/unexpected_attempts.json)，不混入正式实验 DS 调用，不记作成功调用或零成本。

| 独立版本 | Direct 生成 | Direct 报警 | 错误 oracle / 前提不适用 | 两轮 gated 生成 | 可信缺陷 |
|---|---:|---:|---:|---:|---:|
| helper assertion instances | 0 | 0 | 0 / 0 | 0 | 0 |
| open helper assertion instances v2 | 0 | 0 | 0 / 0 | 0 | 0 |
| edit-square | 2 | 2 | 2 / 0 | 0 | 0 |
| observation-priority | 59 | 45 | 27 / 18 | 2 | 0 |

每个版本单独使用 128 候选预算，不把多生成器输出叠加后声称同预算。Instances 的 54 单元全为零生成，不能作为准确率改善。Edit-square 的两项在同一函数对未变化的调用次数同时要求 2 与 0；参考补丁本地缺失，保留 reference unavailable，错误 oracle 的依据独立于参考。Priority 的 7 项 Go 因生成的未声明变量而未执行，不归环境问题；参考 P4 因原测试导入不兼容而 collection error。所有新候选都在新参考运行前固定契约标签；9 个加权 valid oracle 均通过，0 个可信故障。

新增模型成本：edit-square 两次有效请求、53,190 tokens；priority 14 次请求（10 valid / 4 invalid）、390,817 tokens。Instances 无模型调用。旧无效或失败调用全部保留，累计已报告 token 不是未知用量请求的成本上界。

旧 v1 batch3 的 [429 个报警全量审计](../../../results/test_analogy_generation/test_context_exchange_v01/batch_03/independent_oracle_audit_v1/README.md) 得到 280 项前提不适用、140 项断言错误、9 项 unknown、0 已确认 valid oracle。审计者既往暴露明确记录，不能称盲态。9 项只涉及递归包装是否应对元数据观察器透明，公开契约不足，未通过参考结果反向定性。这不能证明全部 919 个候选都无价值，也不能确认 gate 错拒了有效故障；未执行、源控制阻断及未审计通过项仍是覆盖限制。

指标与数据通路的[独立复核](generic_evaluation_integrity_review.md)验证了当时选定的 28 个模型请求可从冻结证据逐项重建。另一个 instances v2 版本的 54 单元也全为零输出、无模型调用；成本总数不变。三个跨项目任务已反复用于可行性探测，后续不称完全未见的盲测。本轮没有 issue resolution rate 的配对修复实验。

## 新配置重复实验

用户更新 `.env` 后首次无代码诊断沿用旧 `ds/` 名称，返回 HTTP 400，用量未知；用户随后明确指定 `deepseek-v4-flash`，plain 名称诊断成功，报告 444 tokens。历史请求保持原样，不能把这次命名错误写成模型生成能力失败。

Priority batch2 的 18 组候选、生成记录和模型证据均与 batch1 字节相同；完整源码和测试记录也相同。7 组 corpus 中 262 个断言的依赖图节点仅编号变化，存在逐节点唯一双射且边完全保持，见 [输入核验](../../../results/test_analogy_generation/observation_guided_test_analogy/batch_02/capsule_node_id_audit.json)。14 次新配置请求全部有效，两轮均拒绝全部 pilot 候选，仅 C06 每轮接受 1 项，测试通过。Direct 的 45 个报警仍为 27 项错误 oracle、18 项前提不适用；0 个待审差分，0 个契约支持缺陷。全部运行重新执行，59 项契约推导仅在来源及生成函数字节哈希相同后复用。

该轮报告 331,698 tokens（输入 331,608，输出 90）。[累计账本 v5](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v05/summary.json) 共 127 次正式实验及诊断尝试，已报告 3,989,711 tokens；23 次请求用量未知。另外 3 次旧 unit fixture 连接事故继续单列，合计尝试 130 次、未知用量 26 次。provider 与模型别名同时变化，不能据此单独归因于其中一项。

## 断言窗口：固定产物的独立评价

两批都完成 18 direct、36 gated 记录；各 18 次新配置 `deepseek-v4-flash` 请求全部格式有效。Flat 审计 70 个不同候选、101 个出现项；balanced 审计 67 个不同候选、89 个出现项。每项检查完整生成函数及其来源，标签在该批参考执行前固定；审计者先前看到候选运行摘要，不能称盲态。Balanced 与 flat 相同内容的推导复用经过完整源码和生成函数字节校验，执行均重新进行。

| 变体 | 生成项 | 受控报警 | 错误 oracle / 前提不适用 | 源控制阻断 | 可信缺陷 |
|---|---:|---:|---:|---:|---:|
| windows flat / direct | 70 | 37 | 22 / 15 | 14 | 0 |
| windows flat / gated r1+r2 | 31 | 12 | 10 / 2 | 4 | 0 |
| windows balanced / direct | 67 | 36 | 21 / 15 | 14 | 0 |
| windows balanced / gated r1+r2 | 22 | 2 | 2 / 0 | 0 | 0 |

这些批次没有生成测试的编译失败；P6 参考编译错误定位于保留的原始测试引用 `ErrNotCallableFromGo`，该符号不在参考实现中，不能误归为生成无效。P4 参考端仍有原测试导入不兼容。Xfail、失败的源测试等控制阻断保留，不能把这些记录算作通过或检出。所有契约支持的生成项都在候选上通过；新增 C01 包含“重复元素＋不修改输入”的有效组合，但它没有发现控制缺陷。

逐 pilot 未检出阶段：

| Pilot | 当前可核验的停止点 |
|---|---|
| P1 | 17 个产物全部 oracle 错误或设置不适用；两轮均拒绝，未构成 phase 组合。 |
| P2 | 9 个有效项主要拼接独立既有事实并通过，另 1 项矛盾 oracle 被两版各两轮接受；没有有效故障候选。 |
| P3 | 25 项仅 1 项有效，重放普通 key 测试；其余保留旧元数据或混用 Paste/Key；11 个 direct 项另有源控制阻断。 |
| P4 | 4 项有效顺序录制/重放组合通过，2 项不成立；两轮全拒绝，未产生路径上下文变换。 |
| P5 | 10 个入口仅 4 个有可用窗口；2000 次尝试均在 anchor/alignment 阶段拒绝，零产物；片段不完整也限制提取。 |
| P6 | Flat 的 2 个有效项只是既有宿主调用重放并通过；其余为算术、参数或全局查找错误；无 clone/transfer 组合。 |
| P7 | 10 个入口均有窗口，1338 次尝试仍零产物：495 对齐歧义、520 对应角色不一致、323 缺 anchor。 |

[逐项阶段与证据哈希](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/windows_pipeline_v1/pipeline.json) 保留预算、提取拒绝、模型准入、源控制和执行情况。这不是对因果根因的证明；本轮没有重新用隐藏目标审计入口排名，故不能断言“入口全部命中”或把全部问题归于检索。模型全拒绝也不等于可靠。

Flat 模型成本 442,540 tokens；balanced 419,806 tokens。[累计账本 v6](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v06/summary.json) 为 163 次正式实验及诊断尝试，报告 4,852,057 tokens（输入 4,562,064／输出 289,993），23 次用量未知。另有 3 次旧 fixture 连接事故，接收和费用未知，单列后总尝试 166 次。旧 windows/batch1 是 2 项 prepare 失败、0 模型调用、0 目标程序执行的保留批次。

所有版本均为 0 个契约支持的缺陷检出，不能选择“统计最优”版本。工程基线比较必须同时看两轮错误报警、unknown、有效执行覆盖与成本：当前新 provider 的 priority 两轮只有 2 个控制测试、0 报警；balanced 两轮 22 项、2 个错误报警；flat 两轮 31 项、12 个错误报警。零生成与大量拒绝不能凭低报警数获胜；这些版本至多是可继续研究的工程基线，不能主张提高 issue resolution rate。

## 移除 predicate 分组约束的独立消融

Predicate-free 仍采用固定 128 候选、2000 次尝试预算，54 单元均完成记录。独立审计 75 个不同候选、93 个出现项；46 项旧推导经过来源与生成函数字节校验后复用，29 项新审计，全部标签在新参考运行前固定。24 次 plain 模型请求全部格式有效，报告 651,270 tokens。

| 变体 | 生成项 | 受控报警 | 错误 oracle / 前提不适用 | 源控制阻断 | 可信缺陷 |
|---|---:|---:|---:|---:|---:|
| predicate-free / direct | 75 | 41 | 25 / 16 | 23 | 0 |
| predicate-free / gated r1+r2 | 18 | 1 | 1 / 0 | 13 | 0 |

12 个 direct 项因生成的 Go 代码而未执行：11 个 P6 项受一个未使用局部变量导致的整包编译失败影响，1 个 Go holdout 项重复使用 `:=` 而没有新变量。前提、oracle 判断与编译结果分别记录，不把未执行项归为通过。Go holdout 参考补丁仍缺失；17 次其他 fresh reference 运行完成。四个数字身份断言虽偶然通过，API 只保证值相等，故审计仍记为错误 oracle；没有用双方通过来给它们背书。

本版两轮只有 1 个受控报警，不等于可靠性改善：另有 13 个准入项被失败源控制阻断；公开契约支持的 15 个出现项中，14 个通过，1 个因同包生成代码编译失败而未执行，未发现可信缺陷。P5 从零变成 6 个产物，但复制了不相容程序的预期值；P7 仍零产物。关于观察已存在、合法组合尚未构造出的边界，见 [可表达性独立审计](generic_generation_expressibility_audit.md)。

[累计账本 v7](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v07/summary.json) 共 187 次正式实验及诊断尝试，已报告 5,503,327 tokens（输入 5,213,124／输出 290,203），23 次用量未知；另 3 次旧 fixture 连接事故继续单列，总尝试 190 次。该历史累计尚未包含下述 LLM 直接生成对照。

另需披露 [pytest 误收集事件](../../../results/test_validity_audits/test_collection_failure_audit_v01/README.md)：predicate-free 实现已在误收集前完成，之后未改生成器；但误收集确实发生模块顶层导入并暴露真实测试路径/片段，网络及文件副作用未知，不能称全过程盲态。已经限定默认测试目录，664 项项目测试通过。此事故不被静默计作零副作用，也不凭未知行为捏造模型调用数量。

## 独立模型直接生成对照

[预先固定的计划](llm_generation_baseline_plan.md)统一取七例冻结检索的前十个父测试，每例两轮、每轮最多三个完整 body 替换。模型可以创造新输入和断言；因此它与仅从源码搬运的 128 候选生成器具有不同能力、预算和展示范围，不能把差异归因于单一因素，更不能合并后选最好一轮。14 次请求全部格式有效，42 项提议中 38 项进入冻结执行；其余 4 项被 body 范围检查拒绝，保留为 unsupported，未修复模型输出。

| 独立轮次 | 提议 / 冻结执行 | 候选通过 | 错误 oracle 报警 | 契约支持报警 | 已确认目标 |
|---|---:|---:|---:|---:|---:|
| r1 | 21 / 19 | 15 | 4 | 0 | 0/7 |
| r2 | 21 / 19 | 16 | 3 | 0 | 0/7 |

[事前 oracle 审计](../../../results/test_analogy_generation/llm_direct_test_generation_baseline/batch_01/oracle_audit_before_reference.json)覆盖全部 38 个出现项：26 项有来源契约支持且候选全部通过；7 个报警均为错误 oracle；5 项运行时 oracle 仍 unknown，即使通过也不升级。七个错误包括把 `=` 字符当作 `base_key` 名称、把 modifier 6 当成 alt+ctrl，以及四项闭包状态/全局值计算错误。另一名未见本轮执行结果的审计者对 26 valid 和 7 invalid 完全一致，将后五项记为 inapplicable；两者均认为类型检查拒绝不能推出精确的运行时抛错规则。[交叉审计记录](../../../results/test_analogy_generation/llm_direct_test_generation_baseline/batch_01/cross_auditor_reconciliation.json)保留原标签与差异。

候选侧源控制全部通过，无编译或 collection 阻断。参考侧存在 P4/P6/P7 原测试导入、API 符号或目录布局不兼容，共 18 项未执行；另有参考源控制失败。原控制失败不会计作新生成误报，参考通过也不自动验证 oracle。八次初始 freeze 因 JSON 将 tuple 保存为 list 而比较失败，已保留原日志，仅用[独立适配器](../../../scripts/freeze_llm_baseline_json_adapter.py)对完整对象作 JSON 规范化后补齐；请求、响应、代码 body、validation 内容和原快照均未修改。此对照最终仍为 0 个合格差分、0 个契约支持缺陷，见[完整评价](../../../results/test_analogy_generation/llm_direct_test_generation_baseline/batch_01/evaluation_complete.json)。

本对照新增 320,488 tokens（输入 304,346、输出 16,142）。[累计账本 v8](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v08/summary.json)共 201 次正式实验及诊断尝试，已报告 5,823,815 tokens（输入 5,517,470、输出 306,345），23 次用量未知；另 3 次旧 unit fixture 连接事故单列，合计 204 次尝试、26 次用量未知。以上不含早期领域专用 contract 实验。零有效检出仍是当前结果，不能将此对照描述为证明某种生成方法有效，也未测得 issue resolution rate 改善。

## 两项独立补充诊断

前导注释的范围检查经独立 toy 证明过严后，统一对原 14 份响应重新物化，模型 body 和原 38 个候选完全不变；新增支持仅为 P3 两轮各 2 项。P3 每轮完整 3 项重新执行，其余 12 轮仅在候选、完整物化文件和 harness 全部字节相同后明确复用。新增 4 项 oracle 可由原 shift-printable、phase 和 aliases 文档推导，候选全部通过，仍无缺陷。诊断总 42 项为 30 valid 通过、7 错误报警、5 unknown 通过；不覆盖原实验，也不混入下述后置筛选。两项新增 reference 报警与原 `97;2u => A` 源契约不一致，已独立记录，没有据 reference 结果改写 oracle。见[机械重验证](../../../results/test_analogy_generation/llm_generated_test_comment_revalidation/batch_01/evaluation_complete.json)。

后置 gate 是另行声明的探索性诊断，只筛选原 38 项，每轮一次请求，不修模型代码、不合并两轮。全部源码、candidate edits 与完整生成函数哈希一致后才复用旧 oracle 标签；两侧执行均重新进行。

| 轮次与流程 | 执行项 | valid oracle 通过 | 错误 oracle 报警 | unknown 通过 | 已确认目标 |
|---|---:|---:|---:|---:|---:|
| 原直接生成 r1 | 19 | 13 | 4 | 2 | 0/7 |
| 原直接生成 r2 | 19 | 13 | 3 | 3 | 0/7 |
| 同一生成池＋gate r1 | 17 | 12 | 3 | 2 | 0/7 |
| 同一生成池＋gate r2 | 13 | 9 | 1 | 3 | 0/7 |

Gate 拒绝了 3 个错误 oracle，也拒绝了 5 个正确但通过的测试，仍保留 4 个错误 oracle 和全部 5 个 unknown。池中没有已确认真实故障候选，所以不能由这些数字估计真实缺陷的误拒率或召回率。21 个 valid oracle 通过只是有效执行覆盖，不是 21 个缺陷。两阶段总成本为 **28 次请求、621,570 tokens**，其中生成 320,488、筛选 301,082；不能只报告筛选成本。[完整后置筛选评价](../../../results/test_analogy_generation/llm_generated_test_admission_baseline/batch_01/evaluation_complete.json)仍为 0 个合格差分、0 个契约支持缺陷。

依[预定选择规则](generic_version_selection.md)，当前没有达到“两轮七个目标都命中且无错误/未知报警与执行问题”的版本。低报警存在明显覆盖取舍：priority 两轮无 pilot 产物；predicate-free 的 14 个准入 pilot 项中 13 个被源控制阻断；v5 batch2 虽零受控错误报警，但只有 r1 的两个有效 pilot 重放，另三轮模型协议失败。Balanced 两轮有 16 个有效 pilot 项通过、2 个错误报警、无源控制阻断，可保留为覆盖较清楚的工程研究基线；这不是统计最优或学术方法有效性的结论。模型直接生成及其 gate 属于不同预算与能力的独立基线，不纳入同预算单因素排名。全部七个目标仍未获得可信检出。

[累计账本 v9](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v09/summary.json)为 215 次正式实验及诊断尝试，已报告 **6,124,897 tokens**（输入 5,818,362、输出 306,535），23 次用量未知。三次旧 unit fixture 连接事故继续单列，合计 218 次尝试、26 次用量未知；前导注释机械诊断没有新增模型调用。

## 固定输入的 thinking 协议对照

最后一批保持同一 top10 源测试、issue、候选上限 3 和 10,000 输出预算，只将请求的 `thinking.type` 改为 `enabled`、`reasoning_effort` 改为 `low`。[输入通路审计](../../../results/test_analogy_generation/llm_reasoning_mode_baseline/batch_01/input_path_audit.json)逐字重建全部 14 次请求，确认两轮输入相同、与 none 协议的语义输入相同。没有输出修复、失败重试或跨轮挑选；物化使用修正后的通用前导注释检查器，原 none 输出的同检查器诊断已单列。

14 次 HTTP 请求均成功返回，但只有 9 次产生格式有效的最终响应；其余 5 次各耗尽 10,000 reasoning tokens 而无 final content，应记为模型响应/预算失败，不能称网络失败或主动拒绝。9 份有效响应提出 27 项，其中 P3 r2 的 3 项被 Python 编译检查拒绝，其余 24 项执行。P5–P7 的支持项由未读本轮运行结果的第二审计者检查，所有标签在新参考执行前固定。

| 预定轮次 | 执行项 | valid oracle 通过 | 前提不适用报警 | 未知 oracle | 已确认目标 |
|---|---:|---:|---:|---:|---:|
| thinking r1 | 15 | 15 | 0 | 0 | 0/7 |
| thinking r2 | 9 | 8 | 1 | 0 | 0/7 |

唯一报警把 Kitty 序列写成四个分号字段，不能作为有效输入上的 parser 缺陷。23 个可支持断言全部通过；没有合格差分或可信缺陷。参考侧 12 项受原测试 API/导入不兼容阻断，源控制失败与参考契约分歧继续单列。模型响应失败和构造覆盖损失使得低报警不能解释为方法可靠性提升，七个目标仍全部未确认检出。见[完整 thinking 评价](../../../results/test_analogy_generation/llm_reasoning_mode_baseline/batch_01/evaluation_complete.json)。

本批追加 406,185 tokens，其中 95,344 reasoning tokens 已包含在 completion/total 内，未重复累加。[最终账本 v10](../../../results/test_analogy_generation/test_generation_cross_version_evaluation/evaluation_v10/summary.json)共 **229 次正式实验及诊断尝试、6,531,082 已报告 tokens**（输入 6,123,058、输出 408,024）；23 次历史请求用量未知。另有 3 次旧 fixture 连接事故单列，合计 232 次尝试、26 次用量未知。以上不是已核定金额，也不包含早期领域专用 contract 实验。固定时限内完成的所有模型响应、原始运行、控制结果及审计均保留，没有将失败从分母或成本中删除。
