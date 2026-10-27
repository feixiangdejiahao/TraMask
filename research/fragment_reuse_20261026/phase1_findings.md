阶段 1 的主要发现是：**多数目标测试缺少的因素，在 Agent 的执行历史中能找到原样片段或相关组件；正确的 Check 比 Context 更难直接复用。** 本轮已完成预先选定的 88 条 combination gap 轨迹的手工分析，覆盖 58 个任务。[完成记录](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/completion.json)

相对于每例选定的原测试，共识别出 125 个需要补入的因素，原测试已经具备的因素不计入这个数量。其中，40 个因素本身已在历史测试中执行过，66 个能找到相关的已执行组件，合计 106 个有历史复用依据。[统计汇总](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.json)

| 历史来源 | 因素数 | 研究含义 |
|---|---:|---|
| Exact | 40 | 所需语义条件已完整出现在执行历史中，可据此提出迁移候选。 |
| Related | 66 | 历史提供了相关组件，仍需组合条件、映射对象或推导联合关系。 |
| Absent | 13 | 历史中没有找到能提供该条件的片段，需要补充新因素。 |
| 未定（null） | 6 | 现有证据不足以判定该因素的历史来源。 |

按轨迹汇总，38/88 例至少有一个需要补入的因素已在历史中完整出现（Exact），71 例的全部补入因素都有 Exact 或 Related 来源。这里更普遍的情形是“已有相关材料，需要建立正确关系”：50 例至少包含一个 Related 因素，21 例的补入因素全部为 Exact。[逐例统计](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.csv)

| 轨迹分组 | 数量 | 含义 |
|---|---:|---|
| 全部 Exact | 21 | 每个补入因素都能找到已执行的完整语义片段。 |
| 全部 Exact/Related，且包含 Related | 50 | 全部因素都有历史依据，其中一部分需要语义映射或组合。 |
| 包含 Absent，且没有未定因素 | 11 | 至少一个所需因素需要从历史以外补充。 |
| 包含未定因素 | 6 | 至少一个因素的来源尚不能确定。 |

这四组互斥。未定组中的 S048 同时含有 Absent，因此全样本中含任意 Absent 的轨迹共 12 条。[分组与交叉统计](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.json)

**缺口更集中在如何判断结果正确，而不只是如何建立执行环境。** 125 个因素中，Check 有 49 个，Context 有 39 个，Trigger 有 37 个。Context 中有 25 个 Exact，Check 中只有 2 个；36 个 Check 只能找到 Related 组件，另有 6 个 Absent、5 个未定。相比之下，Context 只有 2 个 Absent，没有未定项。[因素角色统计](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.json)

| 因素角色 | Exact | Related | Absent | 未定 | 合计 |
|---|---:|---:|---:|---:|---:|
| Trigger：输入与目标操作 | 13 | 18 | 5 | 1 | 37 |
| Context：执行前的状态与环境 | 25 | 12 | 2 | 0 | 39 |
| Check：观察位置与正确预期 | 2 | 36 | 6 | 5 | 49 |

这使方法设计有了更明确的重点：环境和状态片段可以提供较直接的迁移起点，而检查逻辑常常需要把历史中的正确规则应用到新的联合情形。后续候选构造因此需要同时考虑 Setup 迁移和 Check 修订。例如，S065 的历史测试要求 `Result.lash` 返回回调产生的新容器；将这一规则用于 `Validated.lash`，需要修改原测试的错误预期，并完成两种容器之间的语义映射。[S065 分析](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S065.json)

手工提出的构造方案以 2 个来源测试单元为主，共 58 例；使用 3 个单元的有 11 例，4 个单元的有 2 例，1 个单元的有 13 例，另有 4 例未定。来源单元数包含原测试，与迁移条件数不同：一个来源测试可以提供多个条件。这些数量描述手工构造规模，后续实验将检验相应组合能否恢复错误检测。[构造规模统计](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.json)

**历史材料也不总是分散的。** 对本轮选定缺陷，S008、S037、S045、S079 共 4 例已经执行过包含所需条件与正确断言的完整测试，它们都在上述 21 例全部 Exact 的分组中。S037 后来把预期求值次数从 1/2 改成 2/3；S045 在被调用函数中加入等待，改变了能暴露错误的时序。这些案例表明，遗漏也可能来自完整测试被弱化或未被继续采用。因此，后续需要把“恢复完整历史测试”作为单独的比较基线，再判断跨测试片段组合带来的额外价值。[完整 witness 统计](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.json) · [S037](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S037.json) · [S045](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S045.json)

88 条轨迹涉及 58 个任务，同一任务的多次尝试保留为不同轨迹。将同一任务下的全部补入因素合并后，58 个任务分别为：12 个全部 Exact，34 个全部 Exact/Related 且包含 Related，9 个包含 Absent，3 个存在未定因素。已知案例另行标注：S001 为此前的校准案例，S073、S074 属于已知 T13；其余 85 条轨迹覆盖 56 个任务。[任务汇总与已知案例](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.json)

阶段 1 回答了“历史里有什么可复用材料”。第二阶段已启动 88 例盲化生成，接下来要检验算法能否找到并组合这些材料，使测试在错误 Patch 上失败、在正确实现上通过，并揭露同一个任务缺陷。
