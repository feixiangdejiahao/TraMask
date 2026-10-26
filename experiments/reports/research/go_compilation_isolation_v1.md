> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/go_compilation_isolation_v1.md) · [旧路径映射](../../../results/path_map.tsv)

# Go 候选编译隔离

Go 的测试名称过滤与独立测试进程都发生在整包编译之后。同组内一个生成测试删掉必需实参，会让同包其他合法候选一起无法运行。进程隔离能隔离挂起和进程状态，不能隔离同一编译单元里的类型或参数错误。

`scripts/execute_relation_search.py` 新增可选 `--isolate-go-compilation`。Python 调用接口为 `emit_batch(... isolate_go_compilation=True)`。启用时，所有 Go 候选分别使用独立的源码快照和 emission group，每组最多一个候选；原始对照仍先在独立的未修改源码快照中运行。规则不识别案例、API、已知目标或模型修订类型。其他语言不受影响，省略选项时保持旧分组行为。

请求中的 `group_size` 保留用户配置，`effective_group_size` 记录实际值；stage 同时记录隔离开关，manifest 和 execution lanes 记录 `compilation_isolation`。因此改变编译边界不能静默复用旧分组的 checkpoint。运行时仍使用已有 Go runner 和按测试归一化流程；非法候选保持 `not_run / compile_error`，不会被算成检出缺陷。

## 真实 Go 样例

样例中的不完整函数 `combine(left, right)` 总是返回 `left`。原测试检查 `combine(2, 0) == 2`，可以通过。加入两个候选：

- 非法候选：调用变为 `combine(2)`，缺少必需参数。
- 合法检错候选：检查 `combine(2, 3) == 5`，能暴露忽略第二个参数的实现错误。

`tests/test_go_compilation_isolation.py` 使用真实 Go 编译、测试二进制、phase runner、结果归一化和 feedback collection；仅把 Docker transport 替换为本地仓库副本。测试验证：

| 情况 | 原始对照 | 非法候选 | 合法检错候选 | feedback 认定已执行候选 |
|---|---|---|---|---|
| 默认同组 | 通过 | 编译失败，未执行 | 被同组编译错误阻挡，未执行 | 无 |
| 编译隔离 | 各组均通过 | 编译失败，未执行 | 实际执行并断言失败，无基础设施错误 | 仅合法候选 |

此外验证了原始编译日志保留、非法候选没有伪造失败计数、同策略可恢复、切换策略拒绝复用旧结果，以及选项不会拆分 Python 候选。

## 开销边界

使用本机 Go 1.18.1，关闭依赖下载、预热标准库编译缓存，顺序执行一次所得：

| 指标 | 默认同组 | 编译隔离 |
|---|---:|---:|
| replay 调用 / 源码快照组 | 1 | 2 |
| control + generated 编译命令 | 2 | 4 |
| 编译耗时合计 | 0.530 秒 | 1.160 秒 |
| phase 耗时合计 | 0.731 秒 | 1.561 秒 |
| runner 总耗时 | 0.764 秒 | 1.609 秒 |

这是一次小型正确性实验，时间受缓存和运行顺序影响，不是性能基准。实际 Docker 启动开销没有测量；当前 replay 架构每组启动一次容器，因此容器数与组数同步增加。原来每组最多 `g` 个候选时，在单一原分组内改为逐候选编译，最多将组数、原始对照编译和容器启动数放大 `g` 倍。这里采用简单、确定性的独立快照，不增加编译失败后递归拆分的恢复状态。

可复现命令：

```bash
.venv/bin/python -m pytest -q tests/test_go_compilation_isolation.py \
  --basetemp results/relation_search_20260929/go_compilation_isolation_toy_v1
```

首次执行证据位于该目录下 `test_invalid_sibling_cannot_pr0`，包含 prepared/emitted/executed、编译输出、独立测试报告，以及 `compilation_isolation_comparison.json`。重跑时请使用新的 `--basetemp` 目录，以保留已有审计材料。本改动未改变已冻结主实验的工作树或产物，也未重新解释其过去的未执行记录。
