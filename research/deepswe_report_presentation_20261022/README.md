# DeepSWE 独立双语报告 / Portable bilingual report

[打开 HTML / Open the HTML](../../experiments/reports/docs/20261022_deepswe_failure_analysis_n211.html)

本目录维护 211 个 trial 的中文、英文叙述和证据展示定位。页面中的 English / 中文 按钮切换界面、任务概述与全部分析。`?lang=en` 可指定英文初始视图。代码、issue 和日志属于原始证据，保留源文本语言。

This directory contains Chinese and English narratives and evidence selectors for all 211 trials. The English / 中文 button switches the interface, task overviews and every analysis. Add `?lang=en` to start in English. Issues, code and logs retain their source language.

## 每条包含什么 / What each trial contains

| 内容 / Content | 展示方式 / Presentation |
| --- | --- |
| 任务 / Task | 中英文概述、完整 issue / Bilingual overview and complete issue |
| 提交 / Submission | 完整 patch、文件清单、增删行 / Complete patch, changed files and line counts |
| Evaluation | 官方 F2P/P2P、实际失败消息、出错测试源码定位、完整测试补丁、stdout 摘录 / Official scores, failure messages, source context, complete test patch and stdout excerpts |
| Agent validation | 当前分析、相关真实验证命令及输出、提交中的测试摘录 / Analysis, actual validation commands and outputs, submitted test excerpts |
| 组合联系 / Gap reasoning | 条件组合、缺少的有效观察、补测反馈可能引导的修复、条件与限制 / Interaction, missing effective observation, possible repair prompted by feedback, conditions and limits |
| 组合表 / Gap table | 按实际条件选择维度的逐案表格，可点击证据步骤 / Per-trial tables with actual condition dimensions and linked evidence steps |
| 测试生成过程 / Test generation | 阶段导航、记录原文、操作与反馈、事后分析 / Stage navigation, recorded text, actions and feedback, retrospective analysis |

Evaluation 和 validation 在宽屏并排显示，小屏上下排列。完整 issue、提交 patch 和每个任务的评价测试补丁内嵌在 HTML 中。日志与开发步骤是标注的摘录，省略用 `[…]` 或 `…` 表示；评价测试中找不到相关源码时明确说明。测试行号指向原评价补丁，ATIF step 指向真实开发轨迹。

Evaluation and validation appear side by side on desktop and stack on narrow screens. The complete issue, submitted patch and evaluation test patch are embedded. Logs and development steps are labeled excerpts; `[…]` or `…` marks omissions. A missing source location is explicitly disclosed. Test line numbers refer to the evaluation patch, and ATIF steps refer to the development trajectory.

页面全部样式、脚本和证据数据均内嵌，不加载网络资源，不依赖仓库中的其他文件。完整源码按需渲染，并可从页面直接下载；语言偏好仅尝试保存在本地浏览器。页面支持双语搜索、判定筛选、展开与收起及 trial 锚点。

Styles, scripts and evidence data are embedded. The report loads no network resources and needs no neighboring repository files. Complete source is rendered on demand and can be downloaded from the page. The browser may remember the language preference locally. Search covers both languages; judgment filters, expand/collapse controls and trial anchors are available.

## 加载方式 / Loading behavior

HTML 内保存独立压缩的数据块：211 个 trial、211 份测试生成过程、391 份去重后的完整源码和一个双语搜索索引。首次只解析约 298 KB 的目录及当前展开的 trial；其余 trial 在展开时解压和解析。时间线在查看时才解压，完整 issue、提交 patch、evaluation 测试补丁在查看或下载时才解压；未展开的验证输出、失败清单和其他代码也不提前生成 DOM。搜索索引在首次输入关键词时单独解码，不需要展开全部 trial。重复或同时请求同一份材料会共用缓存。

The HTML stores independently compressed chunks for 211 trials, 211 test-generation views, 391 deduplicated source documents and one bilingual search index. Startup parses an approximately 298 KB manifest and the currently opened trial. Other trials decode when expanded; trajectories decode when viewed, and complete issues, patches and evaluation tests decode when viewed or downloaded. Collapsed outputs, failure lists and additional code are rendered on demand. The search index decodes on the first keyword search without loading every trial. Repeated or concurrent requests share cached results.

单文件离线阅读仍会读取整个 HTML；这里的分批加载是分块解压、解析和渲染。压缩减少文件读取量，按需解析减少首次阻塞，不依赖服务器或额外文件。压缩数据使用浏览器内置的 `DecompressionStream` 解码；不支持该 API 的浏览器会提示更新。

Offline use still reads the whole HTML file. Progressive loading here means deferred decompression, parsing and rendering. Compression reduces file I/O, and deferred parsing reduces startup blocking without a server or extra files. Decoding uses the browser's built-in `DecompressionStream`; unsupported browsers receive an explanatory message.

当前版本的[离线启动测量](../../results/failure_analysis/20261022_standalone_report_n211_r01/startup_visuals.json)包含正常 CPU 的 5 次独立运行及 CPU 限速 4 倍的 3 次运行。记录控件可操作、首条内容插入和绘制的不同时间；本机测量不代表其他机器的速度保证。

The linked current-version startup measurements use five independent normal-CPU runs and three runs with 4× CPU throttling. Controls readiness, first-trial DOM insertion and paint are recorded separately; results on this machine are not a latency guarantee elsewhere.

## 数据约束 / Data constraints

三个 `content_*.json` 合计 211 条，各含 `n`、`trial`、`overview.zh/en`、`zh/en` 四项分析、`validation_steps` 与 `evaluation_terms`。展示文本独立解释当前 trial。证据定位用于选择展示窗口，不参与生成判定。

The three `content_*.json` files cover all 211 trials. Each contains the trial identity, bilingual overview, four analysis fields in each language, validation step IDs and evaluation source selectors. Each narrative explains the current trial independently. Selectors choose display windows and do not generate judgments.

[组合表与测试生成记录](../deepswe_gap_visuals_20261022/README.md)保存全部逐案表格、436 个相关步骤和逐字核对的原文摘录。点击表中的步骤可打开对应轨迹。记录概括与事后分析明确区分，不将缺少记录解释为 agent 从未考虑过某个条件。

The linked gap-table and test-generation records contain all per-trial tables, 436 selected steps and verbatim checked excerpts. Table citations open the corresponding trajectory. Summaries are separated from retrospective analysis; missing records do not prove that the agent never considered a condition.

判定为 88 条直接支持、30 条有条件支持；51 条单项/接口问题、39 条证据不足、2 条正确反馈已产生、1 条未关联当前失败。未运行新的被测测试或 coding agent 修复实验；潜在改善不是已测得的 F2P/P2P 提升。双语与证据展示检查不构成独立复标。

Judgments comprise 88 supported and 30 conditional combination gaps, 51 single-feature/API issues, 39 cases with insufficient evidence, 2 with correct feedback already available and 1 without a link to the observed failure. No new subject tests or coding-agent repair experiments were run. Potential improvements are not measured F2P/P2P gains. Translation and evidence-display checks do not constitute independent re-labeling.

## 构建 / Build

```bash
python3 scripts/build_deepswe_failure_manual_report.py
python3 scripts/build_report_readers.py --source docs/20261022_deepswe_failure_analysis_n211.html
python3 scripts/audit_deepswe_standalone_report.py
```

渲染器为 [build_deepswe_standalone_report.py](../../scripts/build_deepswe_standalone_report.py)，界面源码为 [viewer.css](../../scripts/deepswe_report/viewer.css)、[viewer.js](../../scripts/deepswe_report/viewer.js)、[loader.js](../../scripts/deepswe_report/loader.js)、[visuals.js](../../scripts/deepswe_report/visuals.js) 和 [visuals.css](../../scripts/deepswe_report/visuals.css)。[检查输出](../../results/failure_analysis/20261022_standalone_report_n211_r01)包含构建清单、完整性审计、浏览器检查、加载性能测量和桌面/移动截图。

The renderer and interface sources are linked above. Build manifests, integrity checks, browser checks and desktop/mobile screenshots are stored in the linked check outputs.
