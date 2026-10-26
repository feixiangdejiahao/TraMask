# Research reports

[后续 skill 工作区](../research/workspaces/test_augmentation/README.md)保存新的方案和实验记录。[历史材料分类索引](../research/history/README.md)保留各轮材料入口。下列报告按各自版本解释，目录整理不改变其证据状态。

[2026-10-19 独立研究审查](../research/independent_review_20261019/independent_report.html)：独立线程先核查原始材料，再查看历史评分。两个子线程分别核查反例和相关论文。报告提出候选问题抽象、方法机制及后续 pilot，并说明独立性与阅读范围。T08 历史执行事实已在最终稿修正。本轮没有运行新实验。

[十二任务 pilot：验证改动、诊断执行与组合补测](validation_evolution_pilot_20261016.html)：完成 12 项任务、5 组设置、每组 2 次重复，共 120 次任务运行。每次最多 3 个候选。125 份最终文件包含 228 个命名测试。逐项复核确认 18 个正确检测输出、16 个正确补测输出，另有 104 个不符合修复相关标准的肯定候选和 3 个语义未定候选。成功数包含跨设置及重复运行：正确检测涉及 6 项任务，正确补测涉及 4 项任务。正确补测中 4 份获原样动态差分支持，12 份采用 gold 静态语义判断。报告分列四项指标、候选数量作用、14 次格式失败、查询接口混杂、停用尝试成本，以及 T13 诊断“通过”掩盖真实行为差异的配对对照。当前结果不支持直接把更多历史文本作为贡献。建议集中检验历史验证中的行为区别是否保留在新测试的输入、操作和最终观察中。未测 resolution rate。[完整统计](../experiments/validation_evolution/results/pilot12_20261016_v3/evaluation/combined_summary.json) · [逐项复核](../experiments/validation_evolution/results/pilot12_20261016_v3/evaluation/review.json) · [完整性核验](../experiments/validation_evolution/results/pilot12_20261016_v3/evaluation/completion_audit.json)。

[新 pilot：从原验证范围搜索组合缺口](validation_context_pilot_20261016.html)：完成 6 项任务、4 组设置、每组 2 次重复，共 48 份正式输出。LLM 参与假设、程序查询、补测和一次修正。按原补丁失败、gold 通过的规则，源码与测试组检测及补测均为 3/6、1/6；增加开发历史后为 2/6、3/6；按原验证范围搜索为 3/6、2/6。无执行反馈组检测为 3/6、2/6，补测为 3/6、0/6。报告另列误报任务、固定目标漏检、7 份最终交付失败，以及 8 份统一目录查询修复复测。复测没有新增成功项。当前对照支持执行反馈帮助构造测试，尚未显示历史事件或范围提示的稳定增益。未测 resolution rate。[冻结版统计](../experiments/validation_context/results/pilot6_20261016_v1/evaluation/summary.json) · [逐项复核](../experiments/validation_context/results/pilot6_20261016_v1/evaluation/review.json)。

[Testora 与 RippleGUItester：对组合测试补强研究的启发](testora_rippleguitester_review_20261016.html)：精读两篇正式论文，并核对作者代码和部分发布数据。报告比较问题抽象、LLM 职责、历史证据和执行反馈，解释分类精召率与端到端检出的区别。建议把 trajectory 中的验证限制转成具体待检上下文，让程序核验组合条件；两处源码事实的关系可作为局部检查，不预设为全部候选的必要入口。建议尚未实现或评估。本轮没有新增 provider 调用、补测或 benchmark 执行。[完整阅读记录](../experiments/literature/research/testora_rippleguitester_20261016/synthesis.json)。

[研究抽象与算法共识：搜索原验证未能区分的行为](augmentation_abstraction_consensus_20261010.html)：修订 T08 统计，并与不继承历史对话的独立 Codex 线程进行多轮质询。共识以一个源位置绑定的行为区别为搜索目标，用真实执行指导局部测试修改。报告明确轨迹新增信息、最终测试已有信息和源码推断的归因边界，给出搜索状态、单步操作、记录格式、终止条件和实现接口。这是候选方法及实现规格，尚未实现新完整检测器或运行新效果实验。[讨论记录](../research/abstraction_debate_20261010/debate.json) · [算法规格](../research/abstraction_debate_20261010/algorithm_spec.json)。

[T08 统计修订：已有输入，错误预期](augmentation_t08_statistics_revision_20261010.html)：当前评价版本。将 T08-R1 从组合输入缺口移至已有测试的预期问题。固定目标从 23 项变为 22 项，正例任务仍为 18。原方法检测和补测各命中 1 项、漏检 21 项；v2 固定目标命中 0 项、漏检 22 项；v3 原预算命中 1 项、漏检 21 项；追加判断后命中 2 项、漏检 20 项。任意正确目标、误报、费用和执行结果不变。各轮 active_evaluation.json 已指向重算结果，原统计归档保留。[修订数据](../research/t08_statistics_revision_20261010/summary.json)。

[30 项任务：从开发过程与程序关系搜索组合缺口](augmentation_trajectory_program_study30_20261010.html)：索引 30 条原始轨迹的 4,542 个步骤，逐项审读关联 128 个步骤和 42 处源码片段。报告连接原验证的具体限制、agent 的推理与测试修改、程序中的对象身份和行为传播，以及最终断言。详细解释 T13 共享捕获单元、T17 存在性、T27 提交值和 T28 默认 hash 假设。T08 的缺结束分隔符输入已有接受断言，当前已改归预期判断问题。提出以验证限制引导程序与模型共同搜索的候选方法。本轮没有新增模型调用或被测程序执行。[30 项记录](../research/trajectory_program_search30_20261010/review.json) · [分析范围](../research/trajectory_program_search30_20261010/summary.json)。

[Coding agent 的组合缺口检测：开发过程与程序计算对照](augmentation_trajectory_pilot_20261010.html)：完成 8 项任务、4 组方法、每组 2 次重复，共 64 次检测。代码与测试片段组正确 4/8、3/8；加入开发过程后为 3/8、4/8；模型先建行为模型为 4/8、2/8；再加入程序计算为 3/8、2/8。逐条静态复核 79 条肯定报告，34 条符合原补丁失败、gold 通过的规则，45 条不符合。31 个行为模型均未获得完整的原测试输入绑定。报告单列接口格式缺陷、语义绑定错误、有效目标在复核阶段丢失，以及 T28 自定义查询标识的新发现。只做检测与静态审阅；未生成或执行新补测，未测 resolution rate。[完整统计](../experiments/relation_distinction/results/trajectory_contrast8_20261010_v2/evaluation/summary.json)。

[Supervisor-Skills 方法审查：从相关代码转向原验证无法区分的行为](augmentation_supervisor_review_20261010.html)：使用 `idea-evaluator` 和 `tech-paper-template`，核对当前实现、八任务 pilot、关键原测试及相关论文。建议不再以“模型选位置＋局部反馈”为核心贡献，改为从原验证的具体限制出发，绑定行为区别并搜索可观察的组合。报告比较五项最近邻工作，区分算法失败与 gold 相对评估不匹配，并给出三个步骤的候选方法和检测 pilot。新机制尚未实现。本次没有新增模型调用或测试执行。

[八项任务 pilot：程序分析应如何帮助模型发现组合缺口](augmentation_contrast_pilot_20261009.html)：完成 6 组、每组 8 项任务、每项 2 次的检测实验，共 96 次运行。开放模型发现正确检测 4/8、3/8；加入局部程序条件对比后为 5/8、4/8。模型先选位置再接收程序反馈为 3/8、4/8；复用同一计划但删除反馈为 5/8、4/8。逐条复核 127 条肯定报告，69 条合格、53 条不合格、5 条待定；条目包含跨组和重复运行的重复发现。报告另列固定目标漏检、同一缺陷的替代观察、输入与调用审计，以及当前学术贡献的边界。未生成或执行新补测，未测 resolution rate。[完整统计](../experiments/relation_distinction/results/contrast_pilot8_20261009_v2/evaluation/summary.json)。

[独立上下文讨论：算法改进共识](augmentation_algorithm_debate_20261009.html)：启动不继承历史对话的 Codex 线程，完成两轮讨论。T28 的更短静态反例推翻了“必须继续延长观察链”的强解读。共识是先拆开发现与核验，并平等比较开放模型发现与局部程序对比。程序引导不预定为赢家；报告给出支持范围、四组 pilot、同材料证伪对照和避免过拟合的约束。本次未改算法、未重跑 DeepSeek、未生成或执行新测试。

[改进后检测实验：漏检任务的分类诊断](augmentation_detection30_v3_diagnosis_20261009.html)：原报告归档。修订 T08 后，固定漏检为 20 项：更相关候选未选中 4 项、关键关系或阶段未连通 11 项、输入类别或取值不当 4 项、需求误读 1 项。另列 T08-N1。每项包含原验证范围、缺失组合、原补丁与 gold 的区别，以及实际输入和答复。分类来自静态审读，不是因果消融结果。[当前分类数据](../experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1/evaluation/t08_oracle_reclassification_v1/diagnosis_v1/summary.json)。

[30 个任务：改进后的组合缺口提取与检测](augmentation_detection30_v3_20261009.html)：原报告归档，只检测，不生成或执行补测。按当前 22 个固定目标重算，原预算命中 1 项、漏检 21 项；统一追加判断后命中 2 项、漏检 20 项。正确检测任务仍为 2 个和 4 个，误报仍为 2 项。T08 只确认资源关闭，不能确认流已读完；单列该限定观察时，保守成功数仍为 3/30。修订后的 23 个扩展目标中，3 项保留直接关系，仅 1 项由程序明确表达关键取值。[当前原预算统计](../experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1/evaluation/t08_oracle_reclassification_v1/summary.json) · [当前补充后统计](../experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1/evaluation/t08_oracle_reclassification_v1/decision_recovery_v1/summary.json)。

[组合测试补强 v3：实现与验证](augmentation_v3_implementation_20261009.html)：修正测试查询、追加位置说明和反馈预算。用具体条件及其行为影响选择候选。生成后检查测试是否保留条件。本地回归和历史记录回放验证了实现；尚未重测模型效果。

[改进算法的检测与补测失败原因](augmentation_pilot30_v2_diagnosis_20261009.html)：复核 240 份首轮输入、全部交互和最终测试。区分候选未选中、条件未具体化、证据查询错误、需求关系误判、测试目标改变和缺少反馈修正。发现测试查询忽略路径参数，以及 agent 提示遗漏追加代码的位置说明。报告说明 T13、T17、T24 已获得关键线索却仍漏检的不同原因。本次没有新增模型调用，也没有修改算法或原实验成绩。

[改进算法的 30 个任务实验结果](augmentation_pilot30_v2_20261008.html)：原报告归档，2026-10-09 完成。30 个任务均完成提取与 DeepSeek 模型处理。最终保留 78 项测试建议。正确检测和正确补测仍各为 1/30，均来自 T08 的其他目标；77 项建议不满足错误检出标准。按当前固定目标重算，命中 0/22，漏检 22 项。本轮没有测量 resolution rate。[当前统计](../experiments/relation_distinction/results/pilot30_v2_20261008_v1/evaluation/t08_oracle_reclassification_v1/summary.json)。

[改进算法实现与本地验证](augmentation_implementation_v2_20261008.html)：已实现联合条件搜索、逐次调用的原测试范围、局部证据表示，以及有预算限制的模型查阅和执行反馈。报告说明六条真实任务的提取检查及剩余限制。本次没有调用外部模型，不报告新的检测或补测成功率。

[六条任务诊断对照：材料、条件与执行反馈](augmentation_diagnostic6_20261008.html)：已运行 T10、T13、T17、T20、T24、T28 的四组对照。每组两次调用预算；C/D 共用首轮。原输入、人工材料、增加程序条件、加入反馈分别在 0、1、1、1 条任务生成揭示参照错误的测试。逐项比较材料变化，并单列候选问题补充检查及输出额度补跑。结论指向候选表示、输入状态来源和后续观察关系；不是自动算法整体性能或 resolution rate。

[30 条任务 pilot：漏检与补测失败的原因](augmentation_pilot30_diagnosis_20261008.html)：原诊断报告归档。初始检查 18 条参照任务中的 23 个目标，以及原候选、实际模型请求、答复和测试。T08 修订后，当前目标为 22 项，漏检 21 项。区分候选缺失、覆盖判断扩大、测试未触发关键条件及缺少执行反馈。[当前统计](../experiments/relation_distinction/results/pilot30_20261007_v1/benchmark_reverse_v5/diagnosis_summary.json)。

[30 个 trial：从失败测试与补丁差异推导组合缺口](augmentation_pilot30_reverse_20261008.html)：v4 原报告归档。当前 v5 合并目标为 22 项，涉及 18 条任务。原方法检测、生成各命中 1 项，漏检 21 项。其中 12 项对应选定的 benchmark 失败，其余 10 项有静态差分依据。30 项代表性失败现分为 12 项组合缺口、4 项原联合测试预期问题、9 项非组合差异、1 项未复验和 4 项待定。实际 resolution rate 未测量。[当前数据入口](../experiments/relation_distinction/results/pilot30_20261007_v1/active_evaluation.json) 指向 v5；[修订说明](augmentation_t08_statistics_revision_20261010.html)。

[旧 41 项历史目标的静态筛选](augmentation_pilot30_static_20261008.html)：主报告附录。17 项符合原补丁失败、gold 通过，分布于 15 条任务；6 项原补丁已满足，14 项 gold 也未满足，4 项待定。此前 28 个待定目标中，10 项转正，14 项不满足 gold 通过条件，4 项仍待定。方法命中 T24-G1，漏检其余 16 项。主报告重新推导目标，不能混用两个集合的分母。

[30 个 trial：按错误检出与修复相关性修订历史缺口](augmentation_pilot30_relabel_20261008.html)：归档 v2。旧规则保留 7 项，撤销 6 项，28 项待定。上述静态筛选附录已逐项处置这 28 项。原标签和实验记录保持冻结。

[30 个 trial：原补丁与 gold 的修复相关性复核](augmentation_pilot30_gold_20261008.html)：重新解释“任意缺口”与“历史目标”。337 份原样测试对照中，T04、T23、T24 含有效差分测试；此前完成的 T11 环境对齐另提供一项。当前确认 T24 的补测直接暴露原 benchmark 同一失败。报告列出全部 30 个 trial，手动对照私有接口依赖案例的语义，并指出五个漏掉的直接修复相关历史目标。实际 resolution rate 提升尚未测量。旧 20/30 及 251 份测试属于初步 AI 分组审阅结果，不是独立人工逐条核验的金标准。

[30 个 trial 的原组合缺口检测与补测 pilot](augmentation_pilot30_20261007.html)：请求 DeepSeek-v4-flash，provider 实际返回 DeepSeek-V4.1-Flash。旧 AI 审阅标记 20 个 trial 获得有效补测，3 个 trial 命中历史预标注目标，漏掉 38/41 项目标。旧标签还包含 34 份误报和 41 份待定。上述语义标签的审阅强度已在新报告中更正。原始实验记录保持不变。

[组合缺口的关系结构与程序筛选](combination_relation_census_20261007.html)：对DeepSWE v1.1中DeepSeek-v4-flash的211份失败审读逐条重编码。264个已确认验证缺口条目中，200个归为单关系，64个归为多关系；另22个候选或已有反证的条目不计入。报告分别给出失败记录和90个去重任务的统计，说明关系数量与输入维度的区别，并提出程序筛选及短关系链搜索方法。本轮未运行新补测，未评价自动检测性能。

[DeepSWE 全部失败记录：验证缺口与方法设计依据](deepswe_failure_manual_20261006.html)：检查 DeepSeek-v4-flash 的全部 211 条失败记录，涉及 90 个任务和 75 个项目。每条说明原测试、具体遗漏、程序关系、开发过程及代码版本。每条也由另一位 AI 分析助手复核。综合部分给出方法抽象、创新性边界和下一轮小规模实验建议。验证缺口不等于实现错误。

[自动补充验证测试：完整报告](automatic_augmentation_pilot_20261005.html)：解释当前问题抽象、算法及学术新意。报告说明六个案例的选择、四项事先指定的遗漏检查、两种模型输入、三次互不传递结果的尝试、误报与漏报的处理，以及全部实验结果。报告使用原始数据，读者无需回看此前讨论。

[手选材料实验：完整报告](trajectory_gap_pilot_20261005.html)：解释较早的两部分实验。第一部分评价程序提取材料，第二部分用手选材料比较有无开发步骤时的测试生成。报告分别保留格式修复前后的成绩，并区分有效补测与有效错误检出。

[HTML progress report](research_progress.html): method families and subversions, experiments, all 17 trials, false alarms, model cost, and next research decisions. The English report uses short sentences and includes a Chinese term guide. Open it directly in a browser. It has no external page dependencies.

## Archived presentation

[PDF](combination_testing_research.pdf) · [Beamer source](combination_testing_research.tex)

English, 27 slides, 16:9. The deck covers the problem, observation-production-path research abstraction, implemented workflow, formal definitions, HTTPX and Koota worked examples, all 17 trial results, contribution hypotheses, limitations, and future evaluation.

## Build

From the repository root:

```bash
make -C docs
```

Required TeX packages: Beamer, TikZ/PGF, FontAwesome5, Latin Modern, AMS math, booktabs, and listings. The build uses `latexmk` and `pdflatex`. All figures are native vector graphics; there are no external assets or model calls. Intermediate files go to the ignored `docs/build/` directory.

## Evidence snapshot

The completed fresh v3 experiment is frozen at `7a8ff95`: 16 confirmed defect witnesses across 17 development trials / 14 distinct tasks, with 12 retained and 4 revised oracles. It does not include a patch-repair/hidden-test loop. The later optional strict/may source-priority prototype is presented separately; its completed fixed-pool census found no exposure gain (strict unchanged; may worse). No new model or subject execution was performed in that study.

Authoritative local evidence:

- Main score: `results/relation_search_20260929_v3/evaluation/uniform_fresh_impact_v3/checkpoint_14.json`.
- HTTPX witness: `N01_c8e075c82686eb21c4222575_deliveries.json` in the same directory.
- Koota witness: `N09_08f2c625387570b30312_runtime_index.json` in the same directory.
- Generated source and native controls/failures: `results/relation_search_20260929_v3/uniform_fresh_impact_v3/N01/round_000/` and the corresponding `N09` directory.
- Current method and evaluation: `research/method_design.md`, `research/relation_search_v3_evaluation.md`, and `research/patch_observation_priority_protocol.md`.

The delivered PDF was compiled without LaTeX errors or overfull/underfull boxes, rendered and visually reviewed page by page, and checked for text extending beyond page boundaries. Code on the worked-example slides is explicitly condensed from executed witnesses; exact source remains in the experiment artifacts.
