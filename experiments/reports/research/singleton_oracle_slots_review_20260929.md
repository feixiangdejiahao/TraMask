> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/singleton_oracle_slots_review_20260929.md) · [旧路径映射](../../../results/path_map.tsv)

# 单候选 expected-slot 接口与语义编辑运输独立审查

本轮本地审查发现并复现两个实现错误：只读断言在响应阶段重新变为 editable，以及已插桩候选的新语义修改在再次插桩时丢失。两项均已由各模块负责人修复，审查者使用修复前快照和修复后源码分别重放确认。审查没有修改冻结的 v3 实验、运行中的 campaign、provider 或 oracle 接口，也没有调用模型或 Docker。

此外，Python 比较运算符 family 限制存在真实表达能力缺口；上下文收集也不是完整调用闭包。这些应作为方法覆盖范围报告，不能把接口无法表达的正确 oracle 计成模型判断错误。

## 1. 已修复的实现错误

| 问题 | 通用复现 | 修复前 | 修复后 |
| --- | --- | --- | --- |
| 输入与断言重叠时资格不一致 | `assert compute(1) == 1` 为 A0；`assert other == 2` 为 A1。候选把 `compute` 参数 1 改为 2，只要求模型判断 A1 | 构造请求只提供 A1；响应阶段重新提取 A0，导致合法 A1 preserve 返回 `slot_record_changed` | 两阶段共享 `input_overlap`，A0 保持只读，A1 preserve/adapt 可以正常接受 |
| 已插桩候选丢失后追加语义编辑 | 两输入由 1、2 改成 3、5；先插桩，再接受 `assert result == 8`，然后重新插桩和物化 | accepted semantic edit 为 1，重新插桩后为 0；generated assertion 恢复为 `== 3` | accepted 与重新插桩均为 1；generated assertion 为 `== 8` |

第二项是 `instrument → semantic → instrument` 的 API 阶段顺序问题。`0d0bcac` 已解决普通 `semantic → instrument` 流程的 composed-candidate 旧快照问题，但其 instrumented 分支仍只取 `program_edits`。`validate` 与 cache replay 可以在保留 instrumentation 标记时向 `edits` 追加 `semantic_expected`，所以该分支会丢失新修改。

集中修复比要求两个 producer 同步维护第二份规范状态更简单：已插桩候选从 `program_edits` 恢复未加 probe 的语句，再合并 `edits` 中新追加、未带 `instrumented_prefix` 的 `semantic_expected`；以源码 path/start/end、before、after 去重。已有 probe 前缀语句仍从规范快照恢复，避免重复插入 logger。相同范围但不同替换文本不会静默覆盖，由现有 overlap 检查拒绝。审查未发现这项合并引入新的规范来源歧义。

初始简易复现检查整个 emitted file，修复后仍显示 `stale_expectation_present=true`，原因是 **source control 应当保留 `== 3`**。最终重放按 obligation 的实际函数名分别检查：generated 为 `== 8`，source control 为 `== 3`。不能用文件中旧断言是否出现来判断语义编辑是否丢失。

slot 重叠修复不改写已冻结 paired 结果。负责人封存的 [postfreeze audit](../../../results/program_relation_search/program_relation_search_20260929/singleton_expected_slots_postfreeze_fix_v1/audit.json) 记录原 32 条 baseline offered 均无 input overlap，14 条新版有效响应在新旧 adapter 下结果一致；这是材料范围核查，不是正确率评价。

## 2. 原 actual、setup 与失败处理的机械保留范围

接口只返回 expected 表达式与受限 Python comparison。Python 重建原 Assert AST 中的 expected operand，并由既有 guard 检查 actual 的 AST、位置、出现次数和诊断表达式保持不变；TS/Go 只替换期望值的字节范围，继续验证 matcher/API、actual 与 Go 失败语句保持原结构。Go 已有 scalar-conversion 形状的 wrapper 由程序保留，只改变里面的 literal。候选 setup/input edits 由程序持有，模型响应不能提供新的 setup、helper 或完整 assertion 代码。

已有测试对 Python actual/diagnostic、Go wrapper/failure body/operator、TS matcher/actual，以及缺失或多余决策都有具体覆盖。本次重新执行 `tests/test_singleton_oracle_slots.py` 与 `tests/test_relation_semantic_instrumentation.py`，共 **35 passed**。其中后者通过真实物化后的命名测试执行，覆盖 fresh/cache、正确/错误实现、语义在插桩前后及 assertion 边界；不是只检查 JSON 或字符串。

这些是结构保留保证。它们不证明 literal 类型兼容、oracle 正确或强度不下降，也不证明原 actual 没有副作用。现有模块对此表述清楚。Python 在同 family 内改变比较也可能调用不同特殊方法。Go conversion-shaped 名字尚无类型解析证明，可能被 shadow；不能把语法名字匹配当成 builtin 类型证明。

## 3. Python family 限制是语义表达能力边界

通用例子：`parse_optional(None)` 返回 `None`，原断言是 `assert actual is None`；组合后的输入为字符串 `"300"`，规范期望为整数 300。正确的新断言是 `assert actual == 300`。

实际执行本地 toy，原断言通过，组合后的值比较通过；将它改成 `actual is 300` 的 identity 比较失败。当前 slot 从原运算符生成 `allowed_comparisons=["is", "is not"]`，因而 `expected="300", comparison="=="` 被拒绝为 unknown。`is not None` 虽可能通过，却不能替代整数值的正确性检查。

因此，“保留 actual”并不蕴含“保留原比较 family”。当前限制会遗漏合理 oracle。这是 frontend/guard 的表达范围，不能归因于 LLM 输出不好，也不能假设所有合理组合都应保留 `is`。本轮保持冻结接口不变；后续若扩展比较表达，应另立版本与可比较实验，而不是回改已有结果。

同理，chain comparisons、一般谓词 assertion、自定义 assertion helper，以及现支持集之外的 TS matcher/Go assertion API 不会自动变成可编辑槽。Python 未知 expected 表达式可保留原表达式并在许可 family 内改比较，不能任意重写其调用或属性读取。editable 仅表示存在受支持的结构修改，不表示所有合理 oracle 都可表达。

## 4. 上下文完整性与 overlap 范围

请求提供整个修改后测试、未截断的 issue contract、明确 helper/fixture/donor 源码和有限深度的已解析声明；超过请求尺寸时整条记为 unknown，不静默截掉尾部断言。source context 明确标为 `partial`，未声称完整程序切片。

不过，声明遍历从原 frontend 的调用开始，并未对修改后的候选重新解析调用。通用真实 frontend toy 把 `original(1)` 改成 `alternate(1)`，两函数都在 corpus：modified_test 确实调用 alternate，context 却仅提供 original 声明，且 `missing=[]`。因此 missing 只记录此次原图遍历遇到的缺口，不能解释为候选依赖已齐全。显式 `source_contexts`、donor 等可以补充内容，但不提供一般完整性保证。该结果已告知接口负责人，本轮没有扩展调用解析或改变 paired prompt。

输入 edit 与 assertion source span 重叠时只读，保留了“修改输入”和“修改原 oracle”两类源码变换的边界；其代价是同一 assertion 内直接构造输入的检查暂不能同时获得 expected-slot 修改。这是明确的覆盖损失。审查也尝试了 Go 嵌套 if 的潜在 assertion-span 重叠，但真实 frontend 只提取内层 assertion，因此没有把手工伪造的双层 inventory 当作已发现的生产 bug。

## 5. 可复查材料与版本边界

所有本地复现、源码 SHA、快照与输出封存在 [singleton_slots_code_review_v1](../../../results/program_relation_search/program_relation_search_20260929/singleton_slots_code_review_v1)。执行：

```bash
.venv/bin/python results/relation_search_20260929/singleton_slots_code_review_v1/review_probes.py
```

[review_probes_result.json](../../../results/program_relation_search/program_relation_search_20260929/singleton_slots_code_review_v1/review_probes_result.json) 同时保存两项修复前后行为、comparison-family toy 和 changed-call-context toy。该脚本先校验快照 SHA；修复前 instrument 来自本审查 snapshot，修复前 slots 来自冻结 v3 `algorithm_snapshot` 的只读副本，另有来源与 SHA 记录。一般 review snapshot 捕获 slots 时它已修复，不能冒称为修复前版本。当前函数 SHA 也随重放保存。

该审查只确认上述局部运输错误及表达边界，没有用 target/verdict 选择反例，没有改变搜索排序，不构成新的 issue resolution 或 oracle precision 结果。
