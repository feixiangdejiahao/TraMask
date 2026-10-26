> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/executed_oracle_budget_audit_v1.md) · [旧路径映射](../../../results/path_map.tsv)

# 执行与 source control 筛选语义预算：静态审计

此实验只重新分配候选展示机会，不调用模型、不重新运行仓库，也不判定 oracle 正确性。实现为 `scripts/audit_executed_oracle_budget.py`。冻结的 11 个完成 round 是 N01–N10 与 P1 的 `round_000`，共 1,230 个 `prepared/candidates.json` 原输入，不包括模型新修订；后续完成的 round 不加入这个分母。

三组对照是原保存的语义请求、当前 impact 对全部相同原输入的选择，以及当前 impact 仅对已记录 pass/fail 且 source control 有效的输入的选择。后两组使用相同当前代码，避免把 Go predicate 接口修复混算为执行筛选收益。pass 与 fail 不影响资格，失败消息、评价标签和历史 oracle 不参与。

## v1：仅依据原反馈元数据的筛选

`results/relation_search_20260929_v3/executed_oracle_budget_v1/seal.json` 保留原始完整结果。原反馈给出 813 个资格候选、64 个实际执行但 source control 未确认、353 个 execution_unknown。未筛选共分配 176 个名额，筛选后 160，54 个候选得到不同的展示机会。

**这些数字只描述原 feedback 接口的认定，不能把 execution_unknown 解释为没有实际运行。** 特别是 N10 的 128 个候选全部被该接口记作 unknown，而独立评价已有命名原生执行证据。N10 因而失去所有模型预算，这是直接使用该元数据进行硬筛选的错误结果，不是源程序不可执行的证据。v1 没有覆盖、修补或回填任何原记录。

## 发现的通用反馈缺口

`relation_search.feedback.collect` 原来通过 `_selected_test_name` 匹配声明生成测试名与 reporter 名称，没有规范化首尾空白。Vitest `fullName` 可以因为空根 suite 产生前导空格：声明 `suite gc_changed` 的原生命名结果是 ` suite gc_changed`。独立 evaluator 进行首尾 strip，反馈模块却没有，所以同一份已存在报告在两处得到不同的“是否执行”结果。

只读审计 N10 的 217 个 run 记录发现：严格匹配 control 为 0/89、generated 为 0/128；规范化首尾空白后，可从已有命名报告匹配 78 个 control 和 112 个 generated，112 个 generated 均有 pass/fail。剩余 16 个 generated 没有因此被认定执行。这个检查没有用到目标 ID 或 failure 文本，也没有把同组其它测试的 skip 当作该候选的 outcome。

通用修复在 `relation_search/feedback.py` 增加 `match_declared_tests`：只规范化首尾空白，保留内部空白；若不同 runtime 记录归一化为同一个声明身份则拒认并报告歧义，不能从 pass/fail 中任挑一个。不同标准参数/子测试后缀仍分别归属。进一步审查还补全多声明检查：声明 A、B 但只有 A 的命名事件时，保留 A 作诊断并报告 `missing_declared_test_id`，禁止将该 control 批次的 B 也判为通过。八个新增 toy 加四个 gate toy 和六个 loop 测试，共 18 通过。

## v2 的对照要求

新版本单独读取 v1 已冻结的同一 11-round inventory 和原执行报告，在新目录重建反馈，再重新分配预算。它不修改已冻结主臂、原 feedback 或 v1 结果，也不因为缺失报告而新增执行事实。v2 的增益如有，应归为运行结果归属修复或预算重新分配，不是新的 LLM 推理收益；目标材料曝光仍需封存后由独立评价端检查，正确 oracle 与 issue 检出仍需要另外验证。

v2 已封存于 `results/relation_search_20260929_v3/executed_oracle_budget_v2/seal.json`。同一 1,230 个输入中，921 个具有有效执行与 control，65 个执行但 control 未确认，244 个仍为 unknown。未筛选和筛选两组都实际分配了 176 个请求机会，58 个候选成员不同。N10 的原输入分布恢复为 108 个有效、1 个 control 未确认、19 个 unknown，因而获得 16 个名额。上述 112 个命名 generated run 与这里 109 个已认定执行的原候选属于不同计数单位：run 还可能包含语义修订，不能直接混为同一分母。

筛选带来的未知风险仍存在：若编译或执行归属暂时未知，硬资格门槛可能推迟实际可修复的测试；source control 未确认也不证明新输入的语义不合法。全部未入选原候选因此继续保留为 pending，当前结果只用于比较展示机会，没有接入生产选择器。

## v3：补全声明集合检查后重新封存

v2 封存之后，上述 A/B 缺事件的通用审查又修复了匹配完整性，因此重新使用同一 v1 inventory 独立生成 `results/relation_search_20260929_v3/executed_oracle_budget_v3/seal.json`，未修改 v1/v2。v3 是最终静态审计版本；这一补全不改变当前样本的统计：仍为 921 个有资格、65 个 control 未确认、244 个 unknown，两个当前代码对照均为 176 个机会、58 个成员不同。后验目标曝光应基于 v3；本报告没有将展示机会改变量解释为 oracle 准确性或 issue resolution 增益。
