> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/owner_prefix_slice_20260929.md) · [旧路径映射](../../../results/path_map.tsv)

# Go owner prefix 的有界构造候选

实现位于 `experimental/owner_prefix_slice.py`，没有改动冻结的生成器。

原生成器把供体对象创建之后、所需值产生之前的所有操作搬过去。这能保留写入、提交等状态前提，也会搬入与新构造无关的检查；检查本身可以阻塞或失败。这里增加一个候选，不覆盖完整前缀候选。

核心是从待搬运表达式反向找 reaching definitions，找到调用接收者及其局部对象，再保留这些对象构造之后的相关调用。调用可以嵌在检查里，也可以通过实参接收对象；因此不依赖 `Set`、`Apply`、`Close` 或断言库名称。读取所需值之后的资源操作同样保留。直接别名、元组返回值的后续检查、操作输入的前序定义也进入闭包。

构造前，同一外部 owner 的调用不能仅靠变量依赖判定无关。如果提供 Go 源码，原型把同名方法体中可见的 receiver 字段写作为保留证据；这只是 may-write 证据，不是假装已经解析动态类型。同名方法误匹配最多增加保留操作，方法体中没有直接写入绝不等于 pure。其余构造前调用可在新候选中移除，但每一处都会记录 `preconstruction_owner_effect_unknown`。

这**不是 sound slicing，也不是语义等价变换**。它是基于局部对象闭包的有界新构造，是否符合任务前提、断言是否有效仍须独立检查。未知堆别名、全局状态、未展开调用效应没有被证明完备。分支、循环、并发、defer、闭包、间接指针写等直接返回 unknown，不生成伪装确定的切片。

`slice_prefix(prefix, binding, sources=...)` 返回逐句原 prefix byte span、保留/移除理由、方法体写入位置以及 unknown；`propose_candidate(candidate, sources=...)` 返回独立新候选及分析结果，保持所有其他 edits，移除继承来的 equivalence key。

验证包括 14 个测试：任意 API/变量改名、多个对象、实参传递、嵌套调用、前序定义、双向直接别名、tuple error 检查、不支持状态。可执行 Go 负控中，`Arm` 在 child 构造之前建立必需状态；删去它会真实 panic。方法通过 receiver 写证据保留它，同时保留 Add、Commit、Read、Retire 等状态操作，新的程序实际运行成功。缺少 `Arm` 方法体时明确报告前提 unknown，不能据此声称缺陷已经被证明。

N08 开发例子产物在 `results/relation_search_20260929/owner_prefix_slice_v1/N08/`：输入来自完整 source corpus 和现有 source pool；新候选 `04e6ed47ff5921a625aa` 保留 6 条构造/状态语句，移除 3 条构造前检查并标记 4 项 unknown。该原型任务尚未在 N08 repository 执行候选。文件和输入 SHA 记录在 manifest 中；没有使用模型、隐藏 verifier 或参考补丁。
