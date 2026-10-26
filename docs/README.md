# 研究文档

先阅读下表中的当前入口。旧版评价、实现说明和前期汇报见 [归档目录](archive/README.md)。每个归档项都说明原因和后续阅读位置。

本页链接使用已修复本地地址的阅读副本。原报告正文保持不变。211 个 trial 的双语报告及其阅读副本完全一致，可离线打开。

[主要 pilot](../experiments/pilots/README.md) · [跨轮任务索引](../experiments/pilots/tasks.tsv) · [独立研究审查](../experiments/reports/research/independent_review_20261019/independent_report.html)

## 当前阅读入口

当前入口表示适合继续查阅。各报告仍采用自己的实验设置和判断规则。30 项 pilot 的目标修订与 211 个 trial 的新归因使用不同范围，不合并其分母。

| 日期 | 文档 | 内容与范围 |
|---|---|---|
| 20261022 | [211 个 trial：组合缺口与 evaluation 归因](../experiments/reports/docs/20261022_deepswe_failure_analysis_n211.html) | 当前双语报告。88 条直接支持、30 条有条件支持。内嵌完整 issue、patch 和评价证据；未测修复收益。 |
| 20261016 | [验证历史与执行观察：12 项 pilot](../experiments/reports/docs/20261016_validation_history_pilot_n12.html) | 比较验证改动、诊断执行和补测。保留五组设置、重复运行及失败输出。 |
| 20261016 | [原验证范围引导：6 项 pilot](../experiments/reports/docs/20261016_validation_context_pilot_n06.html) | 比较原验证范围、开发历史和执行反馈。 |
| 20261016 | [Testora 与 RippleGUItester 阅读](../experiments/reports/docs/20261016_testora_rippleguitester_literature_review.html) | 比较问题抽象、模型职责和信息使用方式。 |
| 20261010 | [行为区别搜索：研究抽象与算法规格](../experiments/reports/docs/20261010_behavioral_gap_method_design.html) | 保留候选方法与实现规格；建议不等于已验证效果。 |
| 20261010 | [T08 与 30 项 pilot 的评价修订](../experiments/reports/docs/20261010_behavioral_gap_evaluation_revision_t08.html) | 解释 30 项历史 pilot 的目标从 23 项修订为 22 项。 |
| 20261010 | [30 项任务：trajectory 与程序关系分析](../experiments/reports/docs/20261010_trajectory_program_analysis_n30.html) | 保存轨迹审读、程序片段和验证遗漏的观察。 |
| 20261010 | [轨迹信息与程序计算：8 项 pilot](../experiments/reports/docs/20261010_trajectory_guidance_pilot_n08.html) | 独立输入对照；不能用后续不同设置替代其结果。 |
| 20261009 | [程序分析引导：8 项 pilot](../experiments/reports/docs/20261009_program_guidance_pilot_n08.html) | 比较开放模型、程序条件对比和查询反馈。 |
| 20261009 | [行为区别补测 v3：实现与验证](../experiments/reports/docs/20261009_behavioral_gap_implementation_v03.html) | 说明测试查询、候选选择及执行后修正的实现。 |
| 20261008 | [输入材料、程序条件和执行反馈：6 项诊断](../experiments/reports/docs/20261008_input_evidence_diagnosis_n06.html) | 保留四组材料对照，作为输入缺陷的诊断依据。 |
| 20261005 | [自动提取与补测：6 项早期 pilot](../experiments/reports/docs/20261005_automatic_augmentation_pilot_n06.html) | 早期设置有独立参考价值；按当时的判断规则读取。 |
| 20261005 | [手选材料与轨迹对照：8 项早期 pilot](../experiments/reports/docs/20261005_manual_context_pilot_n08.html) | n08 表示生成部分的案例数；提取部分检查 17 条轨迹。 |

211 项报告的数据入口：[evaluation 归因记录](../research/deepswe_counterfactual_review_20261021/README.md) · [双语展示](../research/deepswe_report_presentation_20261022/README.md) · [组合表与测试生成过程](../research/deepswe_gap_visuals_20261022/README.md)。

## 文件命名

文档使用 `YYYYMMDD_<主题>_<文档类型>[_vNN][_nNN].扩展名`。使用小写英文和下划线。例如 `20261009_behavioral_gap_detection_v03_n30.html`。主题用词与 experiments/、results/ 的主题含义一致。

日期取报告或研究记录明确标注的日期，不取本次整理日期。v2 的 30 项报告使用完成日期 20261009；17 项进展报告使用证据截止日期 20261003；当前双语报告使用展示版本日期 20261022。

`vNN` 表示文档所讨论的方法版本。`nNN` 表示报告明确涉及的案例数。T08 等单项修订可使用案例 ID。实验运行 ID 单独记录，不从文件名推定运行次数。

`README.md`、`catalog.json`、`path_map.tsv` 和 `Makefile` 使用固定名称。[catalog.json](catalog.json)记录主题、原路径、日期、归档依据和关联 pilot。

## 归档标准

旧评价被新规则或复核替代、旧实现被后续版本修正、早期方法讨论已形成后续规格时，将对应报告移入 archive/。前期阶段性进展和汇报材料也放在这里。

有独立设置或观察价值的 pilot 继续保留。文件较早或实验结果较差都不足以单独构成归档理由。归档报告及其原始实验数据继续可读。

## 路径与维护

[本目录的旧路径映射](path_map.tsv) · [全仓库映射](../results/path_map.tsv) · [整理检查](../experiments/maintenance/20261023_docs_layout/verification.json)

```bash
# 查询旧文档位置。
python3 scripts/result_paths.py docs/deepswe_failure_manual_20261006.html

# 更新阅读副本、文档目录和实验索引。
python3 scripts/build_experiment_index.py
python3 scripts/build_experiment_index.py --check
```

原 HTML 中的相对链接按 catalog.json 的 link_base 解释。从本页进入阅读副本，可使用更新后的链接。冻结记录中的原路径不改写。
