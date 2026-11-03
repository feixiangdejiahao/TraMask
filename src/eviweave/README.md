# EviWeave 学术原型

当前实现步骤 A/B/D/F：在 replay 中保存历史版本及实际输入输出，将材料整理为候选列表，定位匹配点，再恢复对应历史执行环境中的程序切片与轨迹关系。[完整架构与后续实现顺序](ARCHITECTURE.md)覆盖设计稿 A–L。

## 单独使用 replay

从仓库根目录运行：

```bash
PYTHONPATH=src .venv/bin/python -m eviweave.replay \
  --case-id S030 \
  --input-directory results/failure_analysis/deepswe_failed_trials_n211_20261006/trials/httpx-multipart-response-parsing__pAv36Bv \
  --out results/behavioral_masking/<new-run>/S030
```

宿主使用 Python 3.11+、Docker 和 Git。输入为原始 `instruction.md`、`task.toml`、`model.patch`、`trajectory.json`。Image 来自 task 配置且需已在本地；短 base commit 在输入入口解析，也可用 `--base-commit` 指定完整提交号。

replay 按原命令和顺序执行全部已观测调用，明确标为未执行的调用被排除。执行完成后建立 checkpoint，并在副本中比较 HEAD、index、实际文件与独立构建的 base + Patch。它只依赖标准库、Docker 和 Git，可以将 `eviweave/` 整包复制到其他 Python 目录后独立使用。

## replay 时同步采集版本与输入输出

```bash
PYTHONPATH=src .venv/bin/python -m eviweave collect \
  --case-id S030 \
  --input-directory results/failure_analysis/deepswe_failed_trials_n211_20261006/trials/httpx-multipart-response-parsing__pAv36Bv \
  --out results/behavioral_masking/<new-run>/S030
```

```python
from eviweave.replay import load_case, replay_case
from eviweave.collection import collect_tests

case = load_case("S030", input_directory)
result = replay_case(case, input_directory, replay_output)  # 独立 replay
result = collect_tests(case, input_directory, collected_output)  # replay + 步骤 A
manifest_path = result["step_a"]["manifest"]
```

输出目录必须是新的。执行或采集程序出错时直接抛异常，已经产生的文件供调试使用。单条历史命令失败、超时是原始执行数据，replay 继续后续历史命令，最终提交状态由独立比较判定。

`collect` 的 IO 观察器使用 Linux/x86-64 的 ptrace；采集容器增加 `SYS_PTRACE`。每条原命令仍执行一次，命令文本和执行顺序不变。初始/提交快照连接仓库状态，系统调用记录保存中间写入、实际读取和流数据；同一条命令内写入、运行后删除的脚本也能保留。独立 `eviweave.replay` 使用原执行器，不启用此观察器。

采集输出在 `tests/`：

|产物|内容|
|---|---|
|`manifest.json`|单一 `tests` 清单、源码版本、调用及无法解析的材料|
|`snapshots/<位置>.json`|文件版本清单；相邻相同内容共用快照，仍实际读取命令前后状态|
|`blobs/<sha256>` 和 `blobs/chunks/`|文件版本的分块清单与无损字节；使用 `BlobStore.read(sha256)` 回读|
|`executions/<action_id>.json`|原观测、replay 输出与前后快照的连接|
|`trajectory.json`|材料版本、执行、读写/流关系、初始及提交文件状态|

每次调用的原始事件在 `runtime/calls/<action_id>/trace/events.jsonl`，同目录 `blobs/` 指向该次采集的共享版本库。文件以 64 KiB 分块；每个原版本仍按完整内容的 SHA-256 标识，不同版本和命令共享相同数据块。`cache_bindings.json` 保存普通/pytest 字节码与历史源码的比较结果。源码只用于解析、改写和编译比较，不执行其代码。

多个采集或实验轮次可以指定相同的 `--shared-chunks /path/to/chunks`；批量实验默认在本轮输出目录内共享。跨目录共享时，保留运行目录及其所指向的数据块目录，迁移时需要保持两者的相对位置。

所有测试版本只保存在 `tests` 中，`retained_at_submission` 标明最终仓库是否保留该版本，`historical_associations` 保存有具名结果的调用关联。只存在命令范围推断、没有具名结果的情况留在原始命令/输出中，不为每个可能成员生成关联行。支持 Python、Go、JavaScript/TypeScript、Rust 的常见测试定义。参数化、fixture/hook 和配置保留原始源码；实际具名结果中的参数实例分别保留，不提前构造 fixture 依赖信息。

调用的原始命令、输出和 checkpoint 由 replay 产物持有。测试条目不复制运行环境或生产源码状态；`replay` 指向相应目录。相关配置文件在选定基线测试后从提交快照读取，不为每个测试预存一份。

只有明确的具名结果和对应版本才能确认历史执行。只有套件汇总、skip、Go 缓存、同名歧义，以及命令中无法确定执行版本的修改，保留为未确认。历史 PASS 仍归属于当时的版本；代码语法错误记录在 `parse_errors`，不会隐藏解析器或采集器自身的程序错误。

## 从 A 生成历史材料

```python
from eviweave.history import history_records, read_context
from eviweave.issue_filter import rank_lexical

records = history_records(manifest_path)
selected_id = rank_lexical(records, "iter_multipart is_closed")[0]
selected = next(r for r in records if r["id"] == selected_id)
context = read_context(selected["source"])
```

每条记录只有 `id / text / source`。B 读取全部已采集文件版本、命令内源码、已执行命令及原始/replay 输出；新采集还包含实际流片段和 argv/stdin 代码材料。默认按 6,000 字符、优先在换行处切分。同一来源内的相同窗口共用条目，不同来源分别保留，以便恢复各自的上下文。`source` 是既有文件或 A 条目的地址，`read_context` 返回完整的已保存材料；原输出仅保存 head/tail 时，回读对应字段。原始行尾保持不变。命令行导出的 records 使用相对输出文件所在目录的来源，回读时传入 `read_context(source, base=output.parent)`。

`rank_lexical` 返回全部记录的顺序。示例读取其中一条；后续分析的候选仍是全量 `records`，包括名称未命中、语法错误和输出材料。`anchors.rank_units` 提供匹配单元的全部 `anchors` 位置，作为优先切片的提示，不作为材料淘汰规则。相同函数文本出现在不同文件或历史来源中时分别保留。

reasoning 和普通模型回复不进入材料列表。B 读取 UTF-8 文本，以及按源码声明编码的 Python 文本；二进制 fixture 继续保存在 A 的 blob 中。处理只读取本地文件，不调用 LLM 或重新 replay，也不建立独立索引。

需要保存候选输入时，可以显式导出到一个新 JSON 文件：

```bash
PYTHONPATH=src .venv/bin/python -m eviweave history \
  --manifest /absolute/replay/tests/manifest.json \
  --out /absolute/records.json
```

旧 pilot 与 B 共用分块实现，原有实验输入保持一致。真实 S030 材料及来源回读检查见[步骤 B 实现记录](../../research/eviweave_step_b_20261101/README.md)。

## 从 A/B 选择步骤 D 的切片入口

```bash
PYTHONPATH=src .venv/bin/python -m eviweave targets \
  --manifest /absolute/replay/tests/manifest.json \
  --out /absolute/targets.json
```

```python
from eviweave.targets import targets_from_manifest, read_target_source

result = targets_from_manifest(manifest_path)
records = result["records"]  # 完整 B 材料
for unit in result["units"]:
    raw = read_target_source(unit).encode("utf-8")
    for start, end in unit["anchors"]:
        expression_or_scope = raw[start:end].decode("utf-8")
```

D 从 issue 和提交版本 Patch 提取查询，不选择某一条测试来扩展名称。在历史可能运行的测试范围和编写记录中，按调用、字段／配置键、输入字符串匹配。命中超过 32 个代码单元的弱查询词不再独立选择仓库原有测试；issue 代码片段明确点名的调用／单独名称及修改声明名受到保留。任务中编写的语法单元完整保留，不受词频过滤和案例裁剪影响。

编写来源包括历史命令中的字面写文件、内联脚本，以及实际写入产生的文件版本。旧快照产物按与初始状态不同的版本判断；新 IO 记录按写入来源判断，避免首次读到的依赖库被视为 Agent 编写。数据和未命中的代码仍在完整 `records` 中。此过程不读取 reasoning、人工标签或 Verifier，不调用 LLM。

|输出|用途|
|---|---|
|`targets`|本轮实际用于匹配的查询名称|
|`units`|后续切片的候选；包含原文来源、路径、代码单元范围、`anchors` 和保留的 `ranges`|
|`syntax_templates`|可以共享语法准备工作的单元索引组；每个原始来源仍单独保留|
|`metrics`|入口数、锚点数、含词法依赖的单元数、源码量和语法模板数／字节数|
|`records`|完整 B 材料，包括输出、数据、未命中及无法解析的源码|
|`parse_errors`、`missing_patch_sources`|源码／命令解析问题，以及缺少最终版本的 Patch 源码|

`anchors` 非空的单元是组合入口；其余单元提供同版本 import、常量或 helper 等词法支持。锚点既可以是具体表达式，也可以是完整编写单元。`ranges` 表示选择的分析区域；`read_target_source` 始终回读完整源码，供后续恢复依赖。`syntax_templates` 的索引引用本次结果的 `units`，只共享语法准备，不合并执行状态或类型上下文。

文件来源引用 A 的源码版本。内联脚本使用 `inline` 序号，字面写文件使用 `write` 序号；两者都引用原始命令，回读时解码出代码。所有坐标都相对于回读文本的 UTF-8 字节。同一内容出现在不同来源中时，各来源分别保留。

A 的 `submission_state_validated` 必须为真，D 才解释提交版本 Patch。源码无法解码时，可用 `history.read_source_bytes(source)` 回读 A 保存的原始字节；依赖 shell 展开的脚本保留原命令和未解析原因。程序错误直接抛出，输出文件必须新建。

优化依据见[切片前检索实验](../../research/pre_slice_query_exploration_20261103/README.md)，正式接入检查见[优化后的 D 实现记录](../../research/eviweave_d_optimized_20261103/README.md)。

## 从匹配点恢复历史切片

使用新 `collect` 产物，运行 D→F：

```bash
PYTHONPATH=src .venv/bin/python -m eviweave slice \
  --manifest /absolute/replay/tests/manifest.json \
  --out /absolute/new-slicing-directory
```

`targets.json` 保留 D 的完整输入及 B 材料；`slices/` 保存匹配点与入口对应，`views/` 保存程序切片，`graphs/` 保存共享源码图，`episodes/` 保存材料和执行关系的切片起点。需要完整关系闭包时，将对应 episode 的 `seeds` 与 `inputs` 传给 `TrajectoryGraph.slice`。`summary.json` 列出未降到语句的入口与数据材料。未命中或不能解析的材料继续可回读。

写入磁盘的 targets、slices、views 和 summary 中，来源相对于 slicing 输出目录。回读已保存的入口可调用 `read_target_source(unit, base=slicing_output)`；用已保存的来源重新切片时，向 `TrajectorySlicer.location` 传入相同的 `base`。

也可分析单个源码位置。`source` 使用 A 的源码版本引用或轨迹材料引用，位置为回读文本的 UTF-8 字节范围：

```python
from eviweave.slicing import TrajectorySlicer

slicer = TrajectorySlicer(manifest_path)
source = str(manifest_path) + "#/source_versions/0"  # 换为目标版本的实际引用
path, digest, raw = slicer.source(source)
start = raw.index(b"operation(3)")
views = slicer.location(source, start, start + len(b"operation(3)"))
```

```bash
PYTHONPATH=src .venv/bin/python -m eviweave slice \
  --manifest /absolute/replay/tests/manifest.json \
  --source '/absolute/replay/tests/manifest.json#/source_versions/0' \
  --start 120 --end 132 \
  --out /absolute/new-location-directory
```

若 `--source` 来自已导出的相对引用，可指定 `--source-base` 为对应的导出目录。

默认分别分析实际消费该源码版本的各次执行；`--consumer <event-id>` 可限定其中一次。程序依赖包括局部数据/控制/对象状态、可解析的跨文件调用、helper 调用者和常见测试 setup。外层轨迹关联实际读写、删除前版本、生成文件和管道输入输出。只在提交时出现、未观察到消费者的源码仍提供静态切片。

文件读取是实际事实，函数内部的依赖是静态分析；返回的 `basis` 区分二者。读取一个测试文件不证明其中所有测试都运行过。原轨迹输出与 replay 输出各自保留来源。动态 eval 的内部值、未支持的嵌入语言和继续后台运行的进程会留下具体未解记录。实现与验证范围见[轨迹切片记录](../../research/trajectory_slicing_20261103/README.md)。

## 取回代码和运行基线

```python
from eviweave.artifacts import read_json
from eviweave.collection import read_source
from eviweave.baseline import run_selected_test

manifest = read_json(manifest_path)
test = next(t for t in manifest["tests"] if t["retained_at_submission"])
code = read_source(manifest_path, test["path"])
old_code = read_source(manifest_path, test["path"], sha256=historical_sha256)

baseline = run_selected_test(
    manifest_path, test["id"],
    "python -m pytest tests/test_x.py::test_x -vv",
    baseline_output,
)
```

基线直接从 manifest 取得 checkpoint。运行前后比较被选测试、相关配置与 Patch 文件，具名结果写入 `baseline.json`。需要构建或特定环境时，传 `build_commands`、`workdir`、`env` 和 `timeout`。

```bash
PYTHONPATH=src .venv/bin/python -m eviweave baseline \
  --manifest /absolute/replay/tests/manifest.json \
  --test-id <id> \
  --command 'python -m pytest tests/test_x.py::test_x -vv' \
  --out /absolute/new-baseline-directory
```

pytest 用 `-vv`，Go 用 `-v -count=1`，Jest 可使用 JSON reporter，使结果能对应到测试名。返回结果区分 runner 状态和具名测试结果。目标到达探测在步骤 D 选定目标后实现，不在 A 中写固定占位值。

## 开发检查

```bash
.venv/bin/python -m pytest -q \
  tests/test_eviweave_*.py tests/test_deterministic_anchor_evaluation.py
```

测试使用真实 Git、语法解析器、ptrace、Python/Node/C 小程序与 pytest。轨迹观察测试需要允许 ptrace。独立使用检查会将包复制到空目录，并在 `python -S` 下导入 replay 和调用 CLI。

真实 Docker 集成检查使用新的输出目录：

```bash
.venv/bin/python scripts/smoke_trajectory_slicing.py \
  --out results/behavioral_masking/<new-docker-check>
.venv/bin/python scripts/check_trajectory_real_case.py \
  --out results/behavioral_masking/<new-s030-check>
```

本次精简的[检查记录](../../research/step_a_simplification_20261101/README.md)使用 S030 已冻结的 124 条调用及文件观测重建 A：564 个保留测试、652 个测试版本、71 个文件版本、全部具名结果和执行状态一致。4,822 条关联中仅保留 16 条有具名结果的记录，原始调用和输出仍保留。清单从 14,284,800 降至 345,016 字节；相邻相同快照合并后为 20 份。另在已有 Docker checkpoint 上重新执行两项验证，采集与提交状态比较通过，基线取得 1 + 5 个实例的具名 PASS。
