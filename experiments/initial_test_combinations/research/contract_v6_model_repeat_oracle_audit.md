# v6 模型独立重抽样的 oracle 审计

**此次重抽样仍检出 7/7 个已知目标，候选差分保持 49 条、参考报警保持 3 条。没有新增或变化的报警；唯一新增测试两边均通过，但其契约支持仍需独立确认。** 这不是选择最优模型输出：三个请求逐字节相同，生成器实现快照哈希全部相同，首次与重抽样结果分别保留。

[紧凑审计数据](experiments/contract_v6_model_repeat_oracle_audit.json)记录完整报警 ID、准入变化、结果与模型文件哈希。未修改算法、筛选或删除产物，未读取参考补丁。

| Case | 首次准入 | 重抽样准入 | 共同义务 | 新增/移除 | 候选报警 | 参考报警 |
|---|---:|---:|---:|---:|---:|---:|
| P1 | 98 | 98 | 98 | 0/0 | 21 | 2 |
| P2 | 90 | 90 | 90 | 0/0 | 1 | 1 |
| P3 | 21 | 22 | 21 | 1/0 | 3 | 0 |

新模型的三个 predicate 源码哈希均变化，但有限候选集合上的 P1/P2 决策完全一致；P3 仅增加一项。全部共同义务的输入、原断言、expected 和来源信息逐项相同，重新执行的候选/参考 pass/fail 状态也无一变化。25 条协议报警及 3 条参考报警的 ID 集合与[首次独立审计](contract_v6_oracle_audit.md)完全相等，因此没有新的目标漏报、错误报警或参考冲突类别。

全实验观察到 264 条组合义务，比首次多 1 条；仍有 168 个对照、9 个原始 reference control 失败、28 个静态不支持位置，没有编译、导入、超时、跳过或缺失结果。P4–P7 当前 manifest 和所有测试文件与 `contract_v6_reproduction` 逐字节相同，复用结果文件也逐字节相同且 artifact 哈希匹配，已独立核验。

## 唯一新增准入：双方通过并不足以证明 oracle

P3 新增 `transport_79aefced27a59a5e`：

```text
source:    ESC[61:43;5u
follow-up: ESC[0:43;5:1u
assertion: "ctrl+plus" in aliases
```

新 predicate 的 alias 分支不再具有首次 predicate 的 code0 排除条件，因此把“已知主键带 shifted alternate”的 membership 搬到“code0、没有 wire associated text”的场景。新测试和声明的 source control 在两边全部通过；它不是观察到的误报。现有 issue 对 code0 的明确保证集中在 associated text 的 key/character 行为，不能仅凭双方通过就证明这一新的 alias 运输关系。

**也不能据 code0 没有 wire text 判定输入非法。** 官方 producer 中 `has_text` 来自原始事件文本，wire text 是否输出还取决于 `embed_text`。在 `report_text=true`、`embed_text=false` 时，事件有文本却可以不在键包中携带 text。完整路径依次经过 `encode_glfw_key_event`、`init_encoding_data`、`encode_key`、`serialize`；例如 key0、原事件文本 a、ctrl 可以沿该路径输出 `ESC[0;5u`。这是源码路径推导，并非新执行的 producer 实验。[官方 encoder](https://raw.githubusercontent.com/kovidgoyal/kitty/master/kitty/key_encoding.c)。

因此审计撤回了最初仅根据 `!ev.key && !ev.has_text` 推导“code0 必须有 wire text”的判断。新增项记为 **契约支持待确认**，不记为已证实非法输入、错误 oracle 或误报，不据此增加过滤规则。

同类 wire 形状其实已存在于首次 v6：P1 的 `transport_5d252908b7fbb200` 检查 `ESC[0:43;6:1u` 的 shifted_key=plus；P2 的 `transport_129633607be25a27` 检查 `ESC[0:43;5:1u` 的 modifiers=(ctrl,)。两条在两次实验中均双侧通过。它们进一步说明应区分完整编码路径、具体字段契约与测试通过，不能用局部 producer guard 批量收紧输入域。

本轮未观察到新的错误报警，协议报警的 issue 矛盾数仍为 0；但新增通过项也没有因为零报警而自动获得语义证明。两次 7/7 使用的是同一组七个开发 pilot，不是十四个独立样本，尚不能证明模型输出稳定或方法具有总体零误报、零漏报性质。
