> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_batch3_evaluation.md) · [旧路径映射](../../../results/path_map.tsv)

# Relational gap batch3：独立评价

本轮完整跑完17个trial。固定目标原测试静态召回仍为 **17/17**；独立确认正确组合、正确断言、通过的原测试对照及目标缺陷失败的仍为 **1/17（N10）**。相比batch2，没有新增目标缺陷检出，其他16例仍未检出。这里的静态召回不是Hit@10：它衡量整个静态源测试集合是否包含固定目标。

| 指标 | batch2 | batch3 |
|---|---:|---:|
| 目标原测试静态召回 | 17/17 | 17/17 |
| 获准候选中含目标原测试 | 14/17 | 14/17 |
| 实际观察到目标原测试衍生候选结果 | 10/17 | 10/17 |
| 独立确认目标缺陷检出 | 1/17 | 1/17 |
| 冻结静态候选 | 8444 | 8448 |
| 模型获准候选 | 830 | 809 |
| 有执行索引的候选 | 822 | 797 |
| 有对应具名结果的候选 | 582 | 581 |
| 模型调用 | 34 | 34 |
| 响应整体协议通过 | 34/34 | 32/34 |
| 模型token总量 | 921657 | 919231 |

全部调用使用相同预算：每例最多2次、每次至多提供64个候选、最多接受32个。4个模型工作线程与2个Docker执行线程分开排队，不再让慢Go执行阻塞后续模型请求。没有重试。P3/r0与P4/r0因额外顶层JSON元数据被当前冻结协议整体拒绝；原始响应保留，本轮没有补救。放宽该限制只能属于下一轮。

本轮184个执行组中，35组报告编译、收集或执行错误，其中19组有Go编译诊断。这些不计作缺陷检出。有具名结果也不等于有效的缺陷证据；评价还要求同一manifest中声明的完整原测试对照通过。

## N10成功证据与局限

当前源文件的候选 `32dd7661b8b920895cff7c62` 将缺少details时的 `zod.parser({ mode: 'put' })` 变为 `zod.parser({})`。程序沿两跳调用找到 `mode='put'` 默认值；保留 `toThrow(z.ZodError)` 是正确的。生成测试具名失败“expected function to throw an error, but it didn't”，同组完整原测试 `gc_control_24dc1e3767c92c60f06d7c35` 通过，重复确认了batch2的目标缺陷。

另外三个默认省略候选不能重复算成功：历史版本的相同缺陷场景没有具名执行结果；另外两个仅修改提供合法details的调用，当前源版本通过，历史版本同样未执行。历史文件被命名为 `*.unit.test.test.ts`，不满足仓库Vitest的 `*.unit.test.ts` 收集模式。这属于通用历史文件恢复问题。

证据：`batch3_emitted/N10/group_002/`、`batch3_runs/N10/group_002/normalized.json`；历史版本为group003。完整冻结审查见 `batch3_reviews_audited.json` 与 `batch3_evaluation.json`。

## 逐例结果

| Trial | 获准候选 | 观察到结果 | 获准中含目标原测试 | 确认目标缺陷 |
|---|---:|---:|---|---|
| P1 | 64 | 64 | 是 | 否 |
| P2 | 64 | 64 | 是 | 否 |
| P3 | 32 | 32 | 是 | 否 |
| P4 | 22 | 19 | 是 | 否 |
| P5 | 63 | 23 | 否 | 否 |
| P6 | 46 | 36 | 是 | 否 |
| P7 | 35 | 26 | 否 | 否 |
| N01 | 59 | 26 | 是 | 否 |
| N02 | 64 | 48 | 是 | 否 |
| N03 | 55 | 50 | 是 | 否 |
| N04 | 42 | 42 | 是 | 否 |
| N05 | 32 | 32 | 否 | 否 |
| N06 | 47 | 14 | 是 | 否 |
| N07 | 55 | 0 | 是 | 否 |
| N08 | 42 | 30 | 是 | 否 |
| N09 | 43 | 37 | 是 | 否 |
| N10 | 44 | 38 | 是 | 是 |

两个14/17及10/17的总数相同，不代表成员相同：本轮P1、N08进入获准目标集合，P7、N05离开该集合。不能仅比较总数来声称排序变好。

## 误报与漏报

321个候选观察到失败，256个同时具有通过的完整原测试对照。其中确认1个目标缺陷、抽查确认1个错误oracle，其他254个通过对照的失败尚未证明oracle正确，保留unknown。确认错误oracle的数量不是精确率分母，也不能据此声称误报从4下降到1。

同一明确误报在两轮都存在：P1 `q_8301e007b73f59fa6a996516` 把release输入改成省略事件类型的press输入，却保留期望release。两个原测试对照通过，生成测试返回press并失败；正确行为被错误断言判错。因此这个误报没有改善。

所有809个获准候选都按固定目标组合做了独立审查。除N10之外，缺少的仍是跨因素关系本身：例如N07只改变文件名/提交标签，没有改变两个diff hunk的相交几何；N08调整大整数或job ID，没有把wait目标绑定到实际batch的exclusive high sequence；N09只对普通记录做字段删除，没有将部分字段与deferred pre-flush观察组合。不能把source parent命中或任意失败算作这些目标组合的检出。

## 执行层改善与剩余问题

v3加入Go语法树绑定分析：仅对生成函数中变换后不再被读取的普通局部声明加入 `_ = local`，保留初始化一次执行及词法作用域；完整原测试函数体保持原样。历史Go辅助文件仅保留选中的测试入口及被引用的测试入口闭包，普通helper保留，能解析的未使用import改为blank import以保留init。22个独立回归测试通过，包括真实Go编译/运行、嵌套shadowing、闭包、多变量、控制体不变及import init副作用。

P6四个执行组已经能运行具名测试，N06也有一组能运行；这证明物化可靠性有所改善，但尚未增加目标缺陷检出。

剩余关键问题有三类：

- 数值边界构造缺少数值域前提。`modules == nil` 被转换为 `(modules)-1`，模型仍接受；Go的ModuleMap、Document指针、Hash等均不能做这种运算，一个无效候选会阻止整组编译。这不是目标缺陷。
- 历史代码依赖不完整。N07尚有缺失的formatcfg导入、mergeTestRepo/helper，HTTPX历史脚本的顶层行为在pytest收集期间执行，生成器helper被误当成可执行测试入口。
- 获准候选并没有构成真正缺少的关系。逐例排除理由冻结在 `batch3_manual_review_notes.json`，独立审查材料在 `batch3_review_aids/`，执行诊断在 `batch3_execution_audit.json`。

生成器和模型未读取target_census、独立probe、隐藏verifier或参考补丁。所有审查标签只在evaluation侧写入。模型响应、源码、运行结果、materialization记录均有冻结证据；`all_17_targets_proven=false`。

## 复核

```bash
.venv/bin/python scripts/evaluate_relational_gap.py evaluate \
  --batch-root results/relational_gap_20260928/batch3 \
  --emitted-root results/relational_gap_20260928/batch3_emitted \
  --reviews results/relational_gap_20260928/batch3_reviews_audited.json \
  --output /tmp/relational-gap-batch3-recheck.json
```
