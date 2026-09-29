# 不改主实验的 Go 编译失败补执行

`scripts/replay_go_compile_failures.py` 提供两个阶段。`plan` 只读扫描指定 campaign 已封存的 `executed/runs.json`：只选择生成阶段 Go package 明确为 `compile_error`，且原 manifest 含多个候选的组。它纳入该组全部原候选，不识别 oracle 类型、目标 ID、API 或 evaluator 真值，也不调用模型。未封存轮次、单候选组、其他语言、仅测试失败或通过的组均不纳入。

确定性 plan 按原运行/manifest 路径排序，记录原始候选 JSON、corpus、case、selection、registry、候选补丁、依赖 package inventory、失败报告和源码材料的 SHA。原 Docker transport 的 image、image ID、base commit、候选补丁 SHA 与当前 registry 核对。只读必要的执行材料，不读取模型问答或评价标签。

`execute` 只消费已冻结 plan，将原 raw candidates 原样复制到新的 prepared 目录，使用原 timeout 和 replay registry，调用 `emit_batch(isolate_go_compilation=True)` 与已有 `run`。除候选 JSON/源码输入身份外，重新物化后还核对每个候选及原始对照的 Go 函数体 SHA。新报告必须位于原 campaign 之外；原始编译错误保留，新运行记录和成本另存。

工具保留完整编译日志，非法候选继续报告未执行。补执行成功运行的断言失败不是自动认定有效组合缺陷：仍需 evaluator 检查原始对照、oracle 正确性及缺陷见证。该结果是执行可靠性补充，不能回填成原冻结主臂的检出结果。

## 本地验证

真实 Go toy 使用一个非法缺参候选和一个合法检错候选。原组两者都被编译错误阻挡；补执行后原始对照均通过，合法候选实际断言失败，非法候选仍为编译错误。测试同时确认：

- plan 重复生成完全一致，原组全部候选原样重放。
- 修改源补丁后，在建立补执行输出和运行任何 transport 前拒绝执行。
- 原 campaign 所有文件的 SHA 完全不变。
- 成功补执行可恢复，恢复不再调用 transport。
- 未封存轮次、单候选、非 Go、无编译错误的组被排除。

新增 4 项测试，连同此前编译隔离的 2 项，共 **6 项通过**。Go 编译、测试二进制、phase runner、归一化和 checkpoint 都真实运行；Docker transport 用本地仓库副本替换。证据位于 `results/relation_search_20260929/go_compile_replay_toy_v2`。

## 当前固定主臂的补执行计划和成本

初次只读扫描 `results/relation_search_20260929_v3/uniform_fresh_impact_v3` 已完成轮次，得到 24 个组、134 个候选。最终冻结 ready plan 时 N08 也已完成，因此统一条件扫描扩展为 **35 个组、208 个候选**：N05 为 5 组/69 候选，N07 为 19 组/65 候选，N08 为 11 组/74 候选。没有按案例选择；ready plan 固定后不再追随主臂新增轮次。尚未完成的轮次不被推断为失败。

原 24 组实际记录的 control/generated phase 总耗时为 313.974 秒。将每组原实测 phase 时间乘以该组候选数，134 个候选的逐候选重放基线为 1,267.387 秒，约 21.1 分钟。最终 35 组原 phase 合计为 **803.118 秒**，208 候选的重复 phase 成本为 **4,639.356 秒，约 77.3 分钟**：N05 为 312.987 秒，N07 为 954.400 秒，N08 为 3,371.969 秒。这包含原实际编译和对照成本，不是 toy 外推。

该基线不是上界：原生成阶段在编译错误处停止，隔离后合法候选新增的测试运行时间无法由原失败推断；原 runner 也未记录每个容器的启动/还原总 wall。因此不能把上述基线写成保证完成时间。最终全部候选 phase timeout 累加的粗上限为 74,880 秒；实际执行应由已有 `run_timeboxed_command.py` 以 UTC 16:15 的绝对 deadline 监督，并只增加一个 Docker worker。

`run` 每完成一个 singleton artifact 就写出 runs/summary，完整容器保留 `execution.json`；中途停止后已完成项仍可复核。原 group 的剩余项恢复时复用这些记录，当前工具不引入新的调度器或递归拆分机制。

最终计划位于 `results/relation_search_20260929_v3/go_compile_failure_supplement_v1/plan_ready.json`。本交付没有执行真实 Docker，等待 root 核对 ready 文件后启动既有 supervisor。
