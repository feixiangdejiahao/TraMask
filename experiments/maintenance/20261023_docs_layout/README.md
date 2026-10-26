# 2026-10-23 文档整理

本次统一 31 个文档文件名。13 份保留为当前阅读入口，18 个移入 `docs/archive/`。旧版评价、已被后续版本修正的实现说明和前期汇报分别注明归档原因。较早但仍有独立参考价值的 pilot 继续保留。

- [文档目录与命名规则](../../../docs/README.md)
- [归档依据与后续阅读](../../../docs/archive/README.md)
- [旧路径映射](../../../docs/path_map.tsv)
- [移动计划](plan.json)与[执行记录](operations.json)
- [内容、链接和构建检查](verification.json)
- [211 项双语报告检查](portable_report_audit.json)

全部 HTML、PDF 和 LaTeX 文档保持原始字节。原文件通过移动保留。`before/` 保存整理前的文档、配置和入口。`before_code/` 保存更新路径前的脚本。原始实验记录未被改写。

根 README 现在优先列出当前报告、主要 pilot、轨迹分析和当前实现。旧报告通过归档目录进入。报告阅读副本的本地链接使用新名称；归档副本增加归档原因和后续阅读提示。双语独立报告的阅读副本与原文逐字节一致。

报告生成脚本和 LaTeX Makefile 已使用新路径。本次只检查 LaTeX 构建命令，保留原 PDF。没有调用模型，也没有重跑 benchmark。

执行 `python3 scripts/build_experiment_index.py` 会更新报告阅读副本、文档目录和实验索引。执行同一命令并加 `--check` 可检查入口是否需要更新。
