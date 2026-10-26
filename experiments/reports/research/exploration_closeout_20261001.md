> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/exploration_closeout_20261001.md) · [旧路径映射](../../../results/path_map.tsv)

# 五小时时限后的停止与保存记录

2026-10-01（Asia/Shanghai），用户提醒遵守 goal 的探索时限后，立即停止新增算法探索、模型请求、source census 和真实仓库执行。只完成已有材料的哈希核验及 Git 保存。提醒时 goal 记录的累计活动时间为 27,590 秒，已经超过五小时；此前没有及时收尾，应当纠正。以下结果不能回填既有五小时窗口的成绩。

## 保留的最好已验证结果

当前最好统一首次推理配置为 **16/17**，17 个 trial 的统一 campaign 已完成；N05 尚缺完整正确且实际检错的组合测试。17 个 trial 对应 14 个已见开发任务，不能据此宣称泛化或零漏报。没有验证 patch 修复后的 hidden-test 通过率，也不能称为 issue resolution rate。

- 主配置代码冻结：`7a8ff9521a898bb6ff90f29719e78cabf9964cc6`。
- 已有保存标签：`research-v3-timebox-20260929`，指向 `6829f0a`。
- 独立评价：`results/relation_search_20260929_v3/evaluation/uniform_fresh_impact_v3/checkpoint_14.json`，SHA256 `77272b51d4d7abb4d85a2354dec50b41193c1736482a7dd20fb45a99a7b39542`。
- 本轮源码修复保存：`9979283`。它没有替换上述主配置，不能算新的 16/17 或 17/17 结果。

历史探索见证的并集为 17/17，但需要复用额外探索中的 oracle 回答，不能补足统一首次推理配置缺失的 N05。

## 已完成的源码分析及其边界

缓存等价实验使用固定 17×5 个候选。三个臂对封存原分析结果均为 85/85 完整 JSON 一致；累计分析时间由 100.255 秒降至 58.073 秒。这是计算开销改善，不是检测能力改善。

随后五臂源码修复实验也使用同一 85 个候选，85 个 worker 全部完成，无超时、重试或替换样本。两个 control 的原字段均为 85/85 一致。断言对应恢复了 18 个 actual 编辑后的观察，`changed_assertion_unknown` 实例由 23 降至 6；但 strong 支持仍为 0/85，含 unknown 的候选仍为 83/85。may 数由 baseline 的 21 变为 correspondence 的 24、binder/receiver 的 15、两者合用的 18。没有评定这些变化的准确率，不能报告误报或漏报减少。

结果目录：`results/source_repairs_20261001/run_v1/`。已只读复核 257 个封存输出，哈希全部一致。

- summary SHA256：`5c72418aaca3a538880392a7d36012a2c536dc3616214f87de12577df37f8992`。
- seal SHA256：`0130ed92fa01eb06d9090a83a4d5ac6c32bbd7fa21c9687262b5a231f7c210ae`。

## 单独归档、尚未纳入方法的原型

| 原型 | 已完成 | 尚未完成 |
| --- | --- | --- |
| `source_context_contrasts.py` | 33 项资格测试；精确匹配已有源码前缀中一处输入与 expected 的差异，仅给 review 提示 | 17-trial census、oracle 准确性及检错收益 |
| `go_comparison_probe.py` | 29 项资格测试，含两个独立 Go toy；记录执行过的整数比较关系，缺失记录保持 unknown | 完整独立审查、17-trial census、真实仓库编译/执行及排序收益 |
| `census_go_comparison_probes.py` | 13 项选择资格测试 | 真实 source census 未启动 |
| `study_go_comparison_profiles.py` | 31 项闭合整数编辑/来源/分母资格测试；准备代码已保存 | native driver 未实现，未准备或执行真实 trial，不能视为可用端到端流程 |

这些原型没有启动真实 subject 或 provider。运行轨迹中的比较关系只拟用于候选选择，不能用错误实现的输出制造正确 oracle。停止时所有子任务已经结束；LaTeX/PDF 按用户要求停止处理，其未提交改动没有纳入本次代码归档。
