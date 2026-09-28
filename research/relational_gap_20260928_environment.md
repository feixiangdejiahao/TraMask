# 17 条轨迹的统一输入与运行环境

准备脚本为 [`prepare_relational_gap_cases.py`](../scripts/prepare_relational_gap_cases.py)，通用执行脚本为 [`run_relational_gap_case.py`](../scripts/run_relational_gap_case.py)。本轮 17 条 trial 实际覆盖 **14 个不同 task**：旧七条中有三条 Textual 同 task、两条 Tengo 同 task。

17 个候选工作区全部从精确官方镜像中的已核对 base commit 加公开 `model.patch` 得到。新补齐 HTTPX 两例、SQLite、go-git、Pebble 的精确镜像，Docker 存储仍为 `/data3/jhx/docker`。其余使用原有镜像。没有修改或删除原有镜像、容器。

生成输入在 `data/relational_gap_v1/<ID>/`：只含 issue、提交的候选补丁、原始 agent trajectory、候选仓库。仓库仅导出版本管理中的 base 文件和候选补丁文件，不导出镜像中任意未跟踪文件。没有加入 verifier、参考补丁、人工探针、人工选定步骤或 gap 标签。原始 trajectory 中 agent 自身已经观察到的信息保持原样。

统一注册表：

- `data/relational_gap_v1/registry.json`：供生成流程使用；兼容 `scripts.run_generic_experiment.resolve_case` 自定义 registry。
- `results/relational_gap_20260928/case_registry.json`：相同的来源与环境信息。
- `results/relational_gap_20260928/environment_summary.json`：逐例执行结果、非空原测试控制及哈希。

这三个大数据目录不进入 Git；准备脚本可重建注册表。每个案例的 `repository_provenance.json` 记录 image ID、核验的 base、patch SHA256、导出 archive SHA256。

## 已完成验证

17/17 均能在完整候选环境中运行普通源码测试，所选原开发者/agent 测试全部通过。覆盖 Python pytest、Go testing、Vitest 三种运行方式。P5、N05 初始 Go 过滤器未匹配测试，明确排除该两次空运行，已用真实存在的测试重跑。P5/P6/N05 同时验证了覆盖整个候选测试文件的执行接口。

| Case | 实际采用的原控制 |
|---|---|
| P1–P3 | `python -m pytest -q tests/test_xterm_parser.py` |
| P4 | `python -m pytest -q tests/test_sessionbundle.py` |
| P5 | `go test -count=1 -v -run TestCompiledFunction .` |
| P6 | `go test -count=1 -v -run TestGoCall .` |
| P7 | `cd library && pnpm exec vitest run src/methods/recursive/recur.test.ts --reporter=verbose` |
| N01 | `python -m pytest -q tests/models/test_responses.py` |
| N02 | `python -m pytest -q tests/test_multipart_response.py` |
| N03 | `python -m pytest -q tests/local/test_daemon.py` |
| N04 | `python -m pytest -q tests/test_safe_import.py` |
| N05 | `go test -count=1 -v -run TestStyleWidth .` |
| N06 | `go test -count=1 -run TestDiff .` |
| N07 | `go test -count=1 -v -run "^TestInit$" .` |
| N08 | `go test -count=1 -v -run "^(TestWaitForDurability\|TestDurabilityNotify)$" .` |
| N09 | `pnpm --filter @koota/core exec vitest run tests/deferred.test.ts --reporter=verbose` |
| N10 | `npx --no-install vitest run src/schema/actions/requiredIf.unit.test.ts --reporter=verbose` |

这些是环境控制，不是完整 suite 通过声明，也不是自动 gap 检出成绩。N07 使用基础仓库测试确认构建和运行环境；此前 agent 的临时 merge 验证仍须从 trajectory 恢复。

另在独立的 `evaluation_assets/relational_gap_v1/probes/` 中补齐四条人工事后见证：N01/N02 HTTPX、N07 go-git、N08 Pebble。每条均在完整候选仓库得到 **2 项对照通过、1 项目标断言失败**；不再依赖只有核心函数的组件复放。go-git 直接调用完整仓库的 `mergeText`，包含真实 diff 构造；Pebble 使用真实 DB、内存文件系统与 sync commit。没有 stub 候选函数。这四条仅独立确认既有 ground truth，禁止进入生成器输入，也不能计作算法成功。

## 执行任意普通 source test

```bash
.venv/bin/python scripts/prepare_relational_gap_cases.py --materialize --pull-missing

.venv/bin/python scripts/run_relational_gap_case.py \
  --case P1 \
  --test-file /absolute/path/to/edited_test.py \
  --target tests/test_xterm_parser.py \
  --command 'python -m pytest -q tests/test_xterm_parser.py' \
  --output results/relational_gap_20260928/example_run
```

多个支持文件可使用 `--mounts manifest.json`，格式为 `[ {"source": "/absolute/file", "target": "repository/relative/file"} ]`。无需测试文件时直接提供 `--command`。Python 调用可导入 `scripts.run_relational_gap_case.run_case`。

输入先只读挂载到 `/relational-inputs`；容器内先应用候选补丁，再复制整份测试到目标路径，因而允许覆盖已有或 patch 新增的测试文件。直接在应用 patch 前只读挂载目标会阻止 `git apply`，接口已避开这个问题。每次使用新的一次性容器、关闭网络、限制为 2 CPU/8 GB，并保存 request、挂载文件哈希、stdout/stderr 和执行结果。测试非零退出与容器/环境错误分别记录；测试失败本身不自动认定为正确目标检出。
