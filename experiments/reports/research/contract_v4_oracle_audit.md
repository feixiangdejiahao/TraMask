> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/contract_v4_oracle_audit.md) · [旧路径映射](../../../results/path_map.tsv)

# contract_v4 独立审计

本报告针对 `results/combination_testing/contract_v4`，**不是 screened_v4**。两条候选报警都有明确语义依据；P1 漏报由模型生成的“只允许 u 结尾”前提直接造成。P1 的 80 条参考报警不是 80 条候选误报：它们在候选上全部通过，其中 78 条输入角色兼容性未获充分支持，2 条与 issue 支持的 shift-only 语义冲突。

审计未读取参考补丁源码或隐藏目标，未修改生成器，未按执行失败 ID 筛选生成物。[紧凑证据记录](../../../research/experiments/contract_v4_oracle_audit.json)包含冻结哈希、80 条报警的完整 ID 分组、各组代表日志及两条候选报警；没有复制 80 份重复长日志。

| Case | 生成/执行 | 候选报警/差分 | 参考报警 | 参考生成原始失败 | 参考原始 control 失败 |
|---|---:|---:|---:|---:|---:|
| P1 | 701 | 0 | 80 | 178 | 4 |
| P2 | 782 | 1 | 1 | 10 | 3 |
| P3 | 199 | 1 | 0 | 2 | 2 |
| 合计 | 1682 | 2 | 81 | 190 | 9 |

112 条生成测试受参考来源对照失败影响，其中 109 条生成测试也在参考失败；因此 **190 = 109 条来源对照阻断 + 81 条参考报警**。两条候选报警的来源对照在两边均通过，无编译、导入、超时或跳过问题。

## 80 条 P1 参考报警的共同根因

79 条都来自同一个原测试：`ESC[97:65:113;2:2;65u`，继承 `character == "A"`，只替换主键编码；另一条删除 associated text。参考实际值全部为 None，候选全部返回 A。

| 类别 | 数量 | 审计判断 |
|---|---:|---|
| 主键换成注册功能键，仍保留字母键的 alternate65/base-layout113/text65 | 78 | **输入适用性未判定。** 覆盖 Escape、Backspace、F 键、媒体键、修饰键及 keypad 等。问题是跨字段角色约束，不是 78 种独立 oracle 错误。 |
| 主键换成 printable `61u`，即 `=`，shifted alternate65 与 text65 均不变 | 1 | **需求支持的参考冲突。** 字符仍由明确报告的 shifted A/text A 支持；不能因主键成为标点就把 shift-only 的 A 抹掉。 |
| 删除 text，保留 printable 主键与 shifted alternate65、shift-only 修饰 | 1 | **需求支持的参考冲突。** issue 与原测试明确要求无 associated text 的 shift-only printable 保持 A。 |

78 条的冻结 predicate 先把所有 `u` 当作统一 Unicode 输入，再在 `followup["text"]` 非空时直接令字符为该 text；没有检查 primary 的角色能否与保留的 alternate 共同出现。官方 `encode_function_key` 初始化后明确关闭 `add_alternates`，却没有关闭 `add_text`。因此不能一概禁止“功能键＋text”；也不能把“官方 producer 不生成这种 alternate 结构”直接升级为“接收器必须拒绝”。这 78 条应保留为 **oracle 适用前提缺少依据**，而不是宣称参考有 78 个 bug 或方法有 78 个已确认误报。[官方 encoder](https://raw.githubusercontent.com/kovidgoyal/kitty/master/kitty/key_encoding.c)（`encode_function_key`，2026-09-23 读取）。

P2 唯一参考报警是 `ESC[65:65:113;2:1u` 的 `base_key == "a"`：候选 a、参考 A。issue 明确要求 shifted A 的 base_key 保持 a，属于同类需求支持的参考冲突。因此全部 81 条参考报警的审计分解为 **78 条输入适用性未判定＋3 条需求支持的参考冲突**；它们在候选均通过，不属于两条候选报警。

## 两条候选报警的语义有效性

| Case | source → follow-up（省略 `ESC[`） | 原断言 | 实际候选失败 | 判断 |
|---|---|---|---|---|
| P2 | `65;4u → 65;4:1;97u` | `character == None` | `assert 'a' == None` | 非 shift modified printable shortcut 增加 text；issue 明确要求快捷键 character=None，原断言被正确搬运。 |
| P3 | `61:43;5u → 61:43;6:1u` | `"ctrl+plus" in aliases` | 只有 `ctrl+shift+equals_sign`、`ctrl+shift+plus` | plus 已是 shifted 表示；issue 要求 alternate shortcut 匹配 shifted forms，既有 membership 在增加 shift 后应保持。 |

两条都执行到字段断言，参考及声明的 source control 全部通过。未发现 issue 矛盾 oracle；`issue_contradicted_differential_witness_count = 0`。这是对这两条实际报警的审计结论，不是全局零误报证明。

## P1 漏报是模型前提错误，不是缺少候选

冻结的 `results/combination_contracts/v4/P1/predicate.py` 第一条规则是：

```python
# Kitty's event-type and alternate/text parameters belong to CSI u.
if not source["key"].endswith("u") or not followup["key"].endswith("u"):
    return False
```

这把只有部分参数适用范围的猜测推广成全局编码限制。phase 的具体保持性判断尚未执行，所有非 u 功能键就已被拒绝；冻结的 701 条测试中非 u 数量确为 **0**。原请求明确把 `15~` 作为另一种编码示例，也要求覆盖 justified context changes，并未要求这一限制。官方功能键编码沿用统一 serializer，事件类型仍写在 modifier 后；事件类型并非 u 专属。[官方事件类型说明](https://sw.kovidgoyal.net/kitty/keyboard-protocol/#event-types)，[serializer 实现](https://raw.githubusercontent.com/kovidgoyal/kitty/master/kitty/key_encoding.c)。

这两类问题方向相反：一方面，模型用错误的全局前提封掉有效组合，造成漏报；另一方面，它对合法数值范围过于宽松，忽略 primary/alternate 的角色兼容性，批准契约依据不足的组合。有限既有事实校验可以排除已见矛盾，但不能证明这种新域边界正确。后续公开协议约束必须独立于 oracle，并记录其依据和支持范围；不能按本轮失败 ID 删选。
