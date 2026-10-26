> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/screened_v4_oracle_audit.md) · [旧路径映射](../../../results/path_map.tsv)

# screened_v4 独立 oracle 审计

本轮 241 条生成测试产生 28 条候选报警，均为受来源对照支持的差分证据。**逐条审计未发现这 28 条中存在与 issue 矛盾的 oracle；但 P2 的已知目标仍被准入模型拒绝，协议子集目标检出为 2/3。** 另外 4 条参考报警中，2 条参考结果与明确需求冲突，2 条输入适用性缺乏充分依据，不能直接宣布为参考 bug 或已证实误报。

本报告只做冻结后的评价，未读取 reference patch、未修改生成器、未把审计 ID 回流为候选筛选条件。原始结果为 `results/combination_testing/screened_v4/evaluation.json`；[逐条审计数据](../../../research/experiments/screened_v4_oracle_audit.json)记录全部 28+4 条证据、断言输出、来源对照、issue 原文与哈希。这里的“未发现无效 oracle”限于实际报警，不是对全部 241 条测试或未知输入空间的正确性证明。

## 1. 冻结版本与计数

v4 的冻结请求使用 `gpt-6-astra`，提供 issue、既有观测、候选 API 文档和具体 proposal，三例均通过 16 条既有事实校准；每例 8 条应接受和 8 条应拒绝都判定正确。批准条数包含 8 条正向校准项，扣除后实际生成数量如下。这里不把模型校准通过当作新组合 oracle 的证明。

| Case | 生成/执行 | 候选报警/差分 | 参考报警 | 原始生成参考失败 | 已知目标证据 | 参考来源对照失败 |
|---|---:|---:|---:|---:|---:|---:|
| P1 | 102 | 25 | 3 | 11 | 13 | 4 |
| P2 | 97 | 0 | 1 | 9 | 0 | 3 |
| P3 | 42 | 3 | 0 | 2 | 1 | 2 |
| 合计 | 241 | 28 | 4 | 22 | 14 | 9 |

没有编译、导入、超时、跳过或缺失结果。21 条生成测试受参考来源对照失败影响，其中 18 条生成测试也在参考失败、3 条仍通过。因此原始参考失败数必须拆为 **22 = 18 条被来源对照阻断 + 4 条参考报警**。全部候选来源对照通过，28 条候选报警的对应参考来源对照也都通过。

## 2. 28 条差分的实际失败位置与语义审计

### P1：25 条全部首先违反单事件解码

输入是 `ESC[1;modifier:event_type{A,B,C,D,E,F,H}` 的功能键序列。候选均把它拆成 **7 个事件**，在 `assert len(events) == 1` 处失败，尚未执行被迁移的 `phase` 或 `character` 字段断言。参考按同一冻结测试解码为一个事件并通过字段检查。

这里不能声称“25 条都证明了对应字段值错误”。独立依据是：仓库 `FUNCTIONAL_KEYS` 明确注册这些编码；issue 要求 Kitty 序列的 press/repeat/release；原始测试要求单个 Kitty 包产生单个事件；候选 `_re_kitty_key` 的 phase 语法只接受 `u` 结尾，而 `_re_extended_key` 不接受 `:event_type`，与日志中的拆包行为一致。官方[事件类型语法](https://sw.kovidgoyal.net/kitty/keyboard-protocol/#event-types)也支持这类功能键带事件类型。

25 条可细分为 13 条 repeat/release phase 检查、7 条显式 press phase 检查、5 条非字符功能键的 `character=None` 检查。前 13 条符合既定目标匹配规则；其余 12 条提供同一解码范围问题的附加证据，不增加已知目标 case 数。没有发现更换 key representation 同时改变 phase 的情况，也没有 v1 那种沿用已改变 phase 常量的错误 oracle。

### P3：1 条目标 alias，2 条 text-only 的额外差异

| proposal | 输入变换（省略 `ESC[`） | 继承的断言 | 候选输出 | 独立语义依据 |
|---|---|---|---|---|
| c0014 | `61:43;5u → 61:43;6:1u` | `"ctrl+plus" in aliases` | 只有 `ctrl+shift+equals_sign` 和 `ctrl+shift+plus` | issue 要求 alternate shortcuts 匹配 shifted forms；既有 membership 使用 plus，文档说明 shifted_key 已表示 shift 后的键。 |
| c0064 | `0;1;97u → 0;5:1;97u` | `character == "a"` | None | issue 明确规定 key-code 0 使用 associated text 作为 key 和 character；非空 text 保持为 a。 |
| c0005 | `0;1;97u → 0;3:1;97u` | `character == "a"` | None | 同上，只增加 alt，而非 ctrl。 |

三条均实际执行到字段断言；对应 source control 两边通过。后两条的候选代码先进入 `has_non_shift` 分支把 character 置为 None，再处理 code-0 text 的分支已不可达；这是依照明确 text-only 需求的附加候选缺陷，不能把它们计为 alias 目标。规范的 text-only 示例没有 modifier，并不能据此推导“任何 modifier 都非法”；官方 encoder 的 key0 有效 text 路径也未清空 modifier。[Text as code points](https://sw.kovidgoyal.net/kitty/keyboard-protocol/#text-as-code-points)，[官方 encoder](https://raw.githubusercontent.com/kovidgoyal/kitty/master/kitty/key_encoding.c)。

因此本轮 `issue_contradicted_differential_witness_count = 0`。这与“方法已经证明零误报”不同：审计的对象是本轮 28 个实际报警，其他生成物和新 case 仍须独立评价。

## 3. 4 条参考报警不能统一称为误报

这四条候选均通过，因而它们本身不属于本轮 28 条候选报警。

| Case / proposal | follow-up（省略 `ESC[`） | oracle | 参考实际值 | 审计结论 |
|---|---|---|---|---|
| P1 c0085 | `97:65:113;2:2u` | `character == "A"` | None | **参考与明确需求冲突。** 仍是 shift-only printable，shifted alternate 65 保留；原测试也覆盖无 associated text 的 shifted printable。 |
| P2 c0000 | `65:65:113;2:1u` | `base_key == "a"` | A | **参考与明确需求冲突。** issue 明确要求 shifted A 保持 base_key a，既有测试也接受主键 65 的此语义。 |
| P1 c0027 | `57358:65:113;2:2;65u` | `character == "A"` | None | **输入适用性未充分确立。** 将主键换为 caps_lock，却保留字母键的 alternate/base-layout 65/113 和 text65。不能仅凭候选返回 A 判定参考错误。 |
| P1 c0111 | `127:65:113;2:2;65u` | `character == "A"` | None | **同类未判定。** 将主键换为 backspace，其他字母键上下文不变。 |

后两条不能简单归为“功能键绝不允许 associated text”：官方 encoder 的 `encode_function_key` 调用 `init_encoding_data` 后执行 `ed.add_alternates = false;`，但保留 `add_text`。需要验证的是这种特定 primary 与 alternate 组合是否受契约支持，而非只做每个数字的局部合法性检查。官方 producer 不生成某结构，也不等于接收器必须拒绝它；在没有独立语义依据前，两条保留为 `input_applicability_unresolved`，既不强行宣布参考有 bug，也不把参考失败当作无效 oracle 的充分证明。[官方 encoder](https://raw.githubusercontent.com/kovidgoyal/kitty/master/kitty/key_encoding.c)（2026-09-23 读取，`encode_function_key` 约第 253–257 行）；[alternate 字段含义](https://sw.kovidgoyal.net/kitty/keyboard-protocol/#key-codes)。

## 4. P2 的漏报发生在模型准入

冻结 proposal **c0037**（`transport_283afda4ff81800c`）已被枚举并送给模型：

```text
source:    ESC[65;4u
follow-up: ESC[65;4:1;97u
assertion: character == None
```

它在非 shift 修饰快捷键上添加 associated text，issue 明确要求这类快捷键 `character=None`。v4 的批准列表没有 c0037，因此没有冻结执行这一组合。证据是 v4 `proposals.json` 和 `approved.json`，哈希已记录；模型只返回 ID，没有解释，不能猜测其内部拒绝原因。

这说明本轮 P2 不是断言检索或组合枚举失败，而是语义准入的错误拒绝。既有事实校准全部通过只能检验校准样例，仍不能保证新交互的准入召回。这个归因只用于评价，不允许按已知缺陷或参考结果补回某个 proposal ID。
