> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_batch6_evaluation.md) · [旧路径映射](../../../results/path_map.tsv)

# Relational gap batch6：独立评价

**确认检出3/17个trial：N02、N07、N10。** batch5为2/17；本轮新增N07来自源码支持依赖恢复后，既有正确重叠场景终于可执行。17例全部检出的目标仍未达到。这里是开发集上的独立人工语义审核加原始运行报告核验，不是未见任务泛化结果。

| 指标 | batch5 | batch6 |
|---|---:|---:|
| 静态召回目标原测试 | 17/17 | 17/17 |
| offered源候选包含固定目标parent | 16/17 | 16/17 |
| 目标组合场景 | 4/17 | 6/17 |
| 目标场景且期望语义正确 | 3/17 | 4/17 |
| 正确场景、正确oracle、完整control通过、目标失败 | 2/17 | **3/17** |
| 同时命中固定census parent的检出 | 2/17 | 2/17 |
| 静态候选 | 8631 | 8631 |
| 实际物化候选 | 1487 | 1538 |
| 有运行索引的候选 | 1472 | 1531 |
| 有具名结果记录的候选 | 1256 | 1404 |
| 模型调用 | 34 | 34 |
| 模型token | 912131 | 922718 |

`target_gap_detected`是科学检出判据；`all_dimensions_proven`额外要求固定parent名字命中。N07来自另一个有效的历史验证测试，因此前者成立、后者不成立，不能用名字不在固定census否定真实缺陷。具名记录也不等于control通过或目标被有效观察。

期望正确与观察充分也不同：P2已经形成正确组合场景，保留的key断言语义正确，但character断言被atomic neutralization移除，因此测试通过而遗漏缺陷。这计入场景且正确期望，不计检出，也不计错误oracle。

## 逐例结果

| Trial | source_q | llm_q | 具名记录 | 目标场景 | 检出 |
|---|---:|---:|---:|---|---:|
| P1 | 90 | 34 | 124 | 否 | 0 |
| P2 | 89 | 47 | 136 | 是 | 0 |
| P3 | 90 | 27 | 117 | 是 | 0 |
| P4 | 44 | 3 | 47 | 否 | 0 |
| P5 | 74 | 0 | 39 | 否 | 0 |
| P6 | 78 | 0 | 68 | 否 | 0 |
| P7 | 85 | 1 | 79 | 否 | 0 |
| N01 | 78 | 13 | 91 | 否 | 0 |
| N02 | 68 | 18 | 86 | 是 | 1 |
| N03 | 95 | 0 | 95 | 否 | 0 |
| N04 | 45 | 0 | 45 | 否 | 0 |
| N05 | 128 | 45 | 173 | 是 | 0 |
| N06 | 92 | 0 | 56 | 否 | 0 |
| N07 | 50 | 0 | 37 | 是 | 1 |
| N08 | 45 | 0 | 23 | 否 | 0 |
| N09 | 97 | 1 | 87 | 否 | 0 |
| N10 | 74 | 27 | 101 | 是 | 1 |

## 正确检出与仍然遗漏的原因

**N02：异常消费与资源关闭。** 八个候选都在捕获DecodingError之后、保留的`response.is_closed is True`断言处观察到False；对应完整源control和donor参数化control通过。batch5只有三个历史版本能有效执行，本轮八个都可执行，但同一trial只计一次。

**N07：不同起点的修改区间重叠。** 七个候选的正确`ErrorIs(ErrMergeConflicts)`在实际nil处失败，完整control通过；另两个相关候选control失败，不能计成功。区间为[0,2)与[1,2)，是不同起点且末端相同的重叠，不是严格四端点交叉。Go实际采用retain_all，pinned observation元数据是Merge前NoError，而实际暴露缺陷的是函数中仍保留的后续ErrorIs；不能夸称已精确锁定该单一断言。

**N10：默认参数与条件必填。** 三个当前/历史候选省略mode后仍应采用默认put并拒绝缺失details；完整control通过，生成测试实际未抛ZodError。三个版本只计一个trial。

**P2：关系有了，关键观察被切掉。** optional associated-text组合已生成，key期望正确但不能发现character错误。这个现象动机化了独立的whole-source-observation消融；本报告不提前合并消融的结果。

**P3与N05：关系有了，期望错误。** P3改为modifier4仍保留Ctrl预期。N05将六个可见字符的宽度改为6，却仍期待丢失最后r的截断字符串；模型修订未修正这一语义。

其余例子仍未构造目标关系，包括P5的GoCall/CompiledFunction组合、P6的共享可变闭包状态、N03重复watch与容量、N04相同数据库/表身份下的UPDATE不变量、N06同base/parent下一侧修改已有child文本而另一侧只增加兄弟XML节点、N08正确exclusive high（现有s/s+1并非所需s+2）、N09延迟flush前的部分字段更新等。完整理由见三个`batch6_manual_review_*.json`；未offered静态候选仍保留unknown，不把手工找到的未执行场景加入成功数。

## 误报、预算与可执行性

1322个offered source_q全部保留为假设，216个不同字节的LLM期望修订另行执行。每例仍最多两次模型请求、最多128源候选与64模型修订；实际候选量与batch5不同，且本轮含多项程序分析和环境改动，不能视为单一模块或严格相同总成本的消融。

| Lane | 候选 | 具名记录 | 受控失败 | 确认目标候选 |
|---|---:|---:|---:|---:|
| source_q | 1322 | 1188 | 593 | 18 |
| llm_q | 216 | 216 | 117 | 0 |

790个候选有有效具名失败，710个同时有通过的完整control；其中18个确认为三个目标缺陷、29个确认为错误期望、663个仍unknown。**审核不是随机或穷尽oracle审核，不能估计precision，也不能因已确认错误数变化声称误报减少或增加。** 非目标但可能合法的新缺陷也不自动当作误报。

268个执行组中，生成阶段7组有错误，control阶段3组有错误，2组超时。源候选编译阻塞从batch5的22组79候选降为4组18候选：3组13候选是历史control同样受旧API/未使用绑定影响，1组5候选是N08生成绑定未使用。纯缺失helper/import类别从11组26候选降至0。N05类型错配污染消失，N07源码依赖恢复支持了有效检出；仍没有逐候选编译/崩溃隔离。超时或编译错误组不能作为缺陷报警。

## 冻结与复核

全17例使用同一45文件生成版本；25个执行依赖与6个Go包源inventory冻结。34/34模型响应均协议有效，零自动重试。2667条生成/control运行索引对应268组完整原始phase报告。source支持恢复依据仓库源码和离线依赖包声明；controls和generated同样进行有记录的import/支持代码物化，因此报告为完整原测试的有记录执行上下文，不声称文件字节从未改变。

这些是**声明范围内的hash一致性，不是完整传递依赖的事前冻结**。事后保守静态导入闭包审计发现12个本地传递依赖未列入45+25清单；它们当前源码与记录的Git blob一致，但这不能排除运行时临时修改。`batch6_7_generation_boundary_audit.json`保存导入链、当前hash及此限制。该审计还逐条核对34个请求、1322个候选和2831项issue/source/test证据，未见保存的生成输入混入评价标签；这属于源码调用链和artifact审查，并非完整系统调用隔离证明。

三方独立审核覆盖1538个实际候选并逐一核验引用SHA：root516，Python/TS510，Go512。评价器重新解析原报告、检查完整control和具名失败，不信任人工填入的运行布尔值。模型和生成器没有读取这些审核文件、census、隐藏verifier或参考补丁。

```bash
.venv/bin/python scripts/evaluate_relational_gap.py evaluate \
  --batch-root results/relational_gap_20260928/batch6 \
  --emitted-root results/relational_gap_20260928/batch6_emitted \
  --reviews results/relational_gap_20260928/batch6_reviews_audited.json \
  --output /tmp/relational-gap-batch6-recheck.json
```

结果为`batch6_evaluation.json`，运行/费用审计为`batch6_execution_audit.json`，生成/执行版本核验为`batch6_driver_archive_audit.json`。`all_17_targets_proven=false`。
