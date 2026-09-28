# 17 个目标缺口的独立评价清单

这是评价侧真值。`target_census.json`含源test完整ID、原始/别名路径、历史step、可观察断言、来源哈希与证据。禁止导入生成流程。17个trial对应14个task。

Test hit仅表示命中已登记源测试；Scenario hit要求生成测试实际实现目标关系；Correct oracle要求期望符合issue；Control pass要求同一候选关联源控制实际通过；Actual target failure还要求运行失败确由该关系与观察暴露。任何一层未知都不能称完成。

| Case | 主要源测试（完整ID见JSON） | 必须形成的关系 | 必须检查的观察 |
|---|---|---|---|
| P1 | `test_kitty_key_phase` | 功能键/特殊键编码与repeat/release相位在同一个输入包中组合 | 输入只产生一个正确Key事件，phase保留repeat/release；拆成多个事件也属于同一目标缺陷。 |
| P2 | `test_kitty_non_shift_modified_printable_has_no_character` | 非shift-only的修饰快捷键与非空associated text绑定到同一key包 | 快捷键character仍为None；不能将任意字段失败代替此观察。 |
| P3 | `test_kitty_keyboard_protocol_alternate_metadata` | alternate shifted key与包含shift位的组合modifier同时出现 | 别名集合包含已由shifted字符代表shift语义的快捷键，如ctrl+plus；不能要求冗余shift。 |
| P4 | `test_magic_start_stop_roundtrip` | 同一个含空格路径以合法shell quoting传入sessionbundle magic接口 | magic操作真实目标路径，start/status/stop/已存在路径语义与直接API一致；避免只比较返回字符串。 |
| P5 | `TestCompiledFunctionGoCall` | 从Go调用入口获得复合返回结构，内部含可调用闭包，再实际调用其成员 | 成员返回值符合程序语义且不发生VM帧错误/panic；只测试直接返回单个闭包不足。 |
| P6 | `TestGoCall_CloneIsolation` | 克隆对象内两个闭包共享一个捕获状态，依次写入后读取，同时核对源实例隔离 | clone的reader必须看见clone writer的更新，原实例状态不受影响；两个closure独立计数不足。 |
| P7 | `should resolve `Recur` when composed through `pipe`` | 递归schema内部组合非恒等且可观察的transform，并执行到该递归层 | 解析结果包含该层转换效果；identity或未到达转换层的数据不足。 |
| N01 | `test_iter_ndjson_invalid_line`；`test_iter_ndjson_streams_incrementally` | 同一个未耗尽真实response stream在NDJSON解析中抛异常 | DecodingError出现后同一response.is_closed为True。 |
| N02 | `test_multipart_response_streaming_consumes_and_closes`；`test_multipart_response_malformed_framing` | 同一个streaming multipart response遇到畸形framing/closure | DecodingError出现后同一response.is_closed为True。 |
| N03 | `<script>` | 两个输入来源归一化为同一物理目录，同时应用有限全局batch额度 | 足够不同输入文件下成功处理数达到额度；不能只观察exit_code或无限额度。 |
| N04 | `<script>` | safe bulk UPDATE写入invariant实际读取的字段，使该谓词由真变假 | CLI拒绝非法更新且数据库保持原状态；COUNT invariant配UPDATE name没有判别力。 |
| N05 | `TestOutputTruncatePreserveResetsFromDefault`；`TestOutputTruncatePreserveResetsFromOpts` | Output.Truncate入口启用PreserveResets，输入含reset且visibleWidth<=width | 输出仍在内嵌reset后重开原样式并保持末尾reset；长度断言不足。 |
| N06 | `TestMerge3Way`；`TestMergeIndependentAdds` | 同一base/parent，一侧改已有child文本，另一侧只新增兄弟节点 | 不产生冲突，且结果同时保留更新文本和新兄弟节点。 |
| N07 | `TestMergeContentConflict`；`TestMergeNonOverlappingChanges` | 同一文件的两侧修改区间起点不同且部分相交，例如sA<sB<eA<eB | merge报告冲突；完整Worktree观察可进一步检查markers与index stages。 |
| N08 | `TestWaitForDurability`；`TestDurabilityNotify` | 同一DB中真实sync batch起点s和写入数k定义排他上界，等待target=s+k | 下一序号未持久化前不成功通知/返回；随后提交覆盖目标的batch应成功。 |
| N09 | `spawns entities on flush`；`adds and removes traits` | 同一pending trait/record有多个字段，部分显式值、部分省略，flush前get | 同一读取同时包含显式值和省略字段默认值。 |
| N10 | `zod parser and formatter enforce requiredIf` | 同一requiredIf schema通过未提供mode的默认Zod parser校验触发条件但缺少dependent字段的输入 | 默认parser拒绝该输入，与显式put的要求一致；普通schema默认parser通过不是目标。 |

证据强度：P1–P7沿用此前独立运行审计（历史专门方法，不是新算法成绩）；N03/N04/N05/N06/N09/N10有上一轮完整候选重放；N01/N02/N07/N08本轮补齐完整候选重放。N09默认值一侧原validation是console观察，不伪造为已有assertion。

对轨迹临时文件，源ID按原始版本保留；同一文件后续append、覆盖或删除不会抹掉先前validation。匹配时允许同名且同来源路径的不同历史行号，但不能只凭全仓同名匹配。
