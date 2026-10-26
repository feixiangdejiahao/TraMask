# 同一源码声明的第三种证据呈现

这是提示词呈现消融，不是新的候选生成、检索或排序算法。问题是：已经检索到相同源码时，额外的程序分析文字究竟帮助推理，还是增加阅读负担？

固定使用 `context_ablation` 每个 case 的第一个候选，即按 `SHA256(candidate.id)` 排序后的首条单例请求，共 17 条。16 条已经与原 paired ablation 的首条材料直接核对；P7 原 pair 尚未写完时，先核对原 `offered_ids` 和全部已准备请求的集合完全一致，再用相同 SHA 规则确定首条。选择过程只读取请求、输入 wire 和 pair 路径元信息，不读取回答、validation 或评价真值。

第三臂保留原 system、完整 issue、原始/修改后测试、断言、输入编辑、imports、候选身份、模型设置以及本地完整 `analysis_evidence`。只替换 prompt 中的 `dependency_evidence.rendered`，并更新真实派生的 `rendered_bytes` 和基于原限额计算的 `status`。

新呈现只包含同一 `analysis_evidence.declarations` 中的完整源码。按原 renderer 的 `(path, start_byte, -end_byte)` 顺序输出；角色顺序与独立 SOURCE header 也与原 renderer 一致。仅当源文件 SHA 和路径一致、源码区间包含且嵌套字节完全相同时，才能用完整外层声明覆盖内层声明；内层来源及 roles 保留。不同源码版本、部分重叠的声明不合并，也没有代码截断。

去掉的内容包括输入/调用图描述、actual/formal 绑定文字、观察映射、原/新依赖图节点和边、函数值/对照关联说明以及 unknown 说明，不能把该消融描述成“只删图边”。原始结构化分析仍完整保存在本地请求中，但不会重复放入模型消息。

## 本地完整性检查

17 条请求涉及的 **114 个声明**全部按照完整原源码或候选编辑后的源码 SHA、UTF-8 字节区间核对成功。最终 v2 中，**每条新 rendered 都是对应旧 rendered 中连续完整 SOURCE 区段的逐字相同子串**。因此本次真实样本没有改变源码文字、顺序、角色或 SOURCE 排版，变化仅是去掉其前后的分析文字并更新派生元数据。

新增 8 项测试覆盖 UTF-8、重复/包含声明角色保存、不同源码版本与部分重叠、矛盾或截断拒绝、长声明不截断、原 renderer 顺序/header 一致、真实派生字节数与 status、完整输入 wire 不变、没有回答也能准备请求，以及不完整请求集合不能提前抽样。

| Case | 原 prompt 字节 | v2 prompt 字节 | 完整声明数 |
|---|---:|---:|---:|
| N01 | 31,711 | 23,170 | 15 |
| N02 | 22,461 | 15,086 | 12 |
| N03 | 8,740 | 6,527 | 3 |
| N04 | 32,152 | 24,593 | 14 |
| N05 | 13,080 | 8,563 | 8 |
| N06 | 10,200 | 7,223 | 2 |
| N07 | 19,765 | 12,291 | 7 |
| N08 | 30,344 | 18,232 | 13 |
| N09 | 26,962 | 18,659 | 1 |
| N10 | 9,067 | 5,345 | 4 |
| P1 | 14,901 | 10,314 | 2 |
| P2 | 10,708 | 6,238 | 4 |
| P3 | 10,540 | 5,184 | 2 |
| P4 | 42,062 | 28,887 | 4 |
| P5 | 21,064 | 11,482 | 10 |
| P6 | 20,549 | 10,967 | 10 |
| P7 | 14,560 | 10,668 | 3 |

总 prompt 从 **338,866 字节降至 223,429 字节，减少 34.07%**。这不是模型准确性或 token 用量结论；需要 root 核验后实际派发，并与同一候选的原图文字臂、删除全部 dependency evidence 的对照臂比较。模型回答后仍须区分输出格式通过与语义正确。

实现为 `experimental/source_declarations_context.py`；准备工具为 `scripts/prepare_source_declarations_ablation.py`，不会调用 provider。待发 17 条请求、原 wire 参数的逐字段相同预览、声明核验、逐例字节统计、固定协议和 driver 参数位于 `results/relation_search_20260929_v3/source_declarations_ablation_v2/ready.json` 及同目录各 case 文件。连续源码区段证明位于 `source_sequence_verification.json`。此前 v1 产物保留，待发版本只使用 v2。
