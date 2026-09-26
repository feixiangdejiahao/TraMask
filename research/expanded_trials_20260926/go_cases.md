# 2026-09-26 Go trials：人工组合缺口复核

本报告是回顾性发现，不是盲测。下列四条均来自公开 v1.1 索引，模型为 `deepseek-v4-flash`，outcome 为 `fail`；读取了 agent trajectory、最终候选补丁、公开 verifier 日志及本地公开 task 的测试补丁。没有读取参考实现，没有调用 `.env` 模型。`step_id` 均为 trajectory 内实际编号，不是零基数组下标。原始文件、来源 URL 和 SHA256 在每条 trial 的 `acquisition.json`；额外审核材料和基线 SHA 在 `review_evidence/provenance.json`。

纳入标准：实际执行的 validation 分别覆盖可组合的行为；具体缺失关系能由输入、状态或代码路径表达；公开失败与候选代码解释一致。不能由 fail 标签直接推断“因为没有组合”。这里的因果主张限于：补充所述判别测试可以暴露已提交候选的缺陷；不主张它必然使 agent 最终修复 issue。

## G1：termenv——入口相同语义，快速返回绕过观察义务

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/termenv-preserve-ansi-resets__Qgybsr5)，仓库 muesli/termenv，公开结果 119/122 通过。

真实验证 A：step 32 编写 `TestOutputTruncatePreserveResetsFromDefault` 和 `...FromOpts`。输入 `"\x1b[1mfoo\x1b[0mbar"`，宽度 5，开启 preserve；断言完整输出为 `"\x1b[1mfoo\x1b[0m\x1b[1mba\x1b[0m"`。这覆盖 Output 入口的“需要截断”路径。

真实验证 B：step 38 的 `TestStyleTruncatePreserveResetsFits`，`String("foo\x1b[0mbar").Bold().PreserveResets().Truncate(100, ...)`，断言 reset 后仍重开 bold、末尾 reset。这个“不需要截断”场景走的是 Style 入口。初始 step 32 编译失败，不能计为通过；补全实现后 step 38、39、43 和 step 64 的非缓存测试均通过。

遗漏组合：**Output.Truncate × preserve=true × `ANSIWidth(input) <= width`**。它不是任意字符串拼接，而是将 B 的分支条件搬到 A 的调用入口和同一个 styled 输入上。

候选根因：`model.patch:316` 定义 `ansi.TruncateANSI`；`ANSIWidth(s) <= width` 就 `return s`，出现在处理 reset token 之前。`Output.Truncate` 只是设选项并转发；Style 入口则提前调用 `Styled`，因此 B 单独通过并不能保证 Output 路径也通过。

公开判别：`TestMarsOutputTruncate_UsesPreserveResets` 用 `bold+"a"+reset+"b"`、宽度 10、Output 默认 preserve=true，断言 bold 出现两次、reset 后有重开且最终 reset。实际得到 `"\x1b[1ma\x1b[0mb"`。`OptsOverridesDefault` 同根因失败。第三个宽度 0 + OSC 的失败属于另一缺口，本条不依赖它。

程序可计算特征：公共入口汇合到同一 callee；选项写入与 callee 内早退形成控制依赖；A/B 的差异是谓词 `visible_width <= bound`，观察是 token 序列义务而非输出字符数。

证据：[真实步骤](../../results/expanded_trials_20260926/trials/termenv-preserve-ansi-resets__Qgybsr5/review_evidence/validation_steps.txt)、[候选补丁](../../results/expanded_trials_20260926/trials/termenv-preserve-ansi-resets__Qgybsr5/model.patch)、[公开测试源码](../../results/expanded_trials_20260926/trials/termenv-preserve-ansi-resets__Qgybsr5/review_evidence/public_task_test.patch)、[失败日志](../../results/expanded_trials_20260926/trials/termenv-preserve-ansi-resets__Qgybsr5/verifier/ctrf.json)。

## G2：etree——共享父节点不等于相同修改对象

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/etree-xml-diff-patch__N3t8VYg)，仓库 beevik/etree。公开结果 47/67 通过，其中有 15 项没有执行结果；只采用五项有真实断言失败中的三路合并失败作证据。

真实验证 A：step 29 的 `TestDiffApplyRoundTrip` 分别验证新增和文本修改，`TestGeneratePatchFormat` 明确检查文本替换生成 `/root[1]/a[1]/text()`；初次有失败并修复。step 42 多组 roundtrip 和 merge 测试通过；step 109 完整 `go test ./... -count=1` 通过。

真实验证 B：step 51 `TestMergeIndependentAdds` 从 `<root><a/></root>` 分别新增 `<b/>` 与 `<c/>`，断言没有冲突，执行通过。step 29 的 `TestMerge3Way` 还组合了文本修改与新增，但双方都修改同一个 b，断言正好一个冲突；不能据此称所有合并组合都没测。遗漏的是 **一个分支修改已有子元素文本，另一分支只在共同父节点新增兄弟元素**，两者应独立。

公开判别：base=`<root><item>Original</item></root>`，ours 将 item 改为 Ours，theirs 保持 item 并新增 `<extra/>`。应无冲突，结果保留 Ours 和 extra。实际冲突数 1，结果仍为 base。相关真实失败包括 `TestMerge3Way`、`TestDiffDocumentMerge3WayMethod` 和交换双方角色的 `TestMerge3WayOursAddsTheirsModifies`。

候选根因：`model.patch:1359` 的 `classifyConflict` 先将路径相同或互为前缀判为 related，再在任一操作是 structural 时判冲突。添加节点的 Path 是父路径 `/root`，文本修改路径是 `/root/item[1]`，虽然路径前缀相关，写入的实际位置不同。只有 Add×Add 做了豁免，Add×TextUpdate 没有对应判断。

程序可计算特征：两个操作的 effect footprint 应分清“父节点的 child 集合插入”与“已存在 child 的 text 写入”。缺失关系是资源范围的独立性，普通 call graph 或共同父对象 may-alias 会产生过粗结果。最小判别保留两个输入的非重叠 effect，并同时断言 conflict=0 与两个修改均保留。

证据：[真实步骤](../../results/expanded_trials_20260926/trials/etree-xml-diff-patch__N3t8VYg/review_evidence/validation_steps.txt)、[候选补丁](../../results/expanded_trials_20260926/trials/etree-xml-diff-patch__N3t8VYg/model.patch)、[公开测试源码](../../results/expanded_trials_20260926/trials/etree-xml-diff-patch__N3t8VYg/review_evidence/public_task_test.patch)、[失败日志](../../results/expanded_trials_20260926/trials/etree-xml-diff-patch__N3t8VYg/verifier/ctrf.json)。

## G3：go-git——相等、分离都测过，部分重叠仍然遗漏

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/go-git-worktree-merge-conflicts__ruQZqrh)，仓库 go-git/go-git。公开 16/19 通过；三个 fail 包括一个父 suite，实际有两个具体失败子测试，不能当成三个独立缺陷。

真实验证 A：step 62 `TestMergeContentConflict` 在同一 file.txt 的同一行分别写 OURS/THEIRS，检查 `ErrMergeConflicts`、三种 marker 和 index stages 1/2/3。修复最初测试编译问题后 step 65 逐项通过。

真实验证 B：同批 `TestMergeNonOverlappingChanges` 在同一个三行文件首行和末行分别修改，断言无错误且两个修改均存在；另有重复行的分离修改。step 66、73、74 的诊断运行也覆盖重复行相同位置冲突或分离，不覆盖错位多行区间的部分重叠。step 127 再次逐项通过；step 145 最后恢复临时测试运行通过，然后删除测试文件。源测试确实执行过，即使未留在最终补丁。

遗漏组合：**同一文件上的两次多行修改，起点不同但区间相交**。公开 `TestMergeConflictOverlappingRegions` 中 ours 修改第 2–3 行，theirs 修改第 3–4 行。期望 ErrMergeConflicts、marker、冲突索引 stages；实际没有 error，直接拼接两组修改。`TestMergeComplexOverlap` 在更多重复行上复现相同现象。

候选根因：`model.patch:844` 的 `mergeText` 只当双方下一 hunk 的 start 都不大于当前 `basePos` 时同时处理冲突。在当前位置只命中 ours 时直接输出整个 ours hunk 并推进到其 end；如果 theirs.start 落在刚跨过的区间，下一轮已没有 ours hunk 可比较。所需判断是区间交集，不是“当前扫描点双方是否同时开始”。

可计算特征：两个读自同一 base 的 effect 区间，现有测试仅占据相等和不相交两种关系；尚缺 `sA < sB < eA < eB`（或对称）的见证。可由区间约束直接生成五行内容，不需要自然语言 feature 名称。断言同时观察错误、文件内容、索引状态，避免只检查任一修改存在。

证据：[真实步骤](../../results/expanded_trials_20260926/trials/go-git-worktree-merge-conflicts__ruQZqrh/review_evidence/validation_steps.txt)、[候选补丁](../../results/expanded_trials_20260926/trials/go-git-worktree-merge-conflicts__ruQZqrh/model.patch)、[公开测试源码](../../results/expanded_trials_20260926/trials/go-git-worktree-merge-conflicts__ruQZqrh/review_evidence/public_task_test.patch)、[失败日志](../../results/expanded_trials_20260926/trials/go-git-worktree-merge-conflicts__ruQZqrh/verifier/ctrf.json)。

## G4：Pebble——成功范围和未来等待的边界没有绑定到同一状态

[公开 trial](https://deepswe.datacurve.ai/data/v1.1/trials/pebble-durability-wait-apis__2UjdyFm)，仓库 cockroachdb/pebble，公开 99/103 通过。

真实验证 A：step 117 `TestWaitForDurability` 在同一个 batch 写两条 key，Apply(Sync) 后读取 `seqNum=b.SeqNum()`，检查 Wait(seqNum)、Wait(seqNum+1) 都成功，`DurableState>=seqNum+2`。这里 seqNum+1 仍是该两条记录批次内部，不能当作测试了“下一条未持久化记录”。

真实验证 B：`TestWaitForDurabilityWaits` 先等待常量 100000，提交一条较小序号写入后检查仍阻塞，最后 Close 才返回错误。`TestDurabilityNotify` 检查已持久化 seqNum 的 channel 成功，却把 future=100 的 channel 丢给 `_ = ch`，并没有断言最邻近 future 边界。step 126 读取前述定向测试日志得到通过，step 234 race 定向测试也通过。

遗漏组合：**以 A 真实提交得到的范围终点构造 B 的等待目标，而不是远未来常量**。对一条写入的 batch，其 seq=s，exclusive high=s+1；订阅 target=s+1 应等待下一批。公开 `TestBatchDurableDurabilityNotifyBlocksUntilDurable` 正是提交一条写入后使用 `b1.SeqNum()+1`，非阻塞 select 发现 channel 已就绪，失败消息为 `DurabilityNotify must not fire before target is durable`。

候选根因：`model.patch:340` 自己将 HighestDurableSeqNum 标为 exclusive；`onBatchSyncComplete` 用 `b.durableSeqNum + keyCount` 更新 high；但 `registerLocked` (`model.patch:499`) 使用 `seqNum <= high` 判成功，`signalLocked` (`:474`) 同样使用 <=。边界应区分相等与严格小于。这里 seqNum 的实际关联来自测试中的 `Batch.SeqNum()`，并非根据 verifier 名称猜测常数。具体数字依赖 DB 初始化，论文中应写符号 s；如做全仓库 replay 应记录其真实值。

同一个边界缺陷还会遮蔽失败：前一次成功恰好使 high 等于后一批 start，而 `registerLocked` 在检查 firstErr 前先以 <= 成功返回；公开 sync-failure 案例于是 WaitForDurability(b2.SeqNum()) 得到 nil。本条主证据选不依赖错误注入的 Notify 边界测试，不把另外三项失败都说成相同根因。

可计算特征：动作返回值（批次起点）+容器基数（keyCount）定义一个已完成范围；另一个测试消费的是序号目标。组合必须让消费者目标等于生产者范围边界，同一个 DB identity 是必要条件。单纯拼接“先提交再等待 100000”并不充分。

证据：[真实步骤](../../results/expanded_trials_20260926/trials/pebble-durability-wait-apis__2UjdyFm/review_evidence/validation_steps.txt)、[候选补丁](../../results/expanded_trials_20260926/trials/pebble-durability-wait-apis__2UjdyFm/model.patch)、[公开测试源码](../../results/expanded_trials_20260926/trials/pebble-durability-wait-apis__2UjdyFm/review_evidence/public_task_test.patch)、[失败日志](../../results/expanded_trials_20260926/trials/pebble-durability-wait-apis__2UjdyFm/verifier/ctrf.json)。

## 排除和未完成复核记录

| Trial | 处理理由 |
|---|---|
| abs-stepped-slices__9zkafrW | 排除：step 67 已执行 string[-1] 赋值并看到错误，step 68 接受它；不是未尝试组合。 |
| tengo-destructuring-bindings__awWe9tP | 排除：step 174 已执行显式 undefined 与 default 的组合，得到错误 fallback；属于错误期望/解释。 |
| anko-default-function-arguments__WphKgso | 暂不纳入：确实缺 variadic 标记之后再写 default 的非法语法，但主要失败是错误文案，已有 default×variadic 很充分。 |
| anko-typed-variable-bindings__C4eSULm | 不纳入：目标测试未产生运行结果，尚不能建立语义组合因果链。 |
| helm-array-merge-strategies__DML5BdA | 不纳入：失败是合法 annotation 配无 values.yaml 时是否应抑制警告，需澄清契约；不能只凭 verifier 强说方法应检测。 |
| expr-try-catch-errors__K7Ky9kd | 不纳入：仅错误文本 `type mismatch` 被漏分类，未建立比词面模式遗漏更强的组合解释。 |
| participle-grammar-conflict-anal__FkgH7qv | 不纳入：clean report 的多行格式契约，不足以归因于测试组合。 |
| yaegi-go-embed-directives__Wn3dXEr | 不纳入：96 项均缺运行结果，没有语义判别证据。 |
| kcp-go-multiplexed-kcp-streams__EFcMamD | 不纳入：30 项目标测试缺运行结果，未深入排除构建问题。 |
| opa-rego-rule-profiling__cTVrNB9 | 不纳入：25 项目标测试缺运行结果，未建立组合因果。 |
| scc-bounded-memory-spilling__gUnk5y7 | 未完成深入复核：实际已有 csv-stream×bounded×format-multi 比较，不可按失败测试名直接纳入。 |
| prometheus-typed-label-sorting__fNAZpyn | 未完成深入复核：等价数值字符串的 tie-break 与 malformed fallback，需要核对 agent 是否已测试并接受错误输出。 |
| ytt-jsonpath-query-api__yV5BSux | 备选未纳入：过滤器×非数组类型，已有 incompatible-type 与 filter 测试；但标准及 issue 对 map filter 的限制还需独立确认。 |

四例共同支持的抽象不是“多几个操作模板”，而是：**测试覆盖的是参与者之间某一种关系，程序却在关系边界上决策；组合应系统地改变关系，保持参与者身份与观察义务。** G1 是输入度量与阈值、G2 是作用位置的包含/独立、G3 是两个修改区间的相交、G4 是消费目标与已完成范围的相等/越界。这个归纳尚不是已证明充分的通用算法，也不能据此宣称覆盖所有十条新案例。

## 重放状态

2026-09-26 已完成四例最小重放，均保留源对照，未应用参考补丁或 verifier 测试补丁。重放是人工审阅后的判别性实验，不能作为当前算法自动生成成功率。

| 案例 | 重放范围 | 源对照 | 组合实际结果 |
|---|---|---|---|
| termenv | 官方本地镜像，全候选仓库，network none | 两项通过 | Output×fits 返回原始 ANSI 串，未重开 bold，测试失败 |
| etree | 官方本地镜像，全候选仓库，network none | 两项通过 | conflicts=1，结果 `<root><item>Original</item></root>`，文本与新增均未保留 |
| go-git | 提取候选 mergeText 扫描循环、splitLines、conflictMarker，注入 normalized hunks | 相等区间冲突、分离区间无冲突均通过 | `[1,3)`×`[2,4)` 返回 conflict=false，拼接两方文本 |
| Pebble | 提取候选 onBatchSyncComplete、signalLocked、registerLocked，最小依赖替身 | count=2 时 target10/11 成功；far100000 pending | 合成 start=10、count=1 真正计算 high=11，target=11 立即成功，测试失败 |

Go-git 和 Pebble 缺少本地官方镜像，因此上述两项**只是组件重放**。Go-git 没执行 diff normalization、工作树与索引；Pebble 的 10 是合成输入，**不是本次启动 DB 实际分配的序号**，未执行 WAL。组件源码变换、命令、退出码、SHA 都记录在各自 `review_evidence/component_replay/result.json`，可由 [脚本](../../scripts/expanded_trials_20260926/replay_go_components.py) 重建。完整候选仓库重放的 base SHA 和 patch SHA 在各自 `review_evidence/repository_replay_result.json`；run.sh、手写测试和 stdout 相邻保存。

四项测试进程都以退出码 1 结束，因为各自判别测试真实失败，不是编译阻塞；控制测试均通过。Docker 的 stdout 由工具输出逐字保存并在结果中标注转录，组件 stdout 由 subprocess 直接捕获。
