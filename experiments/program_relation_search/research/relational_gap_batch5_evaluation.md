# Relational gap batch5：独立评价

完整执行17个trial后，**确认检出2/17：N02与N10**。batch4为0/17，batch3为1/17。所有试验仍属于方法开发集，不能据此声称对未见任务具有同样效果。

本轮最直接的改进是保留程序提出的原断言候选：模型没有选择N10的正确候选，它仍被执行并检出缺陷。另一个新增结果N02来自程序生成的异常消费场景与原关闭断言；历史测试恢复使其中三个版本获得有效执行。不能把同一trial的三个成功历史版本计算成三个缺陷。

| 指标 | batch4 | batch5 |
|---|---:|---:|
| 静态召回目标原测试 | 17/17 | 17/17 |
| offered原断言候选包含目标原测试 | — | 16/17 |
| 具名报告包含目标原测试衍生候选 | 14/17 | 16/17 |
| 物化候选包含正确目标组合场景 | 0/17 | 4/17 |
| 目标场景且oracle正确 | 0/17 | 3/17 |
| 正确场景、正确oracle、原control通过、目标失败 | 0/17 | **2/17** |
| 冻结静态候选 | 8631 | 8631 |
| 模型实际看到的候选 | 1347 | 1321 |
| 物化候选 | 656 | 1487 |
| 有运行索引的候选 | 655 | 1472 |
| 有具名结果记录的候选 | 529 | 1256 |
| 模型调用 | 34 | 34 |
| 模型token | 908563 | 912131 |

batch4另外审核过未获准的N05/N10 offered-only场景，因此其旧评价JSON中scenario为2；表中采用“物化候选”口径，不能混用两个口径。具名结果只表示报告能匹配候选身份，不代表原control通过、真正覆盖目标或oracle正确。

## 预算与两条执行路径

每例仍最多两次模型请求，每次最多64个offered候选，实际请求受80KB上限影响。本轮1321个offered候选全部保留为source_q假设，另有166个不同字节编辑的llm_q期望修订，共1487个。部分修订只是引号或局部常量展开，并不意味着模型修正了语义。

模型预算保持不变，**执行预算从最多64增加到最多192个候选/例**，不能把结果描述为相同总成本下的提升。source_q始终是待验证假设，模型判断另存；“被执行”不等于“oracle已获证明”。旧评价字段admitted_candidates在v5为0是阶段分类变化，不能理解为模型没有接受任何候选。

| 执行路径 | 候选 | 具名结果 | 原control通过的失败 | 确认目标候选 |
|---|---:|---:|---:|---:|
| source_q | 1321 | 1095 | 538 | 6，来自2个trial |
| llm_q | 166 | 161 | 101 | 0 |

## 两个有效检出

**N10：默认参数与条件必填。** 当前测试候选`32dd7661b8b920895cff7c62`把缺少必填details的调用从`parser({ mode: 'put' })`改成`parser({})`。仓库中默认mode是put，原`toThrow(ZodError)`成立。生成测试实际失败为“应抛错却未抛错”，同组完整原测试control通过。两个历史版本也满足全部条件。本轮模型没有接受当前候选，source_q保留了它。

**N02：流式multipart解析失败后关闭。** 异常场景把body的boundary改为abc而header仍声明BOUNDARY，保留真实stream消费与同一response的关闭检查。程序将消费调用置于源`DecodingError`异常约束内，仅对异常情况下不存在的parts结果断言加guard，保留`is_stream_consumed`和`is_closed`。

历史候选`5542dbe5228a49345d931456`、`c9a30230826dabc23759685e`、`0ef6d44f46f41a6c334ac50a`分别在group012/013/015正确捕获异常，随后恰在`is_closed=False`失败。每组的完整原测试control与donor的所有参数化control都通过，报告无执行错误。另五个同类候选被历史脚本收集错误阻塞，未计成功。其中两个成功候选得到模型保留判断，另一个没有；本次改进不能全部归因于移除模型门槛。

## 两个有场景但未检出的例子

**N05：场景正确，oracle仍错。** 一个候选把preserve模式的`Output.Truncate`宽度5改为6，确实覆盖六个可见字符不截断的场景。原期望却仍只含ba；模型修订只是把局部want展开成相同字符串，仍漏掉r。source_q被同组错型候选阻止编译，llm_q虽失败且control通过，仍因错误oracle而不能算检出。

**N07：场景与oracle正确，支持代码未恢复。** 九个sequence候选将theirs从`a\nTHEIRS\nc\n`改成`THEIRS\nc\n`，ours仍为`a\nOURS\nc\n`，base为`a\nb\nc\n`。修改区间为[0,2)与[1,2)，形成不同起点的重叠；保留`ErrMergeConflicts`合理。所有九个都因历史helper/import无法编译，未取得运行证据。这是末端相同的包含式重叠，不声称已经构造更严格的交叉区间示例。

## 每例结果

| Trial | source_q | llm_q | 具名结果 | 场景 | 确认检出 |
|---|---:|---:|---:|---|---:|
| P1 | 83 | 1 | 84 | 否 | 0 |
| P2 | 87 | 40 | 127 | 否 | 0 |
| P3 | 90 | 12 | 102 | 否 | 0 |
| P4 | 47 | 11 | 51 | 否 | 0 |
| P5 | 81 | 0 | 46 | 否 | 0 |
| P6 | 88 | 0 | 78 | 否 | 0 |
| P7 | 85 | 2 | 80 | 否 | 0 |
| N01 | 78 | 11 | 89 | 否 | 0 |
| N02 | 67 | 20 | 59 | 是 | 1 |
| N03 | 88 | 0 | 76 | 否 | 0 |
| N04 | 48 | 0 | 48 | 否 | 0 |
| N05 | 127 | 56 | 155 | 是，q错误 | 0 |
| N06 | 92 | 0 | 57 | 否 | 0 |
| N07 | 50 | 0 | 10 | 是，未执行 | 0 |
| N08 | 43 | 0 | 25 | 否 | 0 |
| N09 | 97 | 1 | 87 | 否 | 0 |
| N10 | 70 | 12 | 82 | 是 | 1 |

剩余问题有明确的程序分析含义。P2缺少向不存在的可选字段插入值的坐标；P3只识别外层regex捕获，不能追踪后续split中的子字段；N04错误地把内存库items的invariant与另一个文件库t的UPDATE关联，遗漏数据库对象与表身份；N08取到batch起点但未构造exclusive high；N09的部分字段候选发生在立即执行测试，未与pre-flush观察结合。全部1487个物化候选的变换审核保存在`batch5_manual_review_notes.json`与`batch5_review_aids/`，未提供的静态候选仍保留unknown。

## 误报与执行阻塞

724个候选有有效具名失败，其中639个具有通过的原control。独立确认6个属于目标缺陷，4个oracle错误，另629个受控失败仍unknown。**不能以这个非随机、非穷尽审核估计precision，也不能宣称误报已减少。** 已确认错误包括P1把release输入换成press仍要求release、N01完整消费后要求未关闭、N04放宽invariant后仍要求合法insert被拒绝、N05宽度6仍期望截断文本。

252个执行组中36组生成阶段有执行错误，28组control阶段有错误，1组超时。仅source_q的编译阻塞分为：

- 2组33候选：原control可执行，生成文件编译失败。N05两个bool/string字段错配污染28个候选；N08未使用局部变量污染5个候选。
- 11组26候选：纯历史helper或import缺失，control也不能编译。
- 9组20候选：control同样受旧API、未使用外部import等编译问题影响。

这些组不能算缺陷报警。当前按lane和源文件分组，尚无逐候选编译隔离。N02还暴露raw模块脚本被错误克隆首个generator函数的收集问题；不能把这种收集失败计为目标失败。

## 冻结与复核

24个v5执行依赖hash全部匹配。工具会话中断后保留所有已发请求和执行报告，没有重发原30个请求；N02/N08获得本轮17trial明确授权后才补齐各两次首次模型请求。source-only临时物化被归档且未执行，随后各自完整执行一次。

N02静态准备因多行隐式连接bytes的通用解析错误补跑；仅其`exception_contexts.py`生成hash与另外16例不同。因此本轮不是严格单一生成版本，错误尝试和补跑都保留。P5全部7组原始报告存在，但顶层索引中断；从原manifest和未变的报告离线恢复索引，没有重跑测试。

```bash
.venv/bin/python scripts/evaluate_relational_gap.py evaluate \
  --batch-root results/relational_gap_20260928/batch5 \
  --emitted-root results/relational_gap_20260928/batch5_emitted \
  --reviews results/relational_gap_20260928/batch5_reviews_audited.json \
  --output /tmp/relational-gap-batch5-recheck.json
```

主结果为`batch5_evaluation.json`，执行与模型费用为`batch5_execution_audit.json`，输入版本核验为`batch5_driver_archive_audit.json`。生成器与模型没有读取census、独立probe、隐藏verifier、参考补丁或审核标签。`all_17_targets_proven=false`。
