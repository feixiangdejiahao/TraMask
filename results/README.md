# 实验结果

本目录统一保存实验的实际输出。先打开 [主要 pilot](../experiments/pilots/README.md)，再查看对应运行的数据。全部运行见 [结果目录清单](../experiments/INVENTORY.md)。

结果使用 `results/<主题>/<运行名>/`。`experiments/<主题>/` 使用相同主题名，保存设置、分析和入口。它的 `results/` 链接指向这里。同一结果不重复计数。

目录、运行版本和文件的规则见 [命名规范](../experiments/NAMING.md)。旧的根目录名称已移除。查询旧位置时，使用 [路径映射](path_map.tsv) 或运行 `python3 scripts/result_paths.py OLD_PATH`。

本次整理移动了数据位置。原始实验 JSON、执行日志和报告原文保留。旧记录中的路径表示记录生成时的位置。读取时转换路径；不要改写冻结记录。
