# 组合缺口表与测试生成过程 / Gap tables and test-generation trajectories

[阅读独立双语报告 / Open the standalone bilingual report](../../experiments/reports/docs/20261022_deepswe_failure_analysis_n211.html)

全部 211 个 trial 均有逐案编写的组合缺口表和测试生成过程。表格围绕实际条件、状态、对象、操作顺序或观察字段选择维度，包含 53 个矩阵、22 个场景表、59 个顺序表和 77 个证据对照表。内容使用 3、4 或 5 列，需要时另加轨迹来源列，不预设固定的 2×2 结构。[统计与数据清单](summary.json)记录当前数量和文件校验值。

Every trial has an individually authored coverage table and a test-generation narrative. Dimensions follow the actual conditions, states, objects, operation order or observation fields: 53 matrices, 22 scenario tables, 59 sequence tables and 77 evidence tables. Content uses three, four or five columns, with an additional trace-evidence column where applicable. There is no fixed 2×2 shape. The linked summary records counts and source-file hashes.

## 表格的含义 / Interpreting the tables

单元格区分已有检查、缺少有效检查、观察不足、正确失败反馈已产生、证据未定和非组合归因。已有输入但只打印、采用弱断言或错误期望，也可能没有形成有效组合检查。非正例不使用确定缺口状态；未知表示证据未定，不等于证明从未测试。表中已有检查或记录结果也不意味着最终补丁已正确。

Cells distinguish recorded checks, missing effective checks, weak observations, correct feedback already available, uncertain evidence and non-combination attribution. An input can exist without an effective combined check when it only prints output, uses a weak assertion or expects the wrong result. Non-positive cases do not show a definite gap. Unknown evidence does not prove that an input was never tested. A recorded check or result does not establish that the final patch is correct.

步骤编号只引用开发 trajectory；evaluation 结果来自评价侧材料，不能用本地测试运行的步骤替代其来源。点击表中的步骤编号，会打开该步骤的原文、操作与反馈。

Step numbers cite the development trajectory. Evaluation results come from evaluation artifacts and are not attributed to unrelated local test runs. Selecting a step number opens its recorded text, actions and feedback.

## 测试生成过程 / Test-generation view

当前选取 436 个与测试规划、生成、运行、修改或反馈解释有关的步骤，并保留 405 段人工选取的原文引用。每个 trial 以阶段导航和步骤详情呈现，支持从组合表跳到对应步骤；未进入主要时间线的表格来源记录也可查看。

The authored narratives select 436 steps related to test planning, creation, execution, revision or feedback interpretation, with 405 selected original-text excerpts. Each trial provides stage navigation and step details. Coverage-table citations open the corresponding step, including supporting records outside the main narrative.

内容分为三个层次：中英文记录概括、agent 实际留下的原文摘录、与缺口关系的事后分析。原文按段落、列表和代码显示，不输出 trajectory JSON。每段引用都校验到真实 `step_id`、源字段和字符区间；操作和输出也与原记录核对。省略处标记为 `…` 或 `[…]`。没有充分理由记录的步骤会明确说明，不推测未记录的动机。

The view separates bilingual editorial summaries, actual agent excerpts and retrospective analysis of the gap. Original text is rendered as paragraphs, lists and code, not trajectory JSON. Every excerpt is checked against its step, source field and character offsets; actions and outputs are also verified. Omissions are marked with `…` or `[…]`. Missing rationale is disclosed instead of inventing an unrecorded motive.

设计参考 [Langfuse 的时间线导航](https://langfuse.com/changelog/2026-08-28-responsive-timeline)和 [Inspect 的逐样本消息查看器](https://inspect.aisi.org.uk/log-viewer.html)，采用阶段总览、逐步查看和记录/评价分离；没有引入这些服务作为运行依赖。

The design draws on Langfuse's timeline navigation and Inspect's per-sample message viewer: an overview of stages, step-by-step inspection and separation of records from evaluation. Neither service is a runtime dependency.

## 文件与核验 / Files and verification

`visuals_001_070.json`、`visuals_071_140.json`、`visuals_141_211.json` 保存全部逐案表格、双语概括和原文选择。它们描述当前证据，不改变原判定或 F2P/P2P。表格与过程由 AI 辅助逐案编写、复核；数据完整性检查不构成独立语义复标。

The three `visuals_*.json` files contain the per-trial tables, bilingual summaries and selected excerpts. They describe current evidence without changing judgments or F2P/P2P scores. AI-assisted per-case authoring and checks do not constitute independent semantic re-labeling.

时间线单独压缩为每 trial 一个数据块，点击时才解压。打开报告、搜索或批量展开 trial，不会解码全部时间线；报告仍为可离线使用的独立 HTML。

Each trajectory view is an independently compressed chunk decoded only when requested. Opening the report, searching or expanding trial bodies does not decode all trajectories. The report remains a standalone offline HTML file.

```bash
python3 scripts/build_deepswe_failure_manual_report.py
python3 scripts/build_report_readers.py --source docs/20261022_deepswe_failure_analysis_n211.html
python3 scripts/audit_deepswe_standalone_report.py
```

[构建与数据校验输出](../../results/failure_analysis/20261022_standalone_report_n211_r01)包含表格、步骤、引用、原始文件和页面功能核验；[加载测量](../../results/failure_analysis/20261022_standalone_report_n211_r01/startup_visuals.json)记录本版本的离线启动表现。
