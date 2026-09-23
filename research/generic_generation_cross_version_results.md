# 通用生成实验：跨版本独立评价（截至 predicate-free 消融，成本账本 v7）

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

[当前汇总、逐请求 usage 与证据哈希](../results/generic_evaluation_summary/v7/summary.json)；[成本更正 v2](../results/generic_evaluation_summary/v2/summary.json)；[保留的旧摘要](../results/generic_evaluation_summary/v1/summary.json)。范围至本页列出的独立替代生成实验，另计已识别的协议诊断；此前机制专用实验及尚未完成的新批次未纳入。

v5/batch1 开始获得 holdout/control 模型准入授权；两轮共接受 C06 的 2 个有效测试，C02 的错误 oracle 均拒绝，3 个 holdout 仍零候选。P6 direct 的 7 项因生成代码编译失败未运行，归为无效生成而非环境问题。新 DeepSeek 无代码诊断虽然返回有效 JSON，仍报告 50 reasoning tokens，不能单凭该请求断言代码准入已经可靠。

v5/batch2 保持相同候选代码，只改为用户指定的 DeepSeek 和无冲突协议。12 次实际请求中 3 次准入无效（P1 两轮、P3 第二轮）：各报告 10,000 reasoning tokens、finish_reason=length，无可解析内容，未修复或重试。有效准入仅产生 4 个通过项，无可信缺陷；不能把无效轮次造成的输出减少解释为可靠性提升。

## 新的独立替代实验与审计

模型外发限定：旧配置下、此前用户指定模型后的正式实验请求使用 `ds/deepseek-v4-flash`；本次 `.env` 更新且用户更正模型名称后，新的正式实验请求使用 `deepseek-v4-flash`（无 `ds/`）；另有 3 次误触的旧 unit fixture `gpt-6-astra` 连接尝试，均为 ConnectError，接收、用量及费用未知，已添加全局 unit socket 禁用（626 tests 通过）。这 3 次仅含 synthetic fixture，单列在 [原始事件与归档证据](../results/generic_evaluation_summary/provider_incident_v1/unexpected_attempts.json)，不混入正式实验 DS 调用，不记作成功调用或零成本。

| 独立版本 | Direct 生成 | Direct 报警 | 错误 oracle / 前提不适用 | 两轮 gated 生成 | 可信缺陷 |
|---|---:|---:|---:|---:|---:|
| helper assertion instances | 0 | 0 | 0 / 0 | 0 | 0 |
| open helper assertion instances v2 | 0 | 0 | 0 / 0 | 0 | 0 |
| edit-square | 2 | 2 | 2 / 0 | 0 | 0 |
| observation-priority | 59 | 45 | 27 / 18 | 2 | 0 |

每个版本单独使用 128 候选预算，不把多生成器输出叠加后声称同预算。Instances 的 54 单元全为零生成，不能作为准确率改善。Edit-square 的两项在同一函数对未变化的调用次数同时要求 2 与 0；参考补丁本地缺失，保留 reference unavailable，错误 oracle 的依据独立于参考。Priority 的 7 项 Go 因生成的未声明变量而未执行，不归环境问题；参考 P4 因原测试导入不兼容而 collection error。所有新候选都在新参考运行前固定契约标签；9 个加权 valid oracle 均通过，0 个可信故障。

新增模型成本：edit-square 两次有效请求、53,190 tokens；priority 14 次请求（10 valid / 4 invalid）、390,817 tokens。Instances 无模型调用。旧无效或失败调用全部保留，累计已报告 token 不是未知用量请求的成本上界。

旧 v1 batch3 的 [429 个报警全量审计](../results/generic_v1/batch3/independent_oracle_audit_v1/README.md) 得到 280 项前提不适用、140 项断言错误、9 项 unknown、0 已确认 valid oracle。审计者既往暴露明确记录，不能称盲态。9 项只涉及递归包装是否应对元数据观察器透明，公开契约不足，未通过参考结果反向定性。这不能证明全部 919 个候选都无价值，也不能确认 gate 错拒了有效故障；未执行、源控制阻断及未审计通过项仍是覆盖限制。

指标与数据通路的[独立复核](generic_evaluation_integrity_review.md)验证了当时选定的 28 个模型请求可从冻结证据逐项重建。另一个 instances v2 版本的 54 单元也全为零输出、无模型调用；成本总数不变。三个跨项目任务已反复用于可行性探测，后续不称完全未见的盲测。本轮没有 issue resolution rate 的配对修复实验。

## 新配置重复实验

用户更新 `.env` 后首次无代码诊断沿用旧 `ds/` 名称，返回 HTTP 400，用量未知；用户随后明确指定 `deepseek-v4-flash`，plain 名称诊断成功，报告 444 tokens。历史请求保持原样，不能把这次命名错误写成模型生成能力失败。

Priority batch2 的 18 组候选、生成记录和模型证据均与 batch1 字节相同；完整源码和测试记录也相同。7 组 corpus 中 262 个断言的依赖图节点仅编号变化，存在逐节点唯一双射且边完全保持，见 [输入核验](../results/generic_observation_priority/batch2/capsule_node_id_audit.json)。14 次新配置请求全部有效，两轮均拒绝全部 pilot 候选，仅 C06 每轮接受 1 项，测试通过。Direct 的 45 个报警仍为 27 项错误 oracle、18 项前提不适用；0 个待审差分，0 个契约支持缺陷。全部运行重新执行，59 项契约推导仅在来源及生成函数字节哈希相同后复用。

该轮报告 331,698 tokens（输入 331,608，输出 90）。[累计账本 v5](../results/generic_evaluation_summary/v5/summary.json) 共 127 次正式实验及诊断尝试，已报告 3,989,711 tokens；23 次请求用量未知。另外 3 次旧 unit fixture 连接事故继续单列，合计尝试 130 次、未知用量 26 次。provider 与模型别名同时变化，不能据此单独归因于其中一项。

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

[逐项阶段与证据哈希](../results/generic_evaluation_summary/windows_pipeline_v1/pipeline.json) 保留预算、提取拒绝、模型准入、源控制和执行情况。这不是对因果根因的证明；本轮没有重新用隐藏目标审计入口排名，故不能断言“入口全部命中”或把全部问题归于检索。模型全拒绝也不等于可靠。

Flat 模型成本 442,540 tokens；balanced 419,806 tokens。[累计账本 v6](../results/generic_evaluation_summary/v6/summary.json) 为 163 次正式实验及诊断尝试，报告 4,852,057 tokens（输入 4,562,064／输出 289,993），23 次用量未知。另有 3 次旧 fixture 连接事故，接收和费用未知，单列后总尝试 166 次。旧 windows/batch1 是 2 项 prepare 失败、0 模型调用、0 目标程序执行的保留批次。

所有版本均为 0 个契约支持的缺陷检出，不能选择“统计最优”版本。工程基线比较必须同时看两轮错误报警、unknown、有效执行覆盖与成本：当前新 provider 的 priority 两轮只有 2 个控制测试、0 报警；balanced 两轮 22 项、2 个错误报警；flat 两轮 31 项、12 个错误报警。零生成与大量拒绝不能凭低报警数获胜；这些版本至多是可继续研究的工程基线，不能主张提高 issue resolution rate。

## 移除 predicate 分组约束的独立消融

Predicate-free 仍采用固定 128 候选、2000 次尝试预算，54 单元均完成记录。独立审计 75 个不同候选、93 个出现项；46 项旧推导经过来源与生成函数字节校验后复用，29 项新审计，全部标签在新参考运行前固定。24 次 plain 模型请求全部格式有效，报告 651,270 tokens。

| 变体 | 生成项 | 受控报警 | 错误 oracle / 前提不适用 | 源控制阻断 | 可信缺陷 |
|---|---:|---:|---:|---:|---:|
| predicate-free / direct | 75 | 41 | 25 / 16 | 23 | 0 |
| predicate-free / gated r1+r2 | 18 | 1 | 1 / 0 | 13 | 0 |

12 个 direct 项因生成的 Go 代码而未执行：11 个 P6 项受一个未使用局部变量导致的整包编译失败影响，1 个 Go holdout 项重复使用 `:=` 而没有新变量。前提、oracle 判断与编译结果分别记录，不把未执行项归为通过。Go holdout 参考补丁仍缺失；17 次其他 fresh reference 运行完成。四个数字身份断言虽偶然通过，API 只保证值相等，故审计仍记为错误 oracle；没有用双方通过来给它们背书。

本版两轮只有 1 个受控报警，不等于可靠性改善：另有 13 个准入项被失败源控制阻断；公开契约支持的 15 个出现项中，14 个通过，1 个因同包生成代码编译失败而未执行，未发现可信缺陷。P5 从零变成 6 个产物，但复制了不相容程序的预期值；P7 仍零产物。关于观察已存在、合法组合尚未构造出的边界，见 [可表达性独立审计](generic_generation_expressibility_audit.md)。

[累计账本 v7](../results/generic_evaluation_summary/v7/summary.json) 共 187 次正式实验及诊断尝试，已报告 5,503,327 tokens（输入 5,213,124／输出 290,203），23 次用量未知；另 3 次旧 fixture 连接事故继续单列，总尝试 190 次。尚未包含将来的 LLM 直接生成对照。

另需披露 [pytest 误收集事件](../results/collection_incident_v1/README.md)：predicate-free 实现已在误收集前完成，之后未改生成器；但误收集确实发生模块顶层导入并暴露真实测试路径/片段，网络及文件副作用未知，不能称全过程盲态。已经限定默认测试目录，664 项项目测试通过。此事故不被静默计作零副作用，也不凭未知行为捏造模型调用数量。
