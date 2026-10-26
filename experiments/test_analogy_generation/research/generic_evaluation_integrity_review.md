# 通用生成实验：数据通路与指标独立复核

复核日期：2026-09-23。只读复核冻结证据和请求，不读取 `.env`、参考补丁源码或隐藏目标，不发模型请求，不修改生成规则。

## 数据通路

检查 `generic_v5/batch2`、`generic_edit_square/batch1`、`generic_observation_priority/batch1` 的全部 28 个实际实验请求。每个请求均可由已冻结的 `evidence.json`、`candidates.json` 和统一展示规则精确重建；请求、证据、候选的 SHA 均一致。模型 ID 均为用户指定的 `ds/deepseek-v4-flash`，与 prepare 一致。请求禁用 tools，thinking=disabled 与 reasoning_effort=none 一致。

提供给模型的 production_context 明确声明候选实现可能有 bug，其函数体或当前输出不能当作 oracle。未发现封存控制表、人工目标配置、参考补丁或评价报告的路径进入这些请求。该路径检查只是辅助；核心证据是冻结文件到请求的精确重建，不能据此声称形式化的数据隔离证明或模型实际遵循提示。代理返回的 model 字段也不构成底层模型身份的独立验证。

机器证据：[28 个请求逐项复核](../results/generic_evaluation_summary/data_path_audit_v1/audit.json)。0 项检查失败；历史请求、无代码诊断、3 次意外旧 unit fixture 连接尝试不混入此集合。

用户更新 provider 并明确更正模型名后，另复核 priority batch2、flat/balanced windows 和 predicate-free windows 的全部 74 个正式请求。请求均使用 `deepseek-v4-flash`，可从各批冻结证据与候选逐项精确重建，检查失败为 0；该复核不加载 `.env`、不发模型请求、不读取参考或隐藏目标。[新配置请求复核](../results/generic_evaluation_summary/data_path_audit_v2/audit.json)。

## 指标表述

- 候选报警先独立计算，要求源控制通过、测试体失败且无全局运行错误。参考失败数单列；参考通过不证明 oracle，也不产生全局 FPR。
- JSON 中 `differential_candidates` 仅表示受控的候选失败/参考通过，应称“待审差分”。跨版本表原“有效差分”容易被误读为已证明语义有效，现改为“待审差分”，数据不改。
- 7 个 pilot 是 discovery。报告的零已确认缺陷不等于对所有真实缺陷的完整 recall，也不等于程序无 bug；尤其编译失败、无候选、控制失败均不能当作测试通过。
- 3 个跨项目任务的选取不依赖 outcome，但在连续多版开发中已经反复报告覆盖/运行信息。因此后续不能称完全未见、一次性盲测；应称固定的 feasibility 任务。当前没有跨项目有效性证据。
- 独立 oracle 审计在当前批参考执行前固定，但评价者此前看过旧版结果，不能称盲态。旧版 429 报警的 9 个 unknown 保留，不能根据参考结果反向定性。
- 编译无效、源控制缺失、全局运行错误等指标可能重叠。不能将这些列相加充当互斥样本总数。
- 每个替代生成器单独使用 128 候选预算，不能汇总多个版本后声称一次等预算运行的成功率。模型无效返回与有效拒绝分别统计，全部尝试成本保留。
- 尚未进行生成测试辅助修复的配对实验，故没有 issue resolution rate 结果。生成数、差分数、已确认缺陷数均不能代替该指标。

## 零输出版本

`generic_instances_v2/batch1` 的 18 direct 与 36 gated 单元均完成冻结/运行记录；54 单元全为零生成、零测试执行、零模型调用。见 [完整记录](../results/generic_instances_v2/batch1/evaluation_complete.json)。旧 extractor 未覆盖实际 top10 非 helper 断言是覆盖问题；放宽输入参数限制后依然零输出，不能将原零输出主要归因于参数限制，也不能解释为 oracle 精度改善。

模型外发限定：旧配置下、此前用户指定模型后的正式实验请求使用 `ds/deepseek-v4-flash`；本次 `.env` 更新且用户更正模型名称后，新的正式实验请求使用 `deepseek-v4-flash`（无 `ds/`）；另有 3 次误触的旧 unit fixture `gpt-6-astra` 连接尝试，ConnectError，接收/用量/费用未知，已添加全局 unit socket 禁用。完整事件原字节已单独归档，不记作成功实验调用或零成本。

另一次开发验证误用未限定路径的 `pytest -q`，递归收集到 data/results/vendor，发生导入期执行并以 collection errors 结束。predicate-free 源码及针对性回归在该命令之前完成，之后未据其输出修改生成器；开发者因此不能再称完全未见真实测试材料。现有日志不能证明网络和文件副作用为零，原始命令、完整输出和时间已[单独归档](../results/collection_incident_v1/README.md)。项目新增 `pytest.ini` 将默认发现目录固定为 `tests`，限定后的 664 项项目测试通过。
