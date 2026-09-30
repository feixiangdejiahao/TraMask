# Helper 期望参数：源码覆盖与配对执行

2026-09-30。这是一个独立的接口能力实验，检查固定组合的自定义 Go
helper 期望能否得到正确修订。它没有新增组合构造规则，也没有修改统一
v3 主实验：主实验仍为 **16/17**，N05 未获得合格目标见证。

## 实验问题和冻结方式

原接口无法将某些 helper 的比较期望对应到调用实参。新接口由源码确定
helper 的候选期望形参，再为修改后测试中的每次调用提供一个独立字面值
端口。角色来自程序分析，正确值仍须依据 issue 和已有验证判断。
完整方法及边界见[接口设计](helper_expected_slots_20260930.md)。

先固定全部 17 个 trial 的 4,502 个源码候选，提取端口，封存代码、输入
和请求。候选资格只使用源码：存在新 helper 端口，且旧接口没有普通可编辑
断言。随后在该资格集合内使用原 `semantic_selection.select` 调度器，每例
最多 8 个请求。没有使用目标 ID、历史 oracle 回答、运行结果、参考补丁或
隐藏测试选择候选。模型是 `.env` 配置的 `deepseek-v4-flash`，thinking
开启，每个请求一次调用，不重试。

另一个评价者仅用原测试、helper 和固定修改后测试推导期望，在读取模型
回答和 native 输出之前封存评价依据。这份 ledger 在模型调用结束后落盘，
因此它是**对回答和运行结果保持盲态的独立评价**，不是调用前预注册真值。
它不进入模型输入，不能作为新增推理缓存使用。

## 源码覆盖

全量检查包括 1,942 个 Go 候选。新增 30 个可编辑 helper 调用，全部来自
N05 的同一个 `verify` 源码声明；不能将其称为 30 个 API 或 30 个缺陷。
N05 可表达候选由 133/175 增到 163/175。

新实验接口收窄了普通断言的表达能力：Go 原可表达 1,178 个候选，新接口
可表达 653 个，新增 30 个，同时失去 555 个。损失主要来自普通谓词端口
不再可编辑，另有 5 个原可表达候选成为 owner unknown。因此它没有替换
主线接口；本次调度仍用旧接口独立计算资格，不把收窄误写为无损扩展。

[census summary](../results/helper_expected_slots_20260930/census_v1/summary.json)
和 [seal](../results/helper_expected_slots_20260930/census_v1/seal.json)记录固定
分母、全部不支持原因及快照。独立字节重构核验 89,225 项通过；这是源码
位置与重构检查，不是语义正确率。

## 模型与执行结果

只有 N05 具有新增资格，调度选定 8 个候选。它们是在同一输出对象上执行
一个已有输出操作，随后添加 `Reset()`，最后由 `verify` 读取整个临时文件。
第一个候选执行两次 `Reset()`。源码观察的是文件累计字节；样式重置不会
清空已经写入的文件。因此修订后的期望应包含两个操作的完整输出。

| 指标 | 结果 |
|---|---:|
| 新模型请求 | 8 |
| 可解析并被接口接受的完整修订 | 4/8 |
| 独立源码审查正确的修订 | 4/8；已交付修订中 4/4 |
| 达到输出长度上限、空 content、unknown | 4/8 |
| 已交付错误 oracle | 0/4 |
| 沿用旧期望的固定组合：真实断言失败 | 8/8 |
| 新修订：native 通过 | 4/4 |
| 原测试控制：native 通过 | 22/22 执行记录，8 个不同源控制 |
| 编译、环境或执行错误 | 0 |
| 新增确认目标缺陷 | 0 |

接受的修订对应两次 Reset、RestoreScreen→Reset、SaveScreen→Reset 和
ExitAltScreen→Reset。独立审核确认它们与预先推导的完整测试逐字一致；
实际观察、调用、输入、helper、Seek/ReadAll/Fatal 前提和清理都保持原样。
随后使用本地离线 Docker，逐候选隔离 Go 编译，执行 8 个原组合与 4 个
新修订。原组合确实因不完整期望报警，新修订通过。

这支持“**本组 8 个旧期望报警中，4 个得到了正确修订并消除**”。另外
4 个因 length 没有交付 oracle，仍未解决；unknown 不能当作 preserve 或
正确阴性。不能据此报告全体 17 个 trial 的误报率降低，更不能报告漏报
改善。此组未包含 N05 主实验目标，冻结的 16/17 不变。

8 次请求共 26,995 input token、90,994 completion token，总计 117,989。
即使只要求填写一个字面值，模型仍可能进行大量推理且没有交付回答。
7 个请求没有附加 Reset 的原 donor 测试，独立评价则用它确定输出契约；
这是已发现的上下文差异，不把它当作四次 length 的已证明原因。已有
请求、回答和结果保持冻结，不根据答案补上下文后冒充同一实验。

证据分别保存在：

- [冻结请求及选择](../results/helper_expected_slots_20260930/generation_v1/ready.json)
- [模型调用汇总](../results/helper_expected_slots_20260930/generation_v1/execution/summary.json)
- [独立源码期望](../results/helper_expected_slots_20260930/evaluation/source_oracles_v1.json)
- [完整模型 oracle 审核](../results/helper_expected_slots_20260930/evaluation/model_oracle_audit_v1.json)
- [独立配对 native 审核](../results/helper_expected_slots_20260930/evaluation/paired_native_audit_v1.json)
- [真实执行记录](../results/helper_expected_slots_20260930/native_v1/N05/executed/runs.json)

## 对学术方法的含义

本实验修复了“程序知道该 helper 在比较什么，但接口不能表达其期望修订”
这个能力缺口。它没有提供新的组合搜索核心，也没有证明 helper 角色在
开放 Go 程序中具有普遍可靠性；30 个端口只覆盖一个源码声明。

对当前研究更有用的观察是：分析必须同时梳理**同一对象上的操作历史和
观察范围**。测试终端样式与测试文件累计字节需要不同的期望；一个可编辑
端口本身不提供这层信息。若以此继续设计，应让程序分析连接操作、原验证
和实际观察的产生路径，再让模型解决无法静态确定的契约语义，而非增加
更多自然语言字段。

## 复现与检查

现有输出目录封存，不应覆盖。换用新目录可运行：

```bash
.venv/bin/python scripts/run_helper_expected_slots.py prepare \
  --input results/relation_search_20260929/candidate_inventory_v1 \
  --output results/new_helper_generation --budget 8
.venv/bin/python scripts/run_helper_expected_slots.py run \
  --input results/new_helper_generation --workers 2
.venv/bin/python scripts/run_helper_expected_slots.py emit \
  --input results/new_helper_generation --output results/new_helper_native --timeout 120
.venv/bin/python scripts/execute_relation_search.py run \
  --input results/new_helper_native/N05/emitted \
  --output results/new_helper_native/N05/executed \
  --workers 2 --registry data/relational_gap_v1/registry.json
```

最后代码版本的相关测试通过 **233 项**：接口/helper/census 76 项，调用、
局部 helper、失败源码和证据集成 137 项，原检索集成 20 项。此前全仓库
2,838 项通过发生在最后诊断分支修复之前，不报告为最终版本全仓库检查。
