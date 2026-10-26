# 程序分析主导的语义组合：独立评价计划

固定日期：2026-09-24。当前轮截止时间为 **2026-09-24 08:25:54 UTC / 16:25:54 北京时间**。范围是既有七个 pilot 上的新通用方法；七例均是反复使用的 discovery 集。本文不提供各例目标语义、参考补丁或手工答案给生成器。

本轮独立评价者已读 handbook、既有方法/评价报告、运行器和已落盘运行结果，因此不是盲态评价。准备阶段没有执行被测程序、发送模型请求、读取 `.env`、参考补丁或隐藏 verifier。历史结果的读取不能证明本轮环境当前可用。

## 1. 当前可复用的运行条件

七例的 `data/cases/P*/` 均有 `issue.md`、`model.patch`、`trajectory.json` 和 `repository/`。`data/cases.json` 固定了候选 trial、语言、base commit、镜像和历史 mini-swe-agent 版本；实际执行以 registry 为准，handbook 中的展示 URL 不是候选文件定位依据。

| Case | 语言 / 项目 | 历史 agent harness | 实际测试 harness | 既有运行证据与限制 |
|---|---|---|---|---|
| P1 | Python / Textual | 2.4.2 | pytest + JUnit | 新近模型对照的已执行轮候选来源控制通过；balanced direct 有来源控制 skip。参考有原控制失败。不能据历史控制通过免除本轮检查。 |
| P2 | Python / Textual | 2.4.1 | pytest + JUnit | balanced 两轮及新近模型对照候选来源控制通过；参考有原控制失败。测试体 fail 与控制 fail 分别保留。 |
| P3 | Python / Textual | 2.4.6 | pytest + JUnit | balanced direct 有来源控制 skip；思考对照 r1 候选控制通过，r2 三个生成体被编译校验拒绝。参考有原控制失败。 |
| P4 | Python / IPython | 2.4.1 | pytest + JUnit | 已执行候选来源控制通过；参考因原测试导入 API 不兼容而 collection error。该问题不是候选编译错误，也不是环境安装失败。 |
| P5 | Go / Tengo | 2.4.2 | `go test -json` | balanced 无产物；思考对照两轮响应预算失败而无测试。这两个批次均未给本例新的执行覆盖。其他旧批次的生成失败不能归为永久运行不支持。 |
| P6 | Go / Tengo | 2.4.1 | `go test -json` | 存在候选控制全部通过的执行；旧生成器也出现未声明/未使用变量的整包编译失败。参考保留的原测试依赖参考不存在的 API，因而编译失败，须与生成代码问题区分。 |
| P7 | TypeScript / Valibot | 2.4.3 | library 包内 pnpm / Vitest JSON | balanced 无产物；思考对照 r2 候选及控制通过。参考有原测试模块/目录不兼容导致 suite error；它的 `errors` 数组为空，但 `status=error`、`counts.error=2`，不能遗漏。 |

证据来自 `results/generic_windows_balanced/batch1/pilot/` 的 frozen manifest、candidate/reference result 及 `execution_diagnostics_v1.json`，以及 `results/llm_thinking_baseline/batch1/pilot/*/rounds/*/` 的相同文件。表中“通过”均仅指该历史产物声明的来源控制，不是仓库全测试通过；“无产物”也不是通过。保留完整报告，不以表中摘要替代原始证据。

四个镜像的历史 image ID/digest 在 `results/docker_environment.json`；Python 3.12 venv、Go 1.25.5、Node 24.12.0、pnpm 10.11.0 等安装记录在 `ENVIRONMENT.md`。镜像 ID 在每次实际运行时由 runner 再记录。Docker socket 在执行沙箱内可能不可访问，需根代理按既有授权处理执行权限；本次准备没有重新验证 Docker。

mini-swe-agent 的历史版本用于 trajectory 复现；生成测试的普通 pytest/Go/Vitest 执行不需要重新启动 coding-agent harness。不要为了评价测试组合重放整个 agent trajectory。

## 2. 输入隔离与冻结

生成输入限于 issue、候选实现/补丁、既有测试、trajectory 中 agent 可见材料和公开契约。程序分析负责组合候选及静态检查，少量模型使用范围、模型标识和预算由方法 manifest 在首次调用前固定。本文、manual annotations、评价标签、参考结果、隐藏 verifier、封存控制真值及旧的领域专用答案均不得进入生成输入或提示。

新方法先用一个新输出根冻结：算法文件快照及 SHA、输入文件清单及 SHA、registry/base commit、检索结果、全部提出/拒绝候选、排序/截断、准入提示、模型参数和预算。默认沿用每例至多 128 候选、两轮 `r1/r2`、每轮一次请求及 10,000 输出 tokens 的旧上限；若方法需要变更，应在本轮开始前另行声明，不借已有结果追认等预算。无模型方法可重复确定性执行并明确两轮相同，不虚构独立模型样本。

两轮生成和准入均在收到本轮执行/语义评价反馈前完成。任何代码、提示、预算或输入变化进入新版本和新目录，原结果全部保留。不以本轮第一轮结果重写第二轮，也不从多个版本拼接最好产物。

所有实际请求、响应、无效响应、传输失败、缓存命中和用量未知均进入账本。HTTP 200 不等于有效准入；耗尽 reasoning budget 而没有最终结构化结果不是主动拒绝全部候选。没有候选而跳过请求则明确记零调用。

## 3. 简化后的逐阶段流程

1. **静态准备与物化。** 对固定七例完成全部候选及两轮物化，保留源测试到生成测试的映射、每项来源控制、完整文件、命令、超时和 artifact SHA。无产物、unsupported、机械验证拒绝分别记录。源控制应是未作语义变换的原测试副本；名称变化与合法的框架适配有记录。
2. **独立 oracle 初审。** 评价者读取冻结测试和公开契约，逐项记录输入有效性、前提、期望断言的推导、引用文件/位置及哈希。尽量在候选执行前完成；最低要求是在任何本轮参考/隐藏材料访问或参考执行前固定。允许先看候选运行时，必须标明该暴露，不能称执行盲态。
3. **候选运行与来源控制。** 使用新容器或可丢弃副本执行冻结产物，记录所有 runtime leaves；不修补 expected，不依据失败删除测试。候选报警独立于参考计算。对编译/导入阻断先定位是生成代码、原测试兼容性还是运行设施，禁止统称环境失败。
4. **固定 oracle 标签。** 将标签、证据、审阅人、审核时间及其绑定的 artifact SHA 写入不可覆盖的 `oracle_audit_before_reference.json`，另记该文件 SHA。`valid_oracle`、`invalid_oracle`、`inapplicable`、`unknown` 是语义维度；运行结果单独记录。小规模 pilot 对全部最终输出审核，不只审报警；无力全审时未审项为 unknown，不能据参考通过补标签。
5. **参考/目标评价。** 仅在所有本轮生成冻结且 oracle 标签已固定后，由评价者使用参考补丁/隐藏 verifier。候选与参考使用同一份 frozen bytes。参考不可用或原测试不兼容时保留不可比，不通过删除原测试、改变断言或替换参考来“修好”数字。必要的纯 harness 机械修复另建诊断批次，明确每个变化且重跑两侧；它不覆盖主批次。
6. **独立缺陷判定及汇总。** 有效 oracle 的受控候选失败才进入真实缺陷审核；参考通过只是补充差分。已知目标匹配与其他真实缺陷分开，同一根因去重。目标命中的争议项由第二审阅者复核；新证据造成的标签修正另写新审计版本，保留事前标签及修改原因。

参考访问门槛是两个事实同时成立：“生成已冻结”和“oracle 标签已封存”；文件名、mtime 或口头宣称不能独立证明顺序。评价账本记录封存 SHA 和后续 reference-run 开始时间。哈希证明所引用字节未变，不证明模型未见数据或人工推导必然正确。

## 4. 判定与计数

固定主矩阵为 **7 case × 2 rounds = 14 单元**；旧 generic driver 的直接生成对照是单独消融，不能与两轮方法产物混算。新 semantic transport driver 采用 `rounds/r1|r2/frozen/direct`，其中内层 `direct` 只是复用物化适配器；两轮身份取 `completion_round`，不得误算为第三个消融。最少同时保存任务单元、唯一静态义务、运行参数叶子和去重缺陷四层计数。多参数叶子不冒充独立组合，跨轮重复项不冒充不同测试。

每条义务的候选报警要求：至少一个匹配测试体失败；该义务全部声明来源控制及参数化叶子均为 pass；无相关 setup/collection、编译、超时、transport 或报告错误。skip/xfail、缺失、error、未声明控制均不能当作控制通过。全局错误保守阻断该运行的缺陷主张；若能证明错误不相关，须另留逐项依据，不能静默忽略。

不能仅检查 `bool(result.errors)`。至少同时核对 `status`、`counts.error`、各 testcase 的 error、`process`/`transport` 和声明测试是否实际出现。`passed` 必须要求有效执行，不因部分 pass leaves 和空 errors 而忽略 suite error。参数化父项存在 pass 与 skip/fail 时必须合并全部 leaves。

主表每轮给出：七例目标命中、其他确认缺陷、有效且通过项、错误 oracle 报警、不适用输入报警、未知报警、未审/未知通过项、来源控制阻断、生成编译/导入错误、其他运行错误、无输出和模型协议失败。重叠诊断指标注明重叠，不能相加冒充互斥总数；可另给首要状态形成完整单元分区。

“七例无漏报无误报”的经验终止条件沿用严格版本：**r1 和 r2 各自七例目标全命中；不存在已确认错误报警、未知报警、模型协议失败或相关候选执行错误。** 没产物、未执行或阻断均不算目标检出。参考兼容性失败单列，不自动推翻由独立契约及候选证据确认的缺陷，但不能称该项已有合格差分；若目标身份仍无法确认则 unknown，阻止全成功结论。

这里只报告七个预先给定目标的发现率，不能声称所有真实缺陷的 recall 或全局 FPR。历史/真实项目没有完整真阴性分母。“未知”不变成成功；没有报警但全部拒绝也不成为可靠检测器。尚未执行配对修复实验，不能报告 issue resolution rate 提升。

到时保留全部已完成版本和旧基线。按事前的目标命中、错误/未知报警、实际执行覆盖与成本比较；如果存在取舍，给出取舍理由，不称统计最优。尤其全部版本零命中时，不能仅凭零输出的零报警替换已有可运行基线。截止时仍未完成的单元明确未完成，不用后续补跑倒填截止前成果。

## 5. 复用接口及需要独立补足的部分

- `scripts/run_generic_experiment.py` 的 `prepare/admit/freeze/run/summarize` 已提供新目录、代码/输入 SHA、两轮、产物冻结和不可覆盖运行。`run` 默认 candidate；本轮不在 oracle 封存前使用 `--program pair`。
- `generic_composition.runner.freeze_artifact` 要求生成项声明来源控制；`infer_harness` 处理 Python、Go、Vitest/Jest/Node；`run_artifact` 接受显式 evaluator reference 参数。镜像运行会重建固定 base、应用 candidate/reference patch，并以网络隔离执行。生成前的本地 candidate repository 和运行时 base+patch 是两条输入路径，应核对来源一致，不能只检查 frozen test SHA。
- `combination_testing.test_reports.parse_report` 提供报告解析、错误和参数叶子；`_selected_test_names` 避免依赖硬编码生成命名前缀。汇总仍须处理上述 `errors=[]` 但 suite error 的情况。
- `scripts/evaluate_generic_controls.py` 提供较完整的静态义务、来源控制与独立语义标签模式，但它绑定封存 controls 的真值资产，不能直接作为七 pilot 的语义判定器。其有限域有效性也不能外推到域外输入；复用纯状态逻辑时不要顺便加载封存真值。
- `combination_testing.evaluate.evaluate_case` 需要两侧 result，只适合差分汇总；候选单侧、参考缺失和零输出仍须独立显示，不能等待参考可比才统计候选报警。已有批次的独立 oracle/执行账本可作文件结构范例，不能直接复用语义标签，除非完整输入/产物/契约依据逐字节相同且明确标为复用。
- 本轮执行单元测试使用 `.venv/bin/python -m pytest tests ...`；不要不限定路径递归收集 data/results/vendor。现有 pytest 默认发现配置和网络禁用测试夹具继续保留。算法单元测试通过不是七 pilot 效果证据。

## 6. 相比旧协议的简化与修正

旧的 [通用评价协议](generic_generation_evaluation_plan.md)、[控制评价计划](generic_control_evaluator_plan_v1.md) 和 [完整性复核](generic_evaluation_integrity_review.md) 仍保留，不改写历史口径。本轮差异如下：

1. **先集中七例。** 旧协议同时安排三跨项目任务、八控制、多个消融和修复实验，本轮不把这些全设为交付前置条件。七例两轮完整评价优先；扩展批次另行声明，已见的 feasibility 任务/控制仍不能称未见盲测。
2. **审核少量最终产物，而非增加大量模板化文件。** 七 pilot 最终输出量可控时全审，替代“报警全审、通过项抽样”的复杂加权；若只抽样必须保留旧抽样概率和 unknown，不用样本结论覆盖未审项。
3. **oracle 封存与执行标签分离。** “参考通过”“双方通过”“候选实现如此运行”都不作为独立 oracle 依据；新计划明确参考访问的时序证据，而不只在文档中宣称先审。
4. **把运行阻断归因说清楚。** 原测试控制失败、生成编译错误、参考 API 不兼容、基础设施问题和模型格式/预算失败分开。特别修正只查 `errors` 数组、混合两侧控制阻断和把零输出当成功的汇总风险。
5. **限制比较承诺。** direct、模型自由生成和筛选方法预算/能力不同，分别报告；保留两轮全部结果和总成本，不为时间压力追加“最好一轮”选择。发现率、参考报警率、错误 oracle 比例和真正的 FPR/recall/修复率继续区分。

本文是新轮执行前计划，不代表新方法已经通过任何 pilot，也不为旧数据补作预注册。

## 7. 新 driver 的独立评价实现

只读复核 `experimental/semantic_transport/{proposals,oracle,state_contexts,model,contracts}.py` 和 `scripts/run_semantic_transport.py` 后，评价使用独立的 `scripts/evaluate_semantic_transport.py`，不导入生成器、runner、provider 或被测仓库。所有输出路径必须新建。

```bash
.venv/bin/python scripts/evaluate_semantic_transport.py inventory \
  --experiment-root results/semantic_transport/batchN --output results/semantic_transport/batchN/inventory_v1.json

# 独立审阅者填写 inventory 内 oracle_review_template，保留每条 artifact SHA。
.venv/bin/python scripts/evaluate_semantic_transport.py seal \
  --experiment-root results/semantic_transport/batchN \
  --reviews results/semantic_transport/batchN/oracle_reviews_v1.json \
  --output results/semantic_transport/batchN/oracle_audit_before_reference.json

.venv/bin/python scripts/evaluate_semantic_transport.py evaluate \
  --experiment-root results/semantic_transport/batchN \
  --sealed-oracles results/semantic_transport/batchN/oracle_audit_before_reference.json \
  --output results/semantic_transport/batchN/candidate_evaluation_v1.json
```

`inventory/evaluate` 默认不读取 reference result。只有显式 `evaluate --include-reference` 且 oracle seal 与当前全部生成身份一致时才读取；seal 前 reference 执行目录存在则拒绝封存。其检查证明所见路径/产物的时序和字节一致性，不形式化证明历史上从未访问其他参考副本。目标缺陷结论另用 `--target-reviews` 提供已确认缺陷、目标匹配、根因 ID 和证据；有效 oracle 的候选报警未经这一步仍是待确认报警。

driver 的机械语义边界：纯表达式求值、类型/字面量渲染、源值来源、词法绑定和可选 source witness 只能拒绝已知不成立的候选；没有为通用组合提供正确性证明。state-context 的 may-effect witness 表明插入操作可能影响观察，不能当成 expected-value witness。审核必须覆盖完整冻结测试：选中断言之前保留的 `raises` 或其他断言、被中和断言的求值效果、被截去后缀/清理的影响，以及完整 expected 表达式，不能只核验被替换的单个 literal。

当前冻结预算为 128 pending、24 shown、每轮至多 8 completion、一次调用、10,000 输出 tokens、temperature=0；最多 8 个物化候选自然低于 10 个最终测试上限。静态拒绝、模型省略、guard=false、表达式校验拒绝、物化拒绝和 API 协议失败分别保留；特别是 provider 在 JSON 模式下因请求格式拒绝时，属于通信/协议阻断，不能称为错误 oracle 或语义能力的漏检证据。它仍意味着该轮尚未完成严格十四单元目标。

评价脚本的合成回归覆盖空 `errors` 下的 suite error、来源控制全部参数叶子、未声明/缺失控制、默认不读参考、未知 oracle 与参考差分分离、独立目标判定、全十四单元成功门槛，以及封存后产物变化。测试只使用临时合成 JSON，不执行被测程序或调用模型。
