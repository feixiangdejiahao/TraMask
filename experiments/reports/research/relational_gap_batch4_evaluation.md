> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_batch4_evaluation.md) · [旧路径映射](../../../results/path_map.tsv)

# Relational gap batch4：独立评价

本轮完整执行17个trial。目标原测试静态召回保持17/17，实际观察到目标原测试衍生候选结果从batch3的10/17增至14/17；**独立确认的正确目标缺陷检出从1/17降至0/17**。执行环境改善没有自动带来组合关系和正确oracle的改善。

| 指标 | batch3 | batch4 |
|---|---:|---:|
| 目标原测试静态召回 | 17/17 | 17/17 |
| 模型获准候选包含目标原测试 | 14/17 | 14/17 |
| 观察到目标原测试衍生候选结果 | 10/17 | 14/17 |
| 正确组合＋正确oracle＋原control通过＋目标失败 | 1/17 | 0/17 |
| 冻结静态候选 | 8448 | 8631 |
| 模型获准候选 | 809 | 656 |
| 有运行索引的候选 | 797 | 655 |
| 有具名结果的候选 | 581 | 529 |
| 模型调用 | 34 | 34 |
| 响应整体协议通过 | 32/34 | 34/34 |
| 模型token总量 | 919231 | 908563 |

预算仍为每例至多2次模型请求、每次最多64个候选与32个获准候选；请求还有80KB上限，因此实际提供1347个候选，并非17×128。没有重试、按目标标签回选或单例补救。149个执行组中18组有生成阶段执行错误，7组有Go编译错误，2组超时；这些不算目标缺陷证据。

## 为什么N10本轮没有检出

此前成功的缺省mode候选 `32dd7661b8b920895cff7c62` 仍在本轮request0中，程序也仍正确推导了 `mode='put'` 默认值。模型本轮没有选择它；validation记录为 `not_admitted_by_model`。这不是静态分析遗失、预算挤出或执行失败。本轮获准的4个N10候选只是字段/枚举名替换。

同一缺省mode场景的历史版本 `60bd2b9ea322c0be67393911` 也被提供但未获准。两者的原 `toThrow(z.ZodError)` 都正确，但本轮均没有运行，不能继承之前批次的运行结果计分。这暴露了模型作为执行门槛的漏报风险。

## N05说明“提出场景”与“找到正确断言”不同

两个offered候选 `q_1ac0e50a0bdf2e56c61c0799` 与 `q_6240e44f1afdf5a42dd72ea8` 将preserve测试的width从5改为6。文本foobar可见宽度为6，确实形成preserve与不截断的目标组合。但原断言仍期望只含ba的截断输出，不能原样保留；正确输出必须包含完整bar并保留重应用样式。

模型尝试生成局部期望修订，但decoder报 `index_error`：显示的源局部常量want尚未传播为模型可用的pre值。两个候选均未物化。独立评价因此记录机械场景命中、原oracle错误、实际检出未知/未证明。不能把source-q失败直接算成功。

四个offered-only候选的审核使评价文件中 `scenario_hit=2/17`、`correct_oracle_on_target_scenario=1/17`；**获准并执行的目标场景是0/17**。非获准候选并未全部做穷尽语义审核，这两个数字是已确认的场景证据，并非完整静态场景召回率。

## 各例获准与执行

| Trial | 获准候选 | 有具名结果 | 观察到目标原测试衍生结果 | 确认目标检出 |
|---|---:|---:|---|---:|
| P1 | 55 | 55 | 是 | 0 |
| P2 | 64 | 64 | 是 | 0 |
| P3 | 44 | 44 | 是 | 0 |
| P4 | 14 | 14 | 是 | 0 |
| P5 | 20 | 9 | 否 | 0 |
| P6 | 16 | 16 | 是 | 0 |
| P7 | 18 | 18 | 是 | 0 |
| N01 | 64 | 64 | 是 | 0 |
| N02 | 64 | 62 | 是 | 0 |
| N03 | 42 | 38 | 是 | 0 |
| N04 | 47 | 26 | 是 | 0 |
| N05 | 6 | 6 | 否 | 0 |
| N06 | 55 | 17 | 是 | 0 |
| N07 | 56 | 17 | 是 | 0 |
| N08 | 24 | 20 | 是 | 0 |
| N09 | 63 | 55 | 是 | 0 |
| N10 | 4 | 4 | 否 | 0 |

P1/P3的新regex变换没有组成所需编码字段组合；P7的新调用上下文多为readonly或再次recursive，缺少可观察的非恒等transform。N04没有获准的SQL读写交互场景。N06仍保留两分支冲突修改，N07只改文件名/提交标签而未改变hunk几何，N08没有将等待值绑定到实际batch的exclusive high，N09没有在deferred pre-flush get中观察部分显式字段与默认字段。全部656个获准候选的逐例排除理由保存在 `batch4_manual_review_notes.json` 与 `batch4_review_aids/`。

N01的新live-stream＋invalid-charset候选有两个通过的原control，但运行在 `is_stream_consumed=False` 处失败；charset验证在消费前拒绝，还没到close断言。这不是目标的读取中NDJSON解析失败后资源未关闭，不能算新增命中。

## 误报和执行可靠性

274个候选观察到具名失败，其中217个具有通过的完整原control。抽查确认2个错误oracle，其余215个受控失败仍为unknown，不能据此估算precision或宣称误报减少。

- P1 `q_8301e007b73f59fa6a996516` 将release编码改成默认press编码，却仍期望release；同一误报持续存在。
- N01 `q_70b4e352d07f963c66fdac82` 完整消费stream之后又要求response未关闭；正确关闭被错误断言判成失败。本轮该候选终于有执行结果，因此暴露了原先被收集失败掩盖的误报。

v4把原control与生成候选放到同一离线容器的两个独立进程，先运行control，再安装候选文件运行生成测试，分别保存结果与源码hash。Go支持仓库go.mod/module-local包名解析和有明确来源的历史helper依赖闭包。N07首次有两组共17个候选具名执行，其余6组仍受历史formatcfg缺失影响；P6全部16个候选可观察。原control的import/helper物化上下文有独立记录，未声称支持文件字节完全相同。

同一候选组仍可能被编译失败、挂起或收集异常阻塞，不具备逐候选隔离。对历史脚本是否写入SUT做了独立检查；不把改写SUT后的结果当作原补丁证据，也没有宣称做过完整动态源码完整性证明。

生成器和模型未读取census、独立probes、隐藏verifier、参考补丁或审查标签。22个归档driver依赖hash验证通过。`all_17_targets_proven=false`。

## 复核

```bash
.venv/bin/python scripts/evaluate_relational_gap.py evaluate \
  --batch-root results/relational_gap_20260928/batch4 \
  --emitted-root results/relational_gap_20260928/batch4_emitted \
  --reviews results/relational_gap_20260928/batch4_reviews_audited.json \
  --output /tmp/relational-gap-batch4-recheck.json
```

新增source-q与LLM-q两条执行lane属于下一轮v5，不能回填本轮。v5模型预算不变，但执行预算增加到每例最多192，比较时必须明确成本变化。
