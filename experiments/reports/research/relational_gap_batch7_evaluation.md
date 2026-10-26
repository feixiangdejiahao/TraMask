> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_batch7_evaluation.md) · [旧路径映射](../../../results/path_map.tsv)

# Relational gap batch7：恢复完整源观察的离线消融

**全部17个trial完成执行，独立确认检出4/17：P2、N02、N07、N10。** batch6为3/17；本轮新增P2，来自恢复被原子化移除的character断言。17例全部检出的目标仍未达到；这是开发集上的结果，不能声称泛化或issue resolution rate已经提高。

## 消融改变了什么

从batch6实际offered的全部1322个source_q假设出发，统一恢复`atomic_neutralization`删除的原检查，并重放被该删除吸收的原输入编辑。其他输入、动作、exception guard及normal-result guard的源码编辑保持不变；恢复前置检查仍可能改变动态执行轨迹。恢复后按函数字节及支持代码去重为1305个新wholeq候选；17个重复父候选保留在来源映射中。没有未知恢复、按目标补入、按运行结果筛选或模型重试。

本轮排除LLM期望修订lane，新增模型调用和token均为0；batch6已经发生的34次调用和922718 tokens不能从整体探索成本中消去。每例最多128源候选，全部恢复后的候选直接发射，未再施加请求80KB上限。完整保留原检查仍然只是一种假设，不能据此证明原期望对新输入有效。

| 指标 | batch6全部候选 | batch7完整源观察 |
|---|---:|---:|
| 目标组合场景 | 6/17 | 6/17 |
| 场景且期望语义正确 | 4/17 | 4/17 |
| 正确关系、正确oracle、完整control通过、目标失败 | 3/17 | **4/17** |
| 额外命中固定census parent的检出 | 2/17 | 3/17 |
| 物化候选 | 1538 | 1305 |
| 其中source_q | 1322 | 1305 |
| 其中llm_q | 216 | 0 |
| 有运行索引 | 1531 | 1298 |
| 有具名结果记录 | 1404 | 1187 |
| 新模型调用 | 34 | 0 |

batch7的1305个“静态候选”是原offered源池的恢复快照，不是重新搜索完整8631候选池。其`test_hit=16/17`不能与batch6完整搜索池的17/17直接比较：两批offered源候选均为16/17，P5未含固定目标parent。`target_gap_detected`是主要缺陷检出指标；`all_dimensions_proven`额外要求固定parent，不能否定来自另一个有效历史测试的N07检出。

## P2提供的直接证据

候选`wholeq_5fdd37a2c67ad7a4a9ccb1bc`在`group_013`保留与batch6相同的输入和guards。batch6只检查key，检查成立，但character检查被移除；因此“期望正确”仍然“观察不足”，不是错误oracle。

本轮恢复原`character is None`后，key检查先通过，character实际为`a`而失败；两个required完整原control均通过，两阶段没有报告错误。这条新运行证据表明断言切片确实造成了一次漏报，不是手写新的目标断言或复用旧运行结果。

N02的八个异常消费/关闭候选、N07的七个不同起点重叠候选、N10的三个默认参数/条件必填候选也均以本轮新具名结果和完整control重新核验。历史版本或多个候选不会被当成多个trial。N07是[0,2)与[1,2)的不同起点重叠，不声称严格四端点交叉。

P3仍有错误的Ctrl期望，N05仍在宽度6时期待丢失最后r的字符串；恢复原检查不能纠正这些已经不适用的期望。其他例子仍缺少目标关系。

## 逐例结果

| Trial | 源候选 | 具名记录 | 目标场景 | 确认检出 |
|---|---:|---:|---|---:|
| P1 | 88 | 88 | 否 | 0 |
| P2 | 89 | 89 | 是 | 1 |
| P3 | 88 | 88 | 是 | 0 |
| P4 | 44 | 44 | 否 | 0 |
| P5 | 74 | 43 | 否 | 0 |
| P6 | 78 | 70 | 否 | 0 |
| P7 | 85 | 78 | 否 | 0 |
| N01 | 70 | 70 | 否 | 0 |
| N02 | 67 | 67 | 是 | 1 |
| N03 | 95 | 95 | 否 | 0 |
| N04 | 43 | 43 | 否 | 0 |
| N05 | 128 | 128 | 是 | 0 |
| N06 | 92 | 57 | 否 | 0 |
| N07 | 50 | 37 | 是 | 1 |
| N08 | 43 | 30 | 否 | 0 |
| N09 | 97 | 86 | 否 | 0 |
| N10 | 74 | 74 | 是 | 1 |

## 误报与执行限制

763个候选有有效具名失败，682个同时具有通过的完整control。其中19个确认为四个目标缺陷、26个确认为错误期望、637个仍unknown。审核不是随机或穷尽oracle审核，**不能把26与batch6的29比较后宣称误报率下降，也不能据此估计precision**。源码与旧行为不一致的失败、超时和编译失败都不是自动确认的缺陷。

219个执行组中，6个生成阶段有错误，3个control阶段有错误，2个超时。剩余编译阻塞为3组13个源候选，均同时影响原control；batch6的N08独立生成未使用绑定编译污染消失。P7有7个accepted候选未形成最终可执行artifact，因而1298个有运行索引。具名记录1187也包含不满足完整control条件的情况，不能当成有效目标覆盖。

本消融不是完全相同运行顺序的配对试验：新ID和恢复后轮转/去重改变了组内声明顺序。P6若干函数除名字外字节相同，具名数却从68变70，后续panic遮挡随顺序变化。因此总具名数或失败数的变化不能全部归因于恢复q。P2的同输入、恢复原character检查以及新具名失败/完整control证据是更直接的局部证据。

## 冻结、调度与复核

17个独立准备快照保存新ID、旧父ID列表、原prepare/accepted的SHA与复制的corpus/selection。29个声明driver文件、47个声明生成文件和单独resume调度脚本的当前hash均匹配，没有混合声明版本。这不等于完整传递依赖已事前冻结：`batch6_7_generation_boundary_audit.json`记录了12个未列入原声明清单的本地传递依赖；事后源码/Git一致性不能证明其运行时从未临时变化，也不能回填原冻结协议。

原调度在17例prepare/emit完成、零subject执行时停止；独立resume复用已有artifact，第一worker占用空闲slot，第二worker待batch6全部结束后加入同一固定registry队列。整个过程最多两个Docker容器，保留每phase240s上限，未重prepare、重物化或重跑已执行测试。最终全部219组control/generated报告完整，索引2270行；运行索引位于`batch7_resumed_pipeline/runs.json`。

三方独立审核精确覆盖1305个实际ID：Python/TS394、root446、Go465，所有引用SHA重新核验。评价器重新解析新运行报告；没有继承batch6的运行布尔结论。全部审核标签只在评价侧使用。本消融的研究动机来自此前开发集分析，并非盲选未见数据的实验。

```bash
.venv/bin/python scripts/evaluate_relational_gap.py evaluate \
  --batch-root results/relational_gap_20260928/batch7 \
  --emitted-root results/relational_gap_20260928/batch7_emitted \
  --reviews results/relational_gap_20260928/batch7_reviews_audited.json \
  --output /tmp/relational-gap-batch7-recheck.json
```

主结果为`batch7_evaluation.json`，费用与错误组为`batch7_execution_audit.json`，声明边界核验为`batch7_declared_freeze_audit.json`。`all_17_targets_proven=false`。
