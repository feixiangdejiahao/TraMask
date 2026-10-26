# 历史原型代码

本目录统一称为“历史原型代码”。原目录名是 `experimental/`。`experiments/` 保存实验设置和分析入口。`results/` 保存实际输出。三者按用途区分。

下表给出原型与实验主题的对应关系。一个实验主题可以比较多个原型。不要把原型版本数计作实验次数。

| 原型目录 | 方法含义 | 实验主题 |
|---|---|---|
| `test_edit_analogy_v02/` | 测试编辑类比 | [测试类比与生成](../experiments/test_analogy_generation/README.md) |
| `test_edit_analogy_allow_erasing_v02_01/` | 允许删除信息的类比对照 | 同上 |
| `statement_aligned_test_analogy_v03/` | 按语句对齐的测试类比 | 同上 |
| `balanced_literal_test_analogy_v04/` | 平衡字面量表示的测试类比 | 同上 |
| `unified_view_test_analogy_v05/` | 统一语法视图的测试类比 | 同上 |
| `helper_assertion_instances_v01/`、`helper_assertion_instances_v02/` | 辅助函数与断言实例 | 同上 |
| `assertion_window_generation/` | 断言上下文窗口 | 同上 |
| `test_edit_square_generation/` | 四组测试修改的类比 | 同上 |
| `observation_guided_test_analogy/` | 用观察位置选择测试类比 | 同上 |
| `test_action_and_oracle_transfer/` | 测试操作与断言的语义迁移 | [语义迁移](../experiments/test_semantic_transfer/README.md) |
| `oracle_value_analysis/` | 分析断言预期值 | [程序关系搜索](../experiments/program_relation_search/README.md) |
| `program_relation_search_demo/` | 程序关系搜索演示 | 同上 |
| `research_notes/` | 历史原型说明 | [研究记录](../experiments/research_history/README.md) |

根目录中的独立 `.py` 文件按功能命名。它们包含条件、赋值来源、断言和观察位置分析。新算法放在 `src/`。新实验输出放在 `results/<主题>/<运行名>/`。

Python 导入现在使用 `prototypes`。例如：

```python
from prototypes.statement_aligned_test_analogy_v03.generate import generate
```

旧目录不再保留。旧路径可通过 [映射表](../results/path_map.tsv) 查询。原始实现备份和导入修改清单见 [本次迁移记录](../experiments/maintenance/20261020_directory_rename/prototype_migration.json)。冻结实验中的旧模块名和源码校验值仍表示当时版本。

读取算法效果时，使用 [主要 pilot](../experiments/pilots/README.md)。原型演示和单元测试不代表 pilot 效果。
