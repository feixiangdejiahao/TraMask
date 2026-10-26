> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/semantic_transport_results.md) · [旧路径映射](../../../results/path_map.tsv)

# 观察变换器实验进度

2026-09-24。五小时时限于 08:25:54 UTC 结束。七例两轮都检出且没有错误/未知报警的目标未达到，停止新增实验并保留实现与证据。七例为已见开发集。

## 已完成批次

| 批次 | 冻结代码 | 模型请求 | r1 / r2 目标检出 | 已确认错误报警 | 未知报警 | 主要限制 |
|---|---|---:|---|---:|---:|---|
| batch1 | c0d49a2 | 14 | 0/7；0/7 | 3；3 | 0；0 | 12 次 HTTP 400；仅 P4 两轮有产物并执行 |
| batch2 | f0b75b2 | 14 | 0/7；0/7 | 15；16 | 2；2 | P1/r1 冻结失败；两轮各两个候选运行单元编译阻断 |
| batch3 | 1843b0a | 14 | 0/7；0/7（全部协议阻断） | — | — | 14 次 HTTP 200 均无有效最终答案；0 冻结候选、0 候选执行 |
| batch4 | d0c6d93 | 14 | 0/7；0/7 | 17；17 | 4；4 | 两轮各两个候选运行单元编译阻断；另保留 8 次模型发送前调度失败 |
| batch5 | 5888ca8 | 14 | 0/7；0/7 | 17；17 | 4；4 | 两轮各两个候选运行单元受生成 Go 代码编译阻断 |
| batch6 | ab1552b | 14 | 0/7；0/7 | 17；17 | 5；5 | 两轮各两个候选运行单元仍受生成 Go 调用类型错误阻断 |
| batch7 | 1e5dc83 | 14 | 0/7；0/7（已确认命中） | 0；0 | 2；0（事后审阅） | 3 次补全协议失败；P6/r2 编译阻断；P1/r1 两项事前 valid 报警的适用性仍未决 |

第七批 `1e5dc83` 已完成生成与候选执行，尚未确认七例两轮成功。其事前协议保留第六批候选、语义消息和源码输入，将补全配置改为 enabled thinking / low reasoning、32,000 输出 tokens，两轮各一次请求，不重试。七例 pending 文件字节和语义消息完全相同，请求只改变上述三项补全设置；input.json 另增加 completion_profile 元数据，因此不能称所有包装文件逐字相同。[输入身份核对](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_07/input_identity_vs_batch6_v1.json)。第六批 `ab1552b` 增加的是通用父测试准入与断言排序、源值向量期望模板及 Go 前缀局部变量用途处理，仍使用 disabled thinking / 10,000 输出 tokens。

第二批只有请求提示增加 JSON 字样，源输入与算法策略不据第一批执行反馈改变。该修改解决 provider 对 JSON 输出模式的提示要求。首批 12 次失败用量未知，另外两次共报告 29,692 tokens；第二批报告 171,196 tokens。模型请求名是 `deepseek-v4-flash`，响应名为 `deepseek-flash`，不能仅根据别名证明 provider 的内部路由。

第三批的 14 个生成单元全部终结为完成协议失败。13 次响应为 `finish_reason=length`，各报告 10,000 reasoning tokens，最终 content 为空；P7/r2 为 `stop`，最终 content 仅有 106 个 ASCII 空格，报告 5,754 completion tokens，其中 5,647 为 reasoning tokens。独立核对响应与缓存 manifest 的用量一致：prompt 192,874、completion 135,754，共 **328,628 tokens**，其中 reasoning 135,647。14 次冻结也均失败，日志显示缺失轮次 `prepare.json`；这是无有效补全、未物化候选之后的阻断，不是有效补全后的缓存比较错误。三个批次已知用量合计 529,516 tokens，另有首批 12 次失败用量未知；这些是 provider 报告的 token 数，不是货币成本。

第三批两轮各 7 个协议失败单元均保留在固定分母中，空 oracle 清单已独立封存。没有冻结测试义务，也没有候选或参考执行；表中报警项的破折号表示无可评价执行，不能解释为无误报、无漏报或组合空间完整。该批不是有意义的语义负结果。

第四批仅将第三批请求改回 disabled thinking / none reasoning effort；七例 pending 文件逐字一致，请求模板其余字段一致。14 次模型请求均有效，104 项全部冻结，两轮各 52 项；独立执行前封存标签为 36 valid、18 invalid、40 inapplicable、10 unknown。候选执行后，74 项实际执行、30 项受 Go 编译阻断；36 个有效 oracle 中 30 项通过、6 项受阻断，**没有有效 oracle 的受控失败**，因此没有待目标匹配或第二审阅的报警，也无需参考执行。两轮合计 34 个错误/不适用报警、8 个未知报警；另两项未知通过仍为未知，且它们的一项来源控制为 skip。来源控制阻断共 32 项，与 30 项编译阻断重叠，不能相加。编译日志分别显示生成函数残留未使用局部变量、嵌套多返回值调用将 error 当成 Object 实参，均是生成代码问题。

第四批还发生一次外层调度错误：部分 prepare 未完成时提前启动 complete，P4 至 P7 两轮的 8 个 CLI 在读取缺失的 `transport_prepare.json` 时退出，位置早于创建轮次目录和模型发送。全部 prepare 完成后，只对这 8 个从未发送的单元发起首次请求，另外 6 份响应保留。原始失败日志、恢复计划及两份 complete 账本均保留；22 次 CLI 调用对应 14 次模型调用，每单元一次，不将这 8 次失败隐藏或计作模型重试。第四批独立核对用量 **195,646 tokens**，四个批次已知合计 725,162 tokens，仍不含首批 12 次失败的未知用量及批次外诊断。

第五批 14 次模型请求全部有效，104 项义务冻结，两轮各 52 项。独立评价在任何第五批候选执行之前，于 **07:38:02.191113 UTC** 封存 37 valid、21 invalid、34 inapplicable、12 unknown；全部生成身份在执行后仍匹配封存。104 项完整测试定义及 108 项来源控制均通过源码重构检查；94 项编辑与第四批同轮产物相同，10 项义务具有新测试体。候选运行后，72 项实际执行、32 项因生成 Go 代码编译失败而阻断；37 个有效 oracle 中 28 项通过、9 项未执行，**没有有效 oracle 的受控候选失败**。因此两轮各自的已确认目标命中为 0/7；这不证明所有目标均可被本批有效执行所覆盖。没有需要目标匹配复核的有效报警，未读取参考补丁或隐藏 verifier，未执行参考。

第五批两轮合计 34 项已确认错误报警、8 项未知报警；另两项未知义务通过但各有一个来源控制 skip，标签仍保留 unknown。来源控制阻断共 34 项，与 32 项编译阻断重叠，不能相加。编译诊断包括生成变量未使用、嵌套调用的 error 返回值不满足 Object 参数类型，以及嵌套 helper 的 int64 返回值不满足 Object 参数类型，均属生成代码问题。调度器要求全部前置阶段成功后才进入下一阶段，本批 prepare 7、complete 14、freeze 14 均成功；账本保留耗时但缺少独立绝对开始时间，不能仅由 mtime 证明完整时序。

第五批响应体与缓存用量核对一致：prompt 197,980、completion 3,180，共 **201,160 tokens**。截至第五批，已知用量累计 **926,322 tokens**，仍不含首批 12 次失败的未知用量、批次外诊断和后续批次；不将 token 数称为货币成本。模型协议审计 v1 的 case_id 路径段错误由 v2 更正，调用数、哈希和用量均未变，v1 保留。

第五批补全形式的事后诊断也经独立复核：104 项接受表达式全部是可静态还原的常量字面量，没有使用 `pre` 或 `arg`，其中 99 项的值与相应源期望槽相同；投影观察按其声明的源槽核对，不能一律取 `pre[0]`。没有实际检查的适用源见证。8 项已提交表达式因未知名字被拒绝：`tmp_path` 两项、`false` 四项、`true` 两项；另 180 项只是未提供补全的已展示候选，不能混算为非法提交。常量本来允许，源值相同也不证明 oracle 适用；这些统计不构成方法有效性证明或失败因果归因。[原始诊断](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/completion_expression_audit_v1.json)、[独立复核](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/completion_expression_independent_review_v1.json)。

第六批 14 次模型请求全部有效，106 项义务冻结，两轮各 53 项；完整定义及 110 项来源控制均通过独立源码重构核对。评价于 **07:59:02.807915 UTC**、任何本批候选执行之前，封存 40 valid、22 invalid、32 inapplicable、12 unknown。新的未受契约覆盖输入仍为 unknown；未因希望获得检出而强行标为有效。P7 五个不同测试体另经第二审阅者核对，其无效判定一致。评价者此前已读旧批次结果与事后目标假设材料，不能称为盲态评价；未读取参考补丁或隐藏 verifier。

第六批 74 项义务实际执行、32 项受 Go 编译阻断；40 个有效 oracle 中 30 项通过、10 项未执行，**没有有效 oracle 的受控候选失败**，两轮各自的已确认目标命中为 0/7。两轮合计 34 项错误报警、10 项未知报警；另外两项 unknown 受编译阻断，未据结果修改标签。本批来源控制阻断共 32 项，与编译阻断重叠，没有额外的 skip 依赖义务。四个运行错误单元分别保留多返回值嵌入单值位置、int64 不满足 Object、error 不满足 Object 的生成调用类型错误；新增 blank use 消除了这批日志中的未使用局部变量错误，但并未使这些嵌套调用合法。没有待目标匹配的有效报警，因而未执行参考。

第六批响应体与缓存用量逐项一致：prompt 221,198、completion 3,220，共 **224,418 tokens**。六个已完成批次的已知用量累计 **1,150,740 tokens**，不含首批 12 次失败的未知用量、批次外诊断及当时尚未完成的第七批。


第七批 14 次模型调用中 11 次有效、3 次终结为补全协议失败，均未重试：P1/r2 和 P7/r1 为 length 且最终 content 为空；P7/r2 为 stop，但最终 content 只有 119 个 ASCII 空格。11 个冻结单元共有 70 项义务，两轮各 35 项；70 项完整定义与 67 项来源控制均通过源码重构核对。评价于 **08:18:46.935182 UTC**、任何候选执行之前，封存 67 valid、2 inapplicable、1 unknown。后者保守保留绑定 repeat 事件是否进入应用 on_key 的派发契约疑问。生成身份执行后仍与封存一致；评价不是盲态。

第七批 66 项实际执行、4 项因 P6/r2 的生成 Go 嵌套调用把 error 作为 Object 而编译阻断。67 项事前 valid 中，63 项通过、2 项受阻、**2 项为受控失败且尚未确认缺陷**；1 项 unknown 通过仍保持 unknown。两项未决报警都在 P1/r1，分别观察 ESC+Enter 后追加字面串时的首键和完整键序列，来源控制通过；它们没有已知 P1 目标要求的非默认 phase 观察，因此不计目标命中。第一项实际 events 为空而 IndexError，第二项回退为 circumflex_accent、enter 等键。源码 legacy 对照显式调用 feed("") flush，而这两项组合测试没有 flush；独立第二审阅已将两项的适用性判断保留为 unknown：源码只保证 EOF/timeout 后的 legacy 处理，而新 ESC 边界按未知序列重发。第一次审阅把流式处理的时间边界条件外推过度；保留这一审阅分歧，事前 valid 标签与原始结果不回写。最终没有确认缺陷，这两项按未决/unknown 处理。本表按事后审阅列出两项未知报警；原始封存汇总中的 0 错误/未知报警不包括它们，不能据此宣称可靠性或无漏报。三项协议失败也保留在固定 14 单元分母中。

第七批响应体与缓存用量一致：prompt **221,548**、completion **243,359**，共 **464,907 tokens**，其中 reasoning 241,406。七批已知用量累计 **1,615,647 tokens**，另有三条批次外诊断 692 tokens；首批 12 次失败用量仍未知。这些是 provider 报告 token 数，不是货币成本。本批尚无已确认目标命中，未读取参考补丁或隐藏 verifier，也未执行参考。

第二批 106 项物化，98 项完成冻结；其中 72 项实际执行、26 项受编译阻断。全部冻结项均在本批候选执行前完成独立 oracle 标签封存：33 valid、9 invalid、50 inapplicable、6 unknown。33 个有效 oracle 均通过，没有需要目标匹配复核的有效报警。运行叶子、静态测试义务和任务数分别计数，来源控制阻断等诊断可能与编译阻断重叠，不能直接求和。

第一批 P4 两轮先封存 oracle，再运行候选；第二批同样先封存再执行。以上两批均未读取参考补丁、运行参考或读取隐藏 verifier。没有真实缺陷证据时，不以参考通过来证明 oracle。

第四批同样在全部候选执行前封存 104 项 oracle；完整的 106 个来源控制副本也与源测试核对。封存后保留所有运行结果，没有依据结果重新挑选候选或修改 oracle。第四批未读取参考补丁或隐藏 verifier，也未运行参考。

本地完整证据：[batch1 评价](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_01/candidate_evaluation_v1.json)、[batch2 评价](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_02/candidate_evaluation_v1.json)、[第二批事前封存](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_02/oracle_audit_before_reference.json)、[batch3 评价](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_03/candidate_evaluation_v1.json)、[第三批协议与用量审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_03/completion_protocol_audit_v1.json)、[第三批空项封存](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_03/oracle_audit_before_reference.json)。旧失败与冻结文件保留，不覆盖。第三批独立评价同样未读取参考补丁或隐藏 verifier。

第四批证据：[候选评价](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_04/candidate_evaluation_v1.json)、[事前 oracle 封存](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_04/oracle_audit_before_reference.json)、[执行及编译审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_04/candidate_execution_audit_v1.json)、[调度恢复及请求审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_04/orchestration_audit_v1.json)、[来源控制核对](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_04/source_control_audit_v2.json)。来源控制审计 v1 的两个 Go raw-string 扫描假差异在 v2 中修正；v1 仍保留。

第五批证据：[独立评价报告](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/evaluation_report.md)、[候选评价](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/candidate_evaluation_v1.json)、[事前 oracle 封存](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/oracle_audit_before_reference.json)、[封存回执](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/oracle_seal_receipt.json)、[执行及编译审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/candidate_execution_audit_v1.json)、[来源控制核对](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/source_control_audit_v1.json)、[模型协议与用量审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/completion_protocol_audit_v2.json)。旧产物不覆盖，执行后不重选测试或修改 oracle。

第六批证据：[候选评价](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_06/candidate_evaluation_v1.json)、[事前 oracle 封存](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_06/oracle_audit_before_reference.json)、[封存回执](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_06/oracle_seal_receipt.json)、[执行及编译审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_06/candidate_execution_audit_v1.json)、[来源控制核对](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_06/source_control_audit_v1.json)、[P7 第二审阅](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_06/p7_second_reader_oracle_review.json)、[模型协议与用量审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_06/completion_protocol_audit_v1.json)。本批执行后生成身份仍与事前封存一致。


第七批证据：[候选评价](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_07/candidate_evaluation_v1.json)、[事前 oracle 封存](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_07/oracle_audit_before_reference.json)、[封存回执](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_07/oracle_seal_receipt.json)、[执行及编译审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_07/candidate_execution_audit_v1.json)、[来源控制核对](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_07/source_control_audit_v1.json)、[模型协议与用量审计](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_07/completion_protocol_audit_v1.json)。两个未决报警不能省略；[独立第二审阅](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_07/postexecution_p1_second_review_v1.json)明确保留 unknown 适用性，与事前封存分开记录。

## 由证据得到的限制与后续改动

七例静态生成均有候选，但首版局部状态操作组合为零，候选主要是表达式包装和整体字符串模式迁移。对期望进行小表达式补全不能弥补组合空间缺失。固定实际值观察也存在信息丢失：例如 count 观察不能辨别相同长度的不同顺序；这已由独立 toy 验证，不能据此声称 pilot 效果。

第二批模型的两轮输出均只选择最前面的至多八项，并全部使用原期望 `pre[0]`。独立的三条无项目代码的算术/指令诊断全部答对，共报告 692 tokens，说明接口有基本指令执行能力；不能把这解释为已证明其复杂组合推理可靠。第三批使用更明确的语义推导提示并开启 medium thinking，仍每轮一次请求、10,000 输出 tokens，但全部未得到有效最终答案。提示、候选空间与观察扩展同时变化，该批也没有语义执行结果，不能据此归因某项方法改动的收益或损失。

P1/r1 冻结失败源于 Python 集合 repr 在不同 hash seed 下顺序变化。修复使用递归确定性字面量并拒绝无序集合到有序值的不确定转换；映射采用有序键值对编码，避免 canonical JSON 排序破坏原字典顺序。旧批次保留失败，新实现另行冻结。冻结产物执行也改为检验旧文件哈希，不使用新提示或新生成器重新解释旧回复。

后续开发围绕一个组合单位：**动作切片 + 源观察切片 + 期望变换**。程序扩展控制块内的直线区域、有限参数行的字符串表达式、带唯一局部锚点的字符串变换、同一调用参数位置的源表达式交换，以及按类型根迁移观察。没有新增 case/API 专用规则；这些扩展的实现代理仅使用独立 toy。根代理已了解旧结果，整个开发过程仍不属于盲态。

## 候选阶段的事后定位

第五批在执行与 oracle 封存完成后，另由评价代理逐例对照既有目标描述检查 pending、shown 与 emitted 三层。完整判别目标没有在保留的候选池中被找到；P3 有部分联合 setup，但观察位置不满足目标，因此 coarse pending 标为 uncertain，不能简单归为纯排序损失。P5/P6 的 16/10 个 pending 候选已全部展示，编译失败是额外问题，修复编译本身不会补出这些池中缺失的关系。

这是对已经受预算裁剪的候选池的事后审阅，尚不能区分生成语法不支持、入口遗漏和更早的裁剪，也不是不可表达性证明。审阅代理在完成算法开发后明确切换为评价角色并读取目标描述；结论未送给生成模型或用于本轮 case 专用规则。完整逐例证据与阅读文件哈希见 [定位报告](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_05/failure_localization/report.md)。

第六批的[增量定位报告](../../../results/test_semantic_transfer/test_action_and_oracle_transfer/batch_06/failure_localization/report.md)同样没有建立完整目标判别测试的证据，但不能简单说所有部分特征都缺失：P7 新增了 44 项结构化期望模板候选，包含非恒等字段变换的部分 setup；一些缺少递归标记，另一些缺少解析包装或必要输入。P3/P7 的粗粒度关系保留 uncertain。P5/P6 的测试体增量仅为空白赋值，修复了局部切片表示但没有增加目标闭包/跨调用关系。该定位不进入第七批模型消息；第七批消息与第六批逐字一致。
