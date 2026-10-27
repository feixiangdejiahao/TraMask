# 已执行历史片段的复用：88 条组合缺口轨迹

本轮回答两个问题：缺失 witness 的 Trigger、Context、Check 有多少已存在于 Agent 的执行历史；自动组合其中的片段，能否恢复真正的错误检测。

固定样本为 2026-10-21 手工复审中 `supported` 的全部 88 条轨迹。观察阶段逐条检查历史执行证据，由两个独立 Codex 线程审查。此前 Context Repair 的分类仅用于定位材料，本轮允许组合输入、状态和断言。

88 条轨迹的两份独立审查与最终裁定已经完成并冻结。共识别 125 个缺失因素：40 个有精确的历史执行片段，66 个有相关执行组件，13 个未找到，6 个尚不能确定。38 条轨迹至少包含一个可精确复用的缺失因素；其中 21 条的全部缺失因素都有精确历史来源。[完整统计](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.json) · [逐例表格](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/census.csv)

第二阶段已按用户要求终止。重跑与续跑队列结束了 15 条生成尝试，其中 11 条产出候选、4 条停止；终止时另有 2 条在途任务和 49 条未启动任务。原轮次的结果、调用日志及代码均已保留。自动 P/R 对照尚未开始，因此尚无第二阶段的错误检测结论。[终止记录](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/infrastructure/no_max_tokens_revision_002/termination_by_user_001/summary.json)

结果目录：[`results/behavioral_masking/20261026_fragment_reuse_n88_r01`](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01)。第一阶段已完成；第二阶段已终止。

第一阶段的研究结论与解释见[阶段 1 结果说明](phase1_findings.md)。

已验证的两个联合修改说明了不同的组合价值。S085 将历史中的两条耗时记录迁回原隔离测试，保留操作和断言，得到错误补丁失败、正确实现通过；分别只迁移一条时，两种实现都通过。这里复用的是历史中已有的低慢文件数量状态和另一测试中的隔离断言。[逐例结论](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S085.json)

S006 将默认并发配置与两个独立初始化任务组合，保留原有峰值为2的断言，也得到错误补丁失败、正确实现通过。仅去掉并发上限而保留三个任务，会错误拒绝峰值为3的正确实现。因此，第二项修改的作用是让原断言在新条件下仍然成立。该结果来自完整的预选测试函数；原文件内其他测试的类型错误单独保留。[逐例结论](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S006.json)

上述执行结果均经两个独立线程复核，属于知情观察阶段。下面的案例解释历史片段如何支持组合，以及哪些信息仍需推导。

历史片段并非总是缺少组合。S037 曾运行完整且正确的数组依赖测试并得到失败，随后把期望求值次数从1/2改为2/3，使错误实现通过。该案例应比较“恢复历史测试”的效果，而不能把恢复原断言算成新的跨测试组合收益。[逐例结论](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S037.json)

S030和S031呈现了另一种可复用结构：一个测试验证解析错误，另一个测试验证正常流式处理后的资源关闭。它们缺少的是“异常结束也必须关闭”的联合检查。S030的五条Verifier失败均发生在关闭状态断言，解析异常本身已经正确抛出。当前已定位流式状态与关闭检查的历史来源，组合后的P/R执行尚待验证。[S030](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S030.json) · [S031](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S031.json)

S051–S053的边界输入已经执行过，漏检来自错误的期望值。S052历史中有独立执行的单次反射规则，S053有NumPy边界映射，但最终测试没有采用这些信息。S051只找到退化尺寸下的相关fallback检查，完整规则仍需从任务要求推导。因此，“有相关历史组件”和“正确oracle已经完整存在”需要分别统计。[S051](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S051.json) · [S052](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S052.json) · [S053](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S053.json)

S045也曾运行完整的失败测试，随后在被调用函数中加入等待，使重复请求重叠，测试开始通过。它与S037一样，应检验历史测试恢复的价值，再判断自动组合是否带来额外收益。[逐例结论](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S045.json)

S066的历史分别执行过小写`aggregate`格式化、`keywordCase: upper`转换和完整的大写AGGREGATE布局断言。将前两项迁回布局测试，可以保留原断言，形成一个不需新增语义要素的三测试组合候选。upper设置来自旧项目测试；恢复源码并核对历史全套执行后，两条独立审查才确认其来源。[S066](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S066.json)

S065则需要迁移正确的预期。原测试已经调用`Invalid.lash`，却断言回调不改变结果；历史中实际运行过的`Result.lash`测试要求返回回调产生的新容器。这个规则可以支持修改原断言，但仍需从Result映射到Validated，因而属于相关组件复用。上述两个候选的组合执行均尚未完成。[S065](../../results/behavioral_masking/20261026_fragment_reuse_n88_r01/observation/adjudicated/S065.json)
