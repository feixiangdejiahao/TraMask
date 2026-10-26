> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/assertion_write_origin_census_20260929.md) · [旧路径映射](../../../results/path_map.tsv)

# 自动枚举后的支持面与静态排序

**把原型扩展到所有输入断言后，支持面只有 243/4625（5.25%），尚不能充当通用的 A/q 自动定位算法。** 独立对照中，目标 A 和 q 的确定性前十位置各为 2/8；考虑相同证据桶内任意顺序，稳定下界只有 1/8。这些都是源码检索位置，不是组合生成、正确 oracle 或缺陷检出率。

本次不再手工输入 N01/N02 的 q 行号或 `is_closed`。固定全部 8 个 Python corpus，自动枚举其 2048 个已注册测试、显式引用 helper 内的 Python `assert`，并保留 corpus 已提取的 framework 断言。每例只建立一次源码索引。去重后是 4288 个可解析 Python assert、334 个 framework/其他已有观察点，以及 3 个位于不可解析源码中的已记录断言；比原 capsules 多发现 46 个断言。这里的“全部”限于已有 corpus 的 256 tests/case 及所列 helpers，不代表全仓库或完整 trajectory 的所有测试。

[冻结协议](../../../results/program_relation_search/program_relation_search_20260929/assertion_write_origin_census_v2/protocol.json)记录了输入、代码 SHA、固定案例和排序规则。生成阶段未读目标标签、隐藏测试、oracle 缓存或执行结果，也未调用模型或运行被测仓库。代码为 [枚举入口](../../../scripts/analyze_assertion_write_origin_census.py)和[字段写入分析器](../../../prototypes/assertion_write_origin.py)。

| 案例 | 全部断言/观察点 | 可部分绑定 writer | 含受支持 q 的 tests / 256 | “多 writer + 先操作后观察”桶内 q |
|---|---:|---:|---:|---:|
| P1 | 518 | 13 | 5 | 0 |
| P2 | 431 | 15 | 6 | 0 |
| P3 | 611 | 10 | 5 | 0 |
| P4 | 760 | 1 | 1 | 0 |
| N01 | 581 | 62 | 31 | 14 |
| N02 | 608 | 118 | 72 | 34 |
| N03 | 470 | 22 | 16 | 0 |
| N04 | 646 | 2 | 2 | 0 |
| 合计 | **4625** | **243** | **138 / 2048** | **48** |

支持表示能把至少一个实际属性读取绑定到局部构造类，并找到该类的源码写入，不表示该断言的所有操作都已分析。类型分派、生成器完成性和动态最后写入仍是 unknown。P3 还有 3 个注册测试源码无法解析，已有 capsule 仍计入 unsupported；没有把它们静默删除。

排序只用两个布尔条件：同一绑定字段在构造/操作路径中是否有多个可能写入位置；原测试在 q 前是否对同一局部构造绑定对象调用了通往 writer 的方法。二者同时满足排在前面，之后依次是只有操作路径、只有多个 writer、仅能绑定 writer；桶内按原路径和字节位置排序。测试 A 采用其最好 q 的桶。没有加权分数、关键词、字段白名单或目标 ID。原输出为每项保留整个同分区间，因此不会把源码排序的任意性包装成相关性。

## 独立目标位置检查

排序完成后由另一代理依据既有独立确认见证检查 A/q，见[独立评价](../../../results/program_relation_search/program_relation_search_20260929/evaluation/assertion_write_origin_census_review_v2.json)。生成时没有这些标签输入。

| 案例 | 目标 A 位置 | 目标 q 位置 | 相同证据桶内可能位置 A / q |
|---|---:|---:|---|
| P3 | 3 | 8 | 2–5 / 2–10 |
| N01 | 8 | 10 | 1–11 / 1–14 |
| N02 | 11 | 12 | 1–30 / 1–34 |
| P1、P2、P4、N03、N04 | unsupported | unsupported | 没有排序位置 |

因此，在固定源码顺序下 A@10、q@10 都是 2/8；同桶最坏顺序为 1/8，最好顺序为 3/8。这些上下界不是统计置信区间。N01 的第十名无法证明其证据比第十一名更强；N02 落到前十之外也主要是桶内源码顺序的结果。P3 能稳定进入前十，但它的目标仅属于最弱的“绑定到构造写入”桶，不能归因于新设计的写入切换分析。

五个被排除的目标说明当前缺口：P1/P2 的观察对象来自解析器返回序列的解构，P4 来自 fixture/方法返回，N03 检查标量与 `len(moved)`，N04 使用命令返回对象及 Database 下标/迭代产生的值。直接局部构造对象的字段模型覆盖不了这些数据流。P1 的实际生成失败还先发生在事件解构处；N04 的源观察需要后续语义修改才能成为正确 oracle，单纯找到原 q 不等于这些前提已经解决。

4382 个 unsupported 断言的互斥主原因中：1558 个没有属性读取，472 个涉及条件赋值，436 个同时遇到多类不支持读取，334 个是当前原型不处理的 framework 观察，294 个是嵌套/非局部接收者，170 个是非直接字段别名的 property。其余具体原因及每例分布见 [support_accounting_v1.json](../../../results/program_relation_search/program_relation_search_20260929/assertion_write_origin_census_v2/support_accounting_v1.json)。这表示分析能力缺失，不能称为这些测试质量差。

本次只支持一个有限结论：程序能够在不指定字段的情况下自动定位一部分对象字段观察，并解释来源；**尚未得到稳健的目标排序信号**。需要扩大返回值、局部定义和聚合结果的来源分析，才能公平检验写入来源是否有助于组合搜索。继续在当前窄支持面上调整权重，会遮蔽主要问题。

32 项分析器/枚举测试通过，覆盖共享索引、同一行多个 assert、helper 与 framework 保留、去重、同分区间，以及原有类型绑定阴性控制。第一次 census 的 3 个不可解析 P3 断言曾误标为 framework unsupported；v2 只修正原因分类。[逐项等价证明](../../../results/program_relation_search/program_relation_search_20260929/assertion_write_origin_census_v2/v1_rank_equivalence.json)确认 8 例全部 A/q 支持状态、排序、同分范围与源码证据完全不变。原 v1 结果仍保留。
