# 全部 211 个失败 trial 的组合验证缺口分析

全部 211 个 trial 已逐条审查，涉及 90 个任务、75 个项目，无待审条目。

打开[独立双语 HTML](../../experiments/reports/docs/20261022_deepswe_failure_analysis_n211.html)，可一键切换中文和英文。单个文件包含全部任务需求、提交补丁、评价测试补丁，以及判定所需的失败消息、日志和开发验证摘录。内容压缩分块保存，trial 详情、测试生成过程及完整源码在查看时解码；保存 HTML 后可离线阅读。页面按 trial 展示任务上下文、具体组合表、测试生成时间线、evaluation / validation 并排对照和可能的修复路径，小屏幕自动改为上下排列。表中的步骤可直达记录原文、操作和反馈，原始记录与事后分析分别标明。

## 判定标准与结果

若 validation 中存在有效组合测试，其反馈是否可能帮助 coding agent 改进 patch，使 evaluation 通过或提高部分 F2P / P2P？组合至少涉及两个有独立意义、共同作用于同一对象、数据流或生命周期的条件、功能、状态或操作。判断需说明实际失败、有效验证不足、可判错的观察及反馈可能引导的修复。

已有输入但只打印、断言不敏感或期望违背明确需求，仍可能存在有效观察缺口。正确失败反馈已产生却被忽略的，单列反馈处理问题。公开契约不明确时保留条件或证据不足。

当前结果：88 条直接支持，30 条有条件支持，共 118 条；另外 51 条主要是单项或接口问题，39 条证据不足或契约待定，2 条已有正确失败反馈，1 条未建立与当前失败的联系。10 条正例涉及错误 oracle。有条件项保留需求解释、验证时点或错误定位的不确定性。

F2P / P2P 保留官方分子分母，并与每条 reward、metadata 核对。失败报告可能包含父 suite、参数化重复和 missing 条目，不能把失败行数当作独立缺陷数。未运行新补测或 coding agent 修复实验，实际收益为未知。

## 当前数据和证据

- [全部当前判定 JSONL](reviews.jsonl)、[逐条 JSON](trials)、[统计及任务索引](summary.json)、[判定协议](protocol.json)。
- [633 份 evaluation 文件清单](../../results/failure_analysis/20261021_counterfactual_gap_n211_r01/acquisition.json)：每个 trial 的 CTRF、reward 和 stdout。
- [90 个任务的测试及配置清单](../../results/failure_analysis/20261021_counterfactual_gap_n211_r01/evaluation_tests/manifest.json)。
- [双语叙述和展示用证据定位](../deepswe_report_presentation_20261022/README.md)：逐条的中英文分析、任务概述、真实验证步骤和评价测试标识。
- [组合表与测试生成记录](../deepswe_gap_visuals_20261022/README.md)：211 份逐案表格、436 个相关步骤和 405 段人工选取并逐字校验的原文摘录；展示改进不改变当前判定或分数。

任务需求、最终补丁和开发记录来自各 trial 的实际运行材料。开发验证代码可能早于最终提交；页面明确标记步骤和摘录，不把早期结果自动归于最终版本。全部轨迹未重新逐字全文审读，未读取参考实现。判定是使用 evaluation 证据的 AI 辅助手动事后归因，未做独立复标，不能当作盲测发现率。

## 生成和核验

```bash
python3 scripts/build_deepswe_failure_manual_report.py
python3 scripts/build_report_readers.py --source docs/20261022_deepswe_failure_analysis_n211.html
python3 scripts/audit_deepswe_standalone_report.py
python3 scripts/audit_deepswe_counterfactual_review.py
```

生成器只组装已有的手动判定，不按关键词生成语义标签。双语 HTML 的[构建清单与检查结果](../../results/failure_analysis/20261022_standalone_report_n211_r01)记录独立文件、完整嵌入内容、校验和与浏览器验证。阅读副本与主 HTML 逐字节相同。
