# 补丁到观察路径：固定候选池评价协议

本轮先比较排序，再由独立评价端匹配历史见证。排序阶段不读取目标标签、oracle 回答、运行结果、隐藏测试或参考补丁，不请求模型、不执行被测仓库。结论只适用于现有候选池；排序命中不等于生成了正确断言或检出了缺陷。

固定输入由 `results/relation_search_20260930_finite_templates/paired_inputs_v3/protocol.json` 指定：`results/relation_search_20260929/candidate_inventory_v1/{case}/` 的 `corpus.json`、`frontend.json`、`source_pool.json`、`case.json`，全部 17 例、4,502 个候选，不再生成、删减或改写候选。候选程序采用原 `_program_edits` 视图，排除本项目后来生成的 oracle revision。

17 例均有 `data/relational_gap_v1/{case}/model.patch`，其 SHA 与 `case.json` 的提交补丁 artifact、`repository_provenance.patch_sha256` 一致。`repository/` 是记录的 base commit 应用该提交补丁后的文件；`trajectory.json` 是原 agent 可见历史，其与 issue 的现存文件 SHA 也逐例核对了原 artifact 记录。原材料获取入口 `scripts/prepare_relational_gap_cases.py` 只复制 issue、提交补丁和 trajectory，导出 base tracked files 加提交新增路径。不是参考实现。

| Case | 候选数 | 当前源码文件 | 历史源码版本 | 选中历史测试 / 当前测试 |
|---|---:|---:|---:|---:|
| N01 | 93 | 60 | 29 | 31 / 225 |
| N02 | 195 | 61 | 28 | 116 / 140 |
| N03 | 103 | 43 | 30 | 20 / 236 |
| N04 | 48 | 57 | 64 | 76 / 180 |
| N05 | 175 | 30 | 11 | 137 / 64 |
| N06 | 174 | 9 | 3 | 31 / 68 |
| N07 | 335 | 469 | 36 | 107 / 149 |
| N08 | 506 | 576 | 5 | 82 / 174 |
| N09 | 609 | 248 | 62 | 113 / 143 |
| N10 | 586 | 556 | 26 | 38 / 218 |
| P1 | 90 | 468 | 4 | 4 / 252 |
| P2 | 89 | 483 | 28 | 21 / 235 |
| P3 | 90 | 481 | 20 | 20 / 236 |
| P4 | 60 | 273 | 15 | 49 / 207 |
| P5 | 370 | 80 | 5 | 13 / 191 |
| P6 | 382 | 80 | 8 | 25 / 205 |
| P7 | 597 | 576 | 41 | 27 / 106 |

这里的“当前”是 `origin=repository`，“历史”是 `origin=trajectory`。测试数是已选的语法测试单元；既不是所有历史验证，也不是实测覆盖。源码有文件/字节预算，测试单元最多 256；历史会去重、恢复文件版本、重定位，Go 会重命名 globals，Python/TS 脚本可能被包装。准确来源在 `results/relational_gap_20260928/batch7/{case}/selection.json`，包含 `step_id`、`trajectory_source`、原路径、原 SHA 和 `relocated_globals`。全部提交补丁中的 Python/Go/TS 改动文件均已进入封存的当前源码，字节与本地候选 repository 相同；未入源码池的补丁路径是文档。不能依据历史 `written_path` 把旧实现当成当前补丁节点。

三个主臂均按全部原候选排序，每例预算 16，在全池排序前统一冻结规则：

1. `relation_search.semantic_selection.select`：现有 shape/family/seed 公平轮换。
2. `experimental.patch_observation_priority.select(..., mode='strict', budget=16)`：有限的返回参数投影路径排序。
3. 同一接口 `mode='may'`：保守路径模式，允许 opaque/loop/receiver effect 的候选按 may evidence 排序；不把这类证据称作证明。

两个新臂都保留完整候选：布尔优先分桶后，低优先/未知候选保持原 fair 相对顺序。有限的前 16 不保证未知候选得到名额，也没有固定探索配额。复杂源码全部 unknown 属于支持范围的负结果，不能从 17 例分母删除。

同时预声明另一个共同投影：三个臂都使用同一份旧 `singleton_oracle_slots.assertion_inventory` 源码资格，再取其排序中前 16 个可表达候选，记作 eligible@16。资格先独立封存；不能用新 helper 的 literal-only 资格替换。原 production impact 会自行筛资格，所以只能作附加参照，不能直接作为全池主对照。raw@16 与 eligible@16 的统计必须分开。

`scripts/census_patch_observation_priority.py` 在看答案前封存输入 SHA、源码和测试快照、共同资格、三个完整排序、raw/eligible 选择及未知事实。每例必须保留完整 ID 集合；解析未知不删候选，不靠模型输出或目标选择候选。补丁观察路径是 may evidence，原型的 value-return 路径不代表 heap/state、异常、callback 或调度依赖完整。

独立评价在 seal 之后才能读取此前封存的 17 例目标/已审组合测试。按候选 ID、原程序编辑和输入 SHA 匹配，报告 raw/eligible Witness Exposure@16、见证排名与原池覆盖；未匹配记 miss，不能回填旧 16/17。另报各类路径支持数、unknown 数、源码分析时间、前 16 中原断言可表达数。既有 oracle 正确率和实际缺陷检出结果可另列，但不能因为排序曝光便增加检出分数，也不能把没有新执行解释成新的误报/漏报改善。

这 17 条 trajectory 是既有开发集合，不是未见任务上的泛化实验。评价端须同时给出 trial 与独立 task 的分组结果，说明重复任务；这些分组不能参与排序或候选选择。

主 search 可复用 `scripts/run_relation_search.py:prepare` 的源候选视图和快照、`relation_search.oracle_evidence._modified_sources` 的修改后源码、`anchor_retrieval.index.Index` 的源解析，以及上述 `select` 入口。本轮不调用 `execute_relation_search`、feedback 或 semantic provider；若以后比较模型/执行，需保持同一 oracle 接口，并把格式失败、unknown、预算耗尽留在请求分母。
