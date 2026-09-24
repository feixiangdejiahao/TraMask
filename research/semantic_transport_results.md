# 观察变换器实验进度

2026-09-24。目标仍为七例两轮都检出且没有错误/未知报警；截止 08:25:54 UTC。目前未达到。七例为已见开发集。

## 已完成批次

| 批次 | 冻结代码 | 模型请求 | r1 / r2 目标检出 | 已确认错误报警 | 未知报警 | 主要限制 |
|---|---|---:|---|---:|---:|---|
| batch1 | c0d49a2 | 14 | 0/7；0/7 | 3；3 | 0；0 | 12 次 HTTP 400；仅 P4 两轮有产物并执行 |
| batch2 | f0b75b2 | 14 | 0/7；0/7 | 15；16 | 2；2 | P1/r1 冻结失败；两轮各两个候选运行单元编译阻断 |
| batch3 | 1843b0a | 14 | 0/7；0/7（全部协议阻断） | — | — | 14 次 HTTP 200 均无有效最终答案；0 冻结候选、0 候选执行 |
| batch4 | d0c6d93 | 14 | 0/7；0/7 | 17；17 | 4；4 | 两轮各两个候选运行单元编译阻断；另保留 8 次模型发送前调度失败 |
| batch5 | 5888ca8 | 14 | 0/7；0/7 | 17；17 | 4；4 | 两轮各两个候选运行单元受生成 Go 代码编译阻断 |

第六批 `ab1552b` 正在准备，尚无完成后的独立评价；不将进行中的批次计入上表。该批保留相同七例源码输入、两轮各一次模型请求及 disabled thinking / 10,000 输出 tokens 配置，另行冻结通用父测试准入与断言排序、源值向量期望模板及 Go 前缀局部变量用途处理。

第二批只有请求提示增加 JSON 字样，源输入与算法策略不据第一批执行反馈改变。该修改解决 provider 对 JSON 输出模式的提示要求。首批 12 次失败用量未知，另外两次共报告 29,692 tokens；第二批报告 171,196 tokens。模型请求名是 `deepseek-v4-flash`，响应名为 `deepseek-flash`，不能仅根据别名证明 provider 的内部路由。

第三批的 14 个生成单元全部终结为完成协议失败。13 次响应为 `finish_reason=length`，各报告 10,000 reasoning tokens，最终 content 为空；P7/r2 为 `stop`，最终 content 仅有 106 个 ASCII 空格，报告 5,754 completion tokens，其中 5,647 为 reasoning tokens。独立核对响应与缓存 manifest 的用量一致：prompt 192,874、completion 135,754，共 **328,628 tokens**，其中 reasoning 135,647。14 次冻结也均失败，日志显示缺失轮次 `prepare.json`；这是无有效补全、未物化候选之后的阻断，不是有效补全后的缓存比较错误。三个批次已知用量合计 529,516 tokens，另有首批 12 次失败用量未知；这些是 provider 报告的 token 数，不是货币成本。

第三批两轮各 7 个协议失败单元均保留在固定分母中，空 oracle 清单已独立封存。没有冻结测试义务，也没有候选或参考执行；表中报警项的破折号表示无可评价执行，不能解释为无误报、无漏报或组合空间完整。该批不是有意义的语义负结果。

第四批仅将第三批请求改回 disabled thinking / none reasoning effort；七例 pending 文件逐字一致，请求模板其余字段一致。14 次模型请求均有效，104 项全部冻结，两轮各 52 项；独立执行前封存标签为 36 valid、18 invalid、40 inapplicable、10 unknown。候选执行后，74 项实际执行、30 项受 Go 编译阻断；36 个有效 oracle 中 30 项通过、6 项受阻断，**没有有效 oracle 的受控失败**，因此没有待目标匹配或第二审阅的报警，也无需参考执行。两轮合计 34 个错误/不适用报警、8 个未知报警；另两项未知通过仍为未知，且它们的一项来源控制为 skip。来源控制阻断共 32 项，与 30 项编译阻断重叠，不能相加。编译日志分别显示生成函数残留未使用局部变量、嵌套多返回值调用将 error 当成 Object 实参，均是生成代码问题。

第四批还发生一次外层调度错误：部分 prepare 未完成时提前启动 complete，P4 至 P7 两轮的 8 个 CLI 在读取缺失的 `transport_prepare.json` 时退出，位置早于创建轮次目录和模型发送。全部 prepare 完成后，只对这 8 个从未发送的单元发起首次请求，另外 6 份响应保留。原始失败日志、恢复计划及两份 complete 账本均保留；22 次 CLI 调用对应 14 次模型调用，每单元一次，不将这 8 次失败隐藏或计作模型重试。第四批独立核对用量 **195,646 tokens**，四个批次已知合计 725,162 tokens，仍不含首批 12 次失败的未知用量及批次外诊断。

第五批 14 次模型请求全部有效，104 项义务冻结，两轮各 52 项。独立评价在任何第五批候选执行之前，于 **07:38:02.191113 UTC** 封存 37 valid、21 invalid、34 inapplicable、12 unknown；全部生成身份在执行后仍匹配封存。104 项完整测试定义及 108 项来源控制均通过源码重构检查；94 项编辑与第四批同轮产物相同，10 项义务具有新测试体。候选运行后，72 项实际执行、32 项因生成 Go 代码编译失败而阻断；37 个有效 oracle 中 28 项通过、9 项未执行，**没有有效 oracle 的受控候选失败**。因此两轮各自的已确认目标命中为 0/7；这不证明所有目标均可被本批有效执行所覆盖。没有需要目标匹配复核的有效报警，未读取参考补丁或隐藏 verifier，未执行参考。

第五批两轮合计 34 项已确认错误报警、8 项未知报警；另两项未知义务通过但各有一个来源控制 skip，标签仍保留 unknown。来源控制阻断共 34 项，与 32 项编译阻断重叠，不能相加。编译诊断包括生成变量未使用、嵌套调用的 error 返回值不满足 Object 参数类型，以及嵌套 helper 的 int64 返回值不满足 Object 参数类型，均属生成代码问题。调度器要求全部前置阶段成功后才进入下一阶段，本批 prepare 7、complete 14、freeze 14 均成功；账本保留耗时但缺少独立绝对开始时间，不能仅由 mtime 证明完整时序。

第五批响应体与缓存用量核对一致：prompt 197,980、completion 3,180，共 **201,160 tokens**。五个已完成批次的已知用量累计 **926,322 tokens**，仍不含首批 12 次失败的未知用量、批次外诊断和进行中的第六批；不将 token 数称为货币成本。模型协议审计 v1 的 case_id 路径段错误由 v2 更正，调用数、哈希和用量均未变，v1 保留。

第五批补全形式的事后诊断也经独立复核：104 项接受表达式全部是可静态还原的常量字面量，没有使用 `pre` 或 `arg`，其中 99 项的值与相应源期望槽相同；投影观察按其声明的源槽核对，不能一律取 `pre[0]`。没有实际检查的适用源见证。8 项已提交表达式因未知名字被拒绝：`tmp_path` 两项、`false` 四项、`true` 两项；另 180 项只是未提供补全的已展示候选，不能混算为非法提交。常量本来允许，源值相同也不证明 oracle 适用；这些统计不构成方法有效性证明或失败因果归因。[原始诊断](../results/semantic_transport/batch5/completion_expression_audit_v1.json)、[独立复核](../results/semantic_transport/batch5/completion_expression_independent_review_v1.json)。

第二批 106 项物化，98 项完成冻结；其中 72 项实际执行、26 项受编译阻断。全部冻结项均在本批候选执行前完成独立 oracle 标签封存：33 valid、9 invalid、50 inapplicable、6 unknown。33 个有效 oracle 均通过，没有需要目标匹配复核的有效报警。运行叶子、静态测试义务和任务数分别计数，来源控制阻断等诊断可能与编译阻断重叠，不能直接求和。

第一批 P4 两轮先封存 oracle，再运行候选；第二批同样先封存再执行。以上两批均未读取参考补丁、运行参考或读取隐藏 verifier。没有真实缺陷证据时，不以参考通过来证明 oracle。

第四批同样在全部候选执行前封存 104 项 oracle；完整的 106 个来源控制副本也与源测试核对。封存后保留所有运行结果，没有依据结果重新挑选候选或修改 oracle。第四批未读取参考补丁或隐藏 verifier，也未运行参考。

本地完整证据：[batch1 评价](../results/semantic_transport/batch1/candidate_evaluation_v1.json)、[batch2 评价](../results/semantic_transport/batch2/candidate_evaluation_v1.json)、[第二批事前封存](../results/semantic_transport/batch2/oracle_audit_before_reference.json)、[batch3 评价](../results/semantic_transport/batch3/candidate_evaluation_v1.json)、[第三批协议与用量审计](../results/semantic_transport/batch3/completion_protocol_audit_v1.json)、[第三批空项封存](../results/semantic_transport/batch3/oracle_audit_before_reference.json)。旧失败与冻结文件保留，不覆盖。第三批独立评价同样未读取参考补丁或隐藏 verifier。

第四批证据：[候选评价](../results/semantic_transport/batch4/candidate_evaluation_v1.json)、[事前 oracle 封存](../results/semantic_transport/batch4/oracle_audit_before_reference.json)、[执行及编译审计](../results/semantic_transport/batch4/candidate_execution_audit_v1.json)、[调度恢复及请求审计](../results/semantic_transport/batch4/orchestration_audit_v1.json)、[来源控制核对](../results/semantic_transport/batch4/source_control_audit_v2.json)。来源控制审计 v1 的两个 Go raw-string 扫描假差异在 v2 中修正；v1 仍保留。

第五批证据：[独立评价报告](../results/semantic_transport/batch5/evaluation_report.md)、[候选评价](../results/semantic_transport/batch5/candidate_evaluation_v1.json)、[事前 oracle 封存](../results/semantic_transport/batch5/oracle_audit_before_reference.json)、[封存回执](../results/semantic_transport/batch5/oracle_seal_receipt.json)、[执行及编译审计](../results/semantic_transport/batch5/candidate_execution_audit_v1.json)、[来源控制核对](../results/semantic_transport/batch5/source_control_audit_v1.json)、[模型协议与用量审计](../results/semantic_transport/batch5/completion_protocol_audit_v2.json)。旧产物不覆盖，执行后不重选测试或修改 oracle。

## 由证据得到的限制与后续改动

七例静态生成均有候选，但首版局部状态操作组合为零，候选主要是表达式包装和整体字符串模式迁移。对期望进行小表达式补全不能弥补组合空间缺失。固定实际值观察也存在信息丢失：例如 count 观察不能辨别相同长度的不同顺序；这已由独立 toy 验证，不能据此声称 pilot 效果。

第二批模型的两轮输出均只选择最前面的至多八项，并全部使用原期望 `pre[0]`。独立的三条无项目代码的算术/指令诊断全部答对，共报告 692 tokens，说明接口有基本指令执行能力；不能把这解释为已证明其复杂组合推理可靠。第三批使用更明确的语义推导提示并开启 medium thinking，仍每轮一次请求、10,000 输出 tokens，但全部未得到有效最终答案。提示、候选空间与观察扩展同时变化，该批也没有语义执行结果，不能据此归因某项方法改动的收益或损失。

P1/r1 冻结失败源于 Python 集合 repr 在不同 hash seed 下顺序变化。修复使用递归确定性字面量并拒绝无序集合到有序值的不确定转换；映射采用有序键值对编码，避免 canonical JSON 排序破坏原字典顺序。旧批次保留失败，新实现另行冻结。冻结产物执行也改为检验旧文件哈希，不使用新提示或新生成器重新解释旧回复。

后续开发围绕一个组合单位：**动作切片 + 源观察切片 + 期望变换**。程序扩展控制块内的直线区域、有限参数行的字符串表达式、带唯一局部锚点的字符串变换、同一调用参数位置的源表达式交换，以及按类型根迁移观察。没有新增 case/API 专用规则；这些扩展的实现代理仅使用独立 toy。根代理已了解旧结果，整个开发过程仍不属于盲态。
