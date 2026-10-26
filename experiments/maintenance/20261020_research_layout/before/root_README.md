# 程序分析辅助的组合测试

本仓库保存组合测试研究、测试增强原型及实验依据。2026-10-07 已按主题归拢历史实验入口，并归档 120 份历史方案文档。新算法使用独立的源码和测试目录；现有原型仍可通过原入口使用。

先看 [研究报告](docs/README.md)，再按需查看 [实验材料索引](experiments/index.html)。索引支持按日期、实验名和文件名筛选。

## 目录分工

| 目录 | 用途 |
|---|---|
| `src/augmentation/` | 程序关系与语义区分驱动的测试增强原型。包含提取、筛选、模型生成和隔离执行。 |
| `tests/augmentation/` | 新算法的测试。其余 `tests/` 文件验证既有原型。 |
| `research_tools/` | 当前材料提取和模型接口原型。 |
| `experiments/<主题>/research/` | 历史方案文档，以及指向冻结记录的分组链接。新实验记录也放在这里。 |
| `experiments/<主题>/results/` | 指向历史运行结果的分组链接，以及新实验的运行目录。此目录不进入 Git。 |
| `experiments/maintenance/` | 仓库整理的迁移清单、原文备份和校验记录。 |
| `scripts/` | 既有运行、审查和报告生成入口。 |
| `data/` | 多个实验共用的任务、仓库及输入材料。 |
| `evaluation_assets/` | 独立评价使用的材料。 |
| `docs/` | 可直接阅读的 HTML 报告和论文演示材料。 |
| `configs/`、`vendor/` | 既有执行配置和本地复现依赖。 |
| `research/`、`results/` | 保留冻结记录和结果的原位置。已归档方案的旧路径为兼容链接。 |

旧算法模块保留在 `anchor_retrieval/`、`combination_testing/`、`generic_composition/`、`relational_gap/`、`relation_search/` 和 `experimental/`。这些模块之间存在导入依赖。此次整理保留它们的位置和内容，避免修改已冻结实验的实现。新算法应放入 `src/`，按需复用其中的功能。

部分实验凭据严格比较真实绝对路径，仅保留旧路径符号链接仍会导致验证失败。因此，301 项冻结结果、JSON 记录和目录树保留原位置；`experiments/` 提供按主题分组的入口。新实验可以直接使用新的目录结构。

## 当前研究入口

- [改进算法实现与本地验证](docs/augmentation_implementation_v2_20261008.html)：说明联合条件、原测试范围、按需查阅材料和执行反馈的实现。区分代码验证、真实任务提取检查与尚未运行的模型效果评价。
- [六条任务诊断对照](docs/augmentation_diagnostic6_20261008.html)：已完成原输入、人工材料、程序条件和执行反馈四组实验，并逐项分析材料差异。单列改变候选问题的补充检查及技术补跑，提出程序分析修改依据。
- [30 条任务 pilot：漏检与补测失败的原因](docs/augmentation_pilot30_diagnosis_20261008.html)：复核 23 个参照目标的原候选、模型输入、答复和测试。解释仅命中 T24 的原因，并提出改进算法与诊断对照。没有新模型调用或被测程序执行；不改变当前评估标签。
- [30 个 trial：从失败测试与补丁差异推导组合缺口](docs/augmentation_pilot30_reverse_20261008.html)：当前主报告。逐项比较原补丁与 gold，并回查原验证。合并新推导与旧记录中的有效目标后，确认 23 项组合目标，涉及 18 条任务。原方法检测、生成各命中 1 项，漏检 22 项。其中 13 项直接关联本轮选定的 benchmark 失败。benchmark 用于定位，不作为额外准入条件。结论主要来自静态判断，没有测量修复后的 resolution rate。[当前评估数据入口](experiments/relation_distinction/results/pilot30_20261007_v1/active_evaluation.json) 指向此版；原实验记录保持冻结。
- [旧 41 项历史目标的静态筛选附录](docs/augmentation_pilot30_static_20261008.html)：17 项符合原补丁失败、gold 通过；6 项原补丁已满足；14 项 gold 也未满足；4 项待定。原先 28 个待定目标已逐项处置。此集合与主报告分别计数。
- [211 条失败记录的完整分析](docs/deepswe_failure_manual_20261006.html)。
- [单关系与多关系缺口统计](docs/combination_relation_census_20261007.html)。
- [自动测试增强 pilot](docs/automatic_augmentation_pilot_20261005.html)。
- [手选材料 pilot](docs/trajectory_gap_pilot_20261005.html)。
- [自动提取原型](research_tools/automatic_augmentation_extract.py)。
- [新算法入口](src/augmentation/__main__.py)、[联合条件搜索](src/augmentation/joint.py)、[有预算限制的模型流程](src/augmentation/agent.py)。

上述报告保留各自的实验范围和限制。验证缺口不等于 patch 存在缺陷，历史最好结果也不代表新算法的效果。

## 使用新算法

输入仓库必须已经应用待提交的 patch。算法读取该仓库、公开需求、patch 和可选的公开 trajectory。它不读取人工缺口标签或 benchmark 的隐藏验证结果。

程序分析先组织“联合条件、相关操作、观察结果”。它连接数据流、控制流、可能的共享状态及声明约束。它同时保留观察发生的阶段。候选可以跨越多个函数和关系。调用深度、关系数量和条件维数分别计数。

每一行原测试证据对应一次入口调用。该行保留参数、对象绑定、操作路径和断言。程序不会合并不同调用来宣称联合检查已存在。未知输入、可能的提前退出和未知执行状态均单独保留。一个具体输入已有断言，不表示所有组合都经过验证。

模型收到局部证据后，判断需求是否要求该组合。它可以修正或否定候选，再生成补测。`generate` 保留单次调用方式。新增的 `agent` 允许模型查阅相关代码、原测试、关系和历史，并根据执行反馈修改测试。候选、测试失败和已确认缺陷分别记录。

程序分析发现已有联合结构证据时，会保留对应的执行核查项。模型先检查已有测试是否有效、是否在最终 patch 上运行。工具不会把“源码中有测试”直接判为“验证已完成”，也不会因执行状态未知就要求重复生成测试。

在仓库根目录执行以下命令。将大写占位内容替换为实际路径或候选 ID。

```bash
PYTHONPATH=src .venv/bin/python -m augmentation prepare \
  --repository COMPLETED_REPOSITORY \
  --patch MODEL_PATCH \
  --issue PUBLIC_REQUIREMENT \
  --trajectory TRAJECTORY_JSON \
  --output experiments/relation_distinction/results/RUN/prepared.json
```

`--trajectory` 可省略。提供 `--base-repository BASE_REPOSITORY` 后，算法还会检查原版本中消失的已解析调用关系。`prepared.json` 保存候选、测试范围、源码校验值、相关历史及分析限制。默认调用深度为 6，联合条件搜索上限为 3，保留候选上限为 80。分别使用 `--max-depth`、`--max-order` 和 `--max-regions` 调整。达到上限时，程序明确记录省略范围。

默认使用 `--analysis-mode joint`。`--analysis-mode legacy` 保留旧候选搜索和请求形式，便于实现对照。它使用当前解析器，不代表冻结历史运行的逐字复现。

先查看一个候选对应的完整模型请求。此命令不访问 provider。

```bash
PYTHONPATH=src .venv/bin/python -m augmentation request \
  --prepared experiments/relation_distinction/results/RUN/prepared.json \
  --candidate CANDIDATE_ID \
  --output experiments/relation_distinction/results/RUN/request.json
```

调用 DeepSeek 接口。接口使用本仓库 `.env` 中的 provider 配置，并请求 `deepseek-v4-flash`。日志另存 provider 实际返回的模型标识。下面的单次调用入口在省略 `--candidate` 时处理全部候选；重复此参数可选择多个候选。

```bash
PYTHONPATH=src .venv/bin/python -m augmentation generate \
  --prepared experiments/relation_distinction/results/RUN/prepared.json \
  --candidate CANDIDATE_ID \
  --output experiments/relation_distinction/results/RUN/generation
```

生成目录保存请求、provider 原始响应、解析后的 `CANDIDATE_ID/assessment.json` 和汇总 `results.json`。格式错误保持为错误，不转成“没有缺口”。测试修改只允许新增测试文件或在已有测试文件末尾追加代码。

需要按反馈迭代时，使用以下入口。

```bash
PYTHONPATH=src .venv/bin/python -m augmentation agent \
  --prepared experiments/relation_distinction/results/RUN/prepared.json \
  --candidate CANDIDATE_ID \
  --command '["/ABSOLUTE/PYTHON","-m","pytest","-q","{test_paths}"]' \
  --max-rounds 3 --max-feedback-rounds 2 --max-executions 2 --max-candidates 8 \
  --token-budget 100000 --max-output-tokens 8192 \
  --output experiments/relation_distinction/results/RUN/agent
```

每个候选最多用 3 次模型调用查阅和生成首版测试。首次生成后，另有最多 2 次调用检查反馈和修正。提前生成时，程序不再使用剩余查阅次数。每个候选最多执行测试命令 2 次。全部候选共享 token 预算。程序预留一次反馈调用的额度；总预算不足时仍会停止，并保留待定状态。每次调用都会计入预算，包括格式错误和未完成答复。缺少 provider 用量时，程序按请求字节数及输出额度保守记入预算。重复相同查询或测试时，程序停止该候选。

省略 `--candidate` 时，agent 最多处理 8 个候选。程序按需求相关性、具体条件、修改对后续操作的影响和证据重复程度选择候选。`protocol.json` 保存各项评分。提取阶段也使用此排序。省略 `--command` 时，agent 只检查材料和生成测试。agent 的一次执行只运行选定测试；独立 `execute` 命令仍默认分别运行原测试和补测。

v3 将条件、具体操作和可能的结果区别放在一起，并保留源码位置。测试查询支持路径、目录、行号和分页。`append` 表示在完整文件末尾追加代码，提示明确说明该位置的作用域。模型可以选取程序提供的条件目标，也可以调整条件取值。生成后，程序重新分析新增测试，并在 `condition_check.json` 中记录是否保留目标条件。它不合并不同调用，也不借用追加文件中的旧测试来证明新测试有效。无法确定共享对象或异步阶段时，结果仍为未知。条件保留不等于断言正确，也不等于发现补丁错误。

[v3 实现与验证说明](docs/augmentation_v3_implementation_20261009.html) 记录本次改动和回归结果。上一轮 30 项实验使用的源码已保存在该实验的 `implementation_snapshot/` 中。旧运行脚本仍检查原源码散列；不要用修改后的源码覆盖旧协议或续写旧实验。

执行时，调用方明确指定测试命令。命令必须是 JSON 参数数组。`{test_paths}` 展开为本次测试路径。模型响应和历史命令不能决定执行命令。

```bash
PYTHONPATH=src .venv/bin/python -m augmentation execute \
  --prepared experiments/relation_distinction/results/RUN/prepared.json \
  --response experiments/relation_distinction/results/RUN/generation/CANDIDATE_ID/assessment.json \
  --command '["/ABSOLUTE/PYTHON","-m","pytest","-q","{test_paths}"]' \
  --output experiments/relation_distinction/results/RUN/execution
```

执行目录必须位于被测仓库之外。工具分别在仓库副本上运行原测试和补测，保留命令、返回码及完整输出。它不修改输入仓库。副本不包含 `.env`、`.venv` 或外部符号链接。请指定已有的测试环境。仓库副本用于隔离文件修改，不提供容器级隔离。

选测问题使用独立的执行结果。若选中的测试只存在于历史临时脚本中，执行器会要求先将该脚本明确恢复为仓库中的测试文件。当前执行器不会自动重放历史命令。

Python 执行反馈还记录选定源码行、条件值、对象标识和调用标识。重复调用分别记录。未观察到后续操作可能来自错误的提前退出，不能直接解释为测试无效。Go 和 TypeScript 目前只返回测试命令输出，尚未提供同等的运行时条件记录。

当前语法层支持 Python、TypeScript 和 Go，并读取 YAML 声明。新增分析包括局部默认值传播、索引存在性、循环分配、指令生成与执行分派、字段读写及后续消费者。函数调用可以跨越多条关系；条件组合仍采用有界搜索。类型和字段匹配只产生可能关系。程序尚不能证明复杂别名、异步先后顺序或任意分支可达性。Rust/C++ 尚无语法支持。

新增测试检查算法行为，并用可控的模型替身检查生成接口。执行测试会实际运行小型自建 Python 项目。这些检查不评价 DeepSeek 的生成效果，也不代表 benchmark 的缺口召回率。

本次改进的验证记录见 [实现报告](docs/augmentation_implementation_v2_20261008.html)。六条诊断任务只检查自动提取和请求构建；这不等于正确检测或成功补测。旧版的 N04、N09 提取及测试记录仍保存在 [2026-10-07 实现记录](experiments/relation_distinction/research/implementation_20261007.json)。

## 后续实现和实验

1. 在 `src/` 中实现新算法。`pytest.ini` 已将该目录加入测试导入路径。
2. 在 `tests/augmentation/` 中添加相应测试。
3. 为新实验建立 `experiments/<主题>/research/` 和 `experiments/<主题>/results/<运行名>/`。
4. 在研究记录中写明输入、配置、源码版本和结果路径。每次运行使用新目录，保留已冻结结果。
5. 继续使用现有脚本时，可以沿用旧路径；新增材料使用新的主题目录。

本次整理没有调用模型或重跑 benchmark。`.env`、`.venv`、本地依赖和用户编辑器设置保留原样。`.env` 不进入 Git。

## 验证与维护

运行现有单元测试：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests -q -p no:cacheprovider
```

只运行新算法的测试：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/augmentation -q -p no:cacheprovider
```

实验索引读取 `experiments/catalog.json`。更新目录清单后，可重新生成 HTML：

```bash
.venv/bin/python scripts/build_experiment_index.py
```

清理的内容仅包括可再生成的项目 Python 缓存、pytest 缓存、`docs/build/` 和两个空目录。历史运行结果保留，未将旧实验或负结果当成无效数据删除。

具体路径变化见 [迁移清单](experiments/maintenance/20261007/migration.json)，检查结果见 [整理后校验](experiments/maintenance/20261007/verification.json)。旧版仓库说明保存在该目录的 `before/` 中。[环境安装记录](ENVIRONMENT.md)仅用于查询历史安装方式。
