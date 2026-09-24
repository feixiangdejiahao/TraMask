# 观察变换器实验进度

2026-09-24。目标仍为七例两轮都检出且没有错误/未知报警；截止 08:25:54 UTC。目前未达到。七例为已见开发集。

## 已完成批次

| 批次 | 冻结代码 | 模型请求 | r1 / r2 目标检出 | 已确认错误报警 | 未知报警 | 主要限制 |
|---|---|---:|---|---:|---:|---|
| batch1 | c0d49a2 | 14 | 0/7；0/7 | 3；3 | 0；0 | 12 次 HTTP 400；仅 P4 两轮有产物并执行 |
| batch2 | f0b75b2 | 14 | 0/7；0/7 | 15；16 | 2；2 | P1/r1 冻结失败；两轮各两个候选运行单元编译阻断 |
| batch3 | 1843b0a | 14 | 0/7；0/7（全部协议阻断） | — | — | 14 次 HTTP 200 均无有效最终答案；0 冻结候选、0 候选执行 |

第二批只有请求提示增加 JSON 字样，源输入与算法策略不据第一批执行反馈改变。该修改解决 provider 对 JSON 输出模式的提示要求。首批 12 次失败用量未知，另外两次共报告 29,692 tokens；第二批报告 171,196 tokens。模型请求名是 `deepseek-v4-flash`，响应名为 `deepseek-flash`，不能仅根据别名证明 provider 的内部路由。

第三批的 14 个生成单元全部终结为完成协议失败。13 次响应为 `finish_reason=length`，各报告 10,000 reasoning tokens，最终 content 为空；P7/r2 为 `stop`，最终 content 仅有 106 个 ASCII 空格，报告 5,754 completion tokens，其中 5,647 为 reasoning tokens。独立核对响应与缓存 manifest 的用量一致：prompt 192,874、completion 135,754，共 **328,628 tokens**，其中 reasoning 135,647。14 次冻结也均失败，日志显示缺失轮次 `prepare.json`；这是无有效补全、未物化候选之后的阻断，不是有效补全后的缓存比较错误。三个批次已知用量合计 529,516 tokens，另有首批 12 次失败用量未知；这些是 provider 报告的 token 数，不是货币成本。

第三批两轮各 7 个协议失败单元均保留在固定分母中，空 oracle 清单已独立封存。没有冻结测试义务，也没有候选或参考执行；表中报警项的破折号表示无可评价执行，不能解释为无误报、无漏报或组合空间完整。该批不是有意义的语义负结果。

第二批 106 项物化，98 项完成冻结；其中 72 项实际执行、26 项受编译阻断。全部冻结项均在本批候选执行前完成独立 oracle 标签封存：33 valid、9 invalid、50 inapplicable、6 unknown。33 个有效 oracle 均通过，没有需要目标匹配复核的有效报警。运行叶子、静态测试义务和任务数分别计数，来源控制阻断等诊断可能与编译阻断重叠，不能直接求和。

第一批 P4 两轮先封存 oracle，再运行候选；第二批同样先封存再执行。以上两批均未读取参考补丁、运行参考或读取隐藏 verifier。没有真实缺陷证据时，不以参考通过来证明 oracle。

本地完整证据：[batch1 评价](../results/semantic_transport/batch1/candidate_evaluation_v1.json)、[batch2 评价](../results/semantic_transport/batch2/candidate_evaluation_v1.json)、[第二批事前封存](../results/semantic_transport/batch2/oracle_audit_before_reference.json)、[batch3 评价](../results/semantic_transport/batch3/candidate_evaluation_v1.json)、[第三批协议与用量审计](../results/semantic_transport/batch3/completion_protocol_audit_v1.json)、[第三批空项封存](../results/semantic_transport/batch3/oracle_audit_before_reference.json)。旧失败与冻结文件保留，不覆盖。第三批独立评价同样未读取参考补丁或隐藏 verifier。

## 由证据得到的限制与后续改动

七例静态生成均有候选，但首版局部状态操作组合为零，候选主要是表达式包装和整体字符串模式迁移。对期望进行小表达式补全不能弥补组合空间缺失。固定实际值观察也存在信息丢失：例如 count 观察不能辨别相同长度的不同顺序；这已由独立 toy 验证，不能据此声称 pilot 效果。

第二批模型的两轮输出均只选择最前面的至多八项，并全部使用原期望 `pre[0]`。独立的三条无项目代码的算术/指令诊断全部答对，共报告 692 tokens，说明接口有基本指令执行能力；不能把这解释为已证明其复杂组合推理可靠。第三批使用更明确的语义推导提示并开启 medium thinking，仍每轮一次请求、10,000 输出 tokens，但全部未得到有效最终答案。提示、候选空间与观察扩展同时变化，该批也没有语义执行结果，不能据此归因某项方法改动的收益或损失。

P1/r1 冻结失败源于 Python 集合 repr 在不同 hash seed 下顺序变化。修复使用递归确定性字面量并拒绝无序集合到有序值的不确定转换；映射采用有序键值对编码，避免 canonical JSON 排序破坏原字典顺序。旧批次保留失败，新实现另行冻结。冻结产物执行也改为检验旧文件哈希，不使用新提示或新生成器重新解释旧回复。

后续开发围绕一个组合单位：**动作切片 + 源观察切片 + 期望变换**。程序扩展控制块内的直线区域、有限参数行的字符串表达式、带唯一局部锚点的字符串变换、同一调用参数位置的源表达式交换，以及按类型根迁移观察。没有新增 case/API 专用规则；这些扩展的实现代理仅使用独立 toy。根代理已了解旧结果，整个开发过程仍不属于盲态。
