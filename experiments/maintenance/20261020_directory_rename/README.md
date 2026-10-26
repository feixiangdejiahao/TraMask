# 2026-10-20 目录命名迁移

本次按用户要求移动实际目录。结果根目录只保留新名称。`experimental/` 改为 `prototypes/`，统一称为“历史原型代码”。

- [命名规范](../../NAMING.md)：目录用途、主题对应关系和文件名称。
- [完整路径映射](../../../results/path_map.tsv)：包含结果、实验主题和历史原型代码。
- [初始移动计划](plan.json)与[执行记录](operations.jsonl)：179 项结果、主题和文件移动。
- [原型迁移记录](prototype_migration.json)：15 项目录改名和 228 个 Python 文件的导入、路径修改。
- [原型文档更新](prototype_documentation.json)：四份说明中的命令地址和内部链接。
- [核验结果](verification.json)：文件内容、物理目录、链接、任务索引和单元测试。

原始实验记录和报告正文保持不变。报告阅读副本位于 `experiments/reports/`。其链接使用新地址。冻结记录中的旧地址通过映射工具解释。

`before_prototype_imports/` 保存导入修改前的源码。它用于核对改名，不代表整轮实验的完整复现环境。已有运行内的实现快照继续保留。

完整单元测试有 5,120 项通过、6 项跳过，以及 1 项既有失败。失败测试检查旧 provider 的请求构建代码。测试、审计器和 provider 均与 Git HEAD 一致。使用 HEAD 的原始源码可复现同一失败。详见 [测试输出](unit_tests.log)和[原版本复现记录](preexisting_test_failure.json)。

本次未调用模型，也未重跑 benchmark。
