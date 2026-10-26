"""Persist the investigator's explicit, offline semantic review.

These are judgments made by Codex after reading requirements, both patches,
generated tests and execution records. This is NOT an automatic judge and NOT
independent human annotation. No online experiment imports this file.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "experiments/validation_evolution/results/pilot12_20261016_v3"
ORIGINAL = "experiments/relation_distinction/results/pilot30_20261007_v1/cases"
GOLD = str((RUN / "evaluation/gold_sources").relative_to(ROOT))


def read(path):
    return json.loads(path.read_text())


def main():
    inventories = {str(p): read(p / "evaluation/inventory.json") for p in [RUN, RUN / "observation_view"]}
    rows = {r["key"]: r for inv in inventories.values() for r in inv["targets"]}
    judgments = {}

    def mark(keys, reason, category, detection=False, generation=False, evidence=(), fixed=(), uncertain=False):
        for key in keys.split():
            assert key in rows and key not in judgments, key
            row = rows[key]
            assert row["target"]["decision"] == "gap", key
            root = RUN / "observation_view" if row["arm"] == "E_observations" else RUN
            pair = root / row["execution_path"] / "comparison.json"
            dynamic = pair.exists() and read(pair)["counts"]["differential_witness"] > 0
            judgments[key] = {
                "detection": "repair_relevant_gap" if detection else ("unresolved" if uncertain else "rejected_repair_relevant_claim"),
                "generation": "correct_repair_relevant_test" if generation else "not_a_correct_repair_relevant_test",
                "generation_evidence": ("dynamic_pair" if dynamic else "static_semantics") if generation else None,
                "detection_evidence": "dynamic_pair" if dynamic else "static_semantics",
                "false_positive": None if uncertain else not detection,
                "fixed_hits": list(fixed), "category": category, "reason": reason,
                "evidence": [str((root / row["execution_path"] / "feedback.json").relative_to(ROOT)), *evidence],
                "reference_comparison": str(pair.relative_to(ROOT)) if pair.exists() else None,
                "original_execution_status": row["feedback"].get("status"),
                "private_helpers_policy": "Do not execute original-only helpers on gold; inspect their semantic effect instead.",
            }

    def paths(cid, *names):
        return [f"{prefix}/{cid}/{name}" for prefix in [ORIGINAL, GOLD] for name in names]

    # T05: distinguish missing interaction from a stronger, unsupported oracle.
    mark("T05/A_final/1/h1 T05/A_final/2/h1 T05/B_versions/1/h1 T05/B_versions/2/h1 T05/C_history/1/h2 T05/C_history/2/h2 T05/D_probe/1/h2 T05/D_probe/2/h2 T05/E_observations/1/h2 T05/E_observations/2/h2",
         "要求保留命名快照。两个补丁都在没有未命名快照时停止淘汰。测试额外要求硬上限，不能作为原补丁失败且 gold 通过的证据。", "unsupported_oracle", evidence=paths("T05", "aiomonitor/monitor.py"))
    mark("T05/A_final/1/h2 T05/C_history/1/h1 T05/C_history/2/h1 T05/D_probe/1/h1 T05/D_probe/2/h1 T05/E_observations/1/h1 T05/E_observations/2/h1",
         "字符串 abc 触发 ValueError，gold 的字典查找会触发 KeyError。这个差异只需要一个非法 ID。当前候选没有指出两个独立行为的交互。ID 参数还标注为 int。因此不计为组合缺口，也不把它称为虚构的代码差异。", "outside_combination_scope", evidence=paths("T05", "aiomonitor/monitor.py"))
    mark("T05/A_final/1/h3", "未挂接任务工厂时，结束的任务没有进入监控记录。测试先要求存在该结束任务，再检查时间字段。前置条件没有成立。", "condition_not_established", evidence=paths("T05", "aiomonitor/monitor.py"))
    mark("T05/A_final/2/h2", "两个补丁对 common 项使用不同快照中的名称。但需求只规定按对象 ID 划分 added、removed、common，没有规定 common 的名称来自哪一端。缺少独立依据，保留为未定，不计为已证实误报或成功。", "contract_underdetermined", uncertain=True, evidence=paths("T05", "aiomonitor/monitor.py"))

    mark("T06/A_final/2/h1", "生成测试在两个补丁上都通过。目标没有揭示原补丁缺陷，也没有命中多次路由复制的既定缺口。", "original_already_satisfies")
    mark("T06/C_history/2/h1 T06/D_probe/2/h1 T06/E_observations/2/h1", "路由定义在变量 outer 指向的路由器上，再把它包含进 inner。最近的配置来自路由定义处的 2030。模型按变量名判断嵌套层级，错误要求 2031。两个补丁都拒绝这个断言。", "wrong_relation_direction")

    mark("T09/A_final/1/h2", "别名与额外字段收集的组合在两个补丁上都通过。缺少失败见证。", "original_already_satisfies")
    mark("T09/A_final/2/h3", "被 skip 的字段不进入有效名称布局。两个补丁都不将它与活动字段判为冲突。测试对已跳过字段增加了未确定的冲突要求。", "unsupported_oracle")
    mark("T09/B_versions/1/h1", "别名与另一字段的主键冲突，应在创建 loader 时拒绝。模型要求进入加载阶段后才报多键错误。原补丁和 gold 都在创建时正确拒绝。", "wrong_failure_phase")
    mark("T09/C_history/2/h3 T09/E_observations/2/h3", "DebugTrail.ALL 返回嵌套异常组。测试在外层异常对象上读取路径，未检查叶子错误。FIRST 对照通过；两个补丁都拒绝外层路径断言。不能据此断言别名路径丢失。", "wrong_observation_object")

    mark("T10/A_final/1/h1", "原实现恢复每个文件的缓存 metrics，再统一 aggregate；没有发现所称的双文件指标丢失。测试还把带 self 的方法追加到模块顶层，执行停在 fixture self 不存在。", "original_satisfies_and_bad_scope", evidence=paths("T10", "bandit/core/manager.py"))
    mark("T10/A_final/1/h2", "原 import_ 会合并同键下 files，并仅在目标指纹为空时采用导入指纹。所称缺陷与实现相反。生成方法又在类作用域之外使用 self。", "original_satisfies_and_bad_scope", evidence=paths("T10", "bandit/core/cache.py", "bandit/core/cache_manager.py"))
    mark("T10/A_final/1/h3", "原 CLI 已令 warm_cache 强制 incremental=True，符合候选最终要求。测试没有进入该逻辑，先因模块顶层 self 参数失败。", "original_satisfies_and_bad_scope", evidence=paths("T10", "bandit/cli/main.py"))
    mark("T10/B_versions/1/h1 T10/B_versions/1/h2 T10/B_versions/2/h1", "混合命中/未命中的指标比较或导入覆盖测试已在原补丁通过。模型仍声明 gap。没有修复相关失败。", "original_already_satisfies")
    mark("T10/B_versions/1/h3", "有效目标是 warm-cache、summary 和真实输入文件共存。原 CLI 在 summary 分支提前退出，未预热；gold 仅在无 targets 时走独立 summary 分支。有 targets 时继续预热。生成测试又要求旧 summary 文本和原实现私有文件名 cache.json；gold 使用 cache_data.json。因此目标正确，当前完整测试不正确。", "correct_target_wrong_oracle", detection=True, evidence=paths("T10", "bandit/cli/main.py", "bandit/core/cache_manager.py"))
    mark("T10/B_versions/2/h2", "原补丁把强制重扫记为 not_cached，gold 绕过查询且不增加该计数。需求没有明确强制重扫的计数口径。测试还要求 cache_misses=1，而 gold 的内部 miss 计数为 0。此候选需要独立规范确认，不计为成功或已证实误报。", "contract_underdetermined", uncertain=True, evidence=paths("T10", "bandit/core/manager.py", "bandit/core/cache_manager.py"))
    mark("T10/B_versions/2/h3", "测试局部 import bandit 覆盖了文件中 CLI 模块的别名，bandit.main 不存在。原 CLI 的预热路径已有缓存保存逻辑。这个失败没有证明缓存未写入；候选也没有给出独立组合条件。", "wrong_binding_and_noncombination", evidence=paths("T10", "bandit/cli/main.py"))

    mark("T11/A_final/2/h2", "根元素替换不自动删除文档级处理指令。gold 的元素替换也保留这些兄弟节点。整篇文档字符串相等超出了当前元素差异的支持范围。", "reference_also_rejects", evidence=paths("T11", "patch.go"))
    mark("T11/A_final/2/h3", "ours 修改 a，theirs 删除 b。两个操作作用于不同节点。测试却要求恰好一个 modify-delete 冲突。它没有建立冲突关系。", "wrong_relation_identity", evidence=paths("T11", "merge.go"))
    mark("T11/B_versions/1/h1 T11/B_versions/2/h1 T11/C_history/1/h1 T11/C_history/2/h1 T11/D_probe/1/h1 T11/D_probe/2/h1 T11/E_observations/1/h1 T11/E_observations/2/h1", "原补丁的移动组合确实会复制或丢失兄弟元素。但是 gold 的 OpMove 也转换为 remove/add；parseAddSelector 返回原路径且不实现位置插入。gold 不能满足这份交换测试。因此这是值得保留的通用缺陷线索，但不计入本轮修复相关成功。", "real_issue_reference_not_fixed", evidence=paths("T11", "patch.go", "diff.go"))
    mark("T11/B_versions/2/h3", "一次删除同时遇到属性修改和子节点增加。测试要求只报告一个 structural 冲突，并删除父节点。gold 分别处理修改路径和结构路径，未解决的冲突保留基线内容。该整套断言没有 gold 支持。", "unsupported_conflict_oracle", evidence=paths("T11", "merge.go"))
    mark("T11/D_probe/1/h2", "增加 b 与将 a 替换为 x 可作用于不同节点。测试把这两个修改当作必须互斥的冲突。gold 按操作路径处理，不能支持恰好一个冲突且删除 x 的全部要求。控制测试的两个同路径增加也不保证零冲突。", "unsupported_conflict_oracle", evidence=paths("T11", "merge.go", "diff.go"))
    mark("T11/C_history/2/h2 T11/D_probe/2/h2 T11/E_observations/2/h2", "先向 /r[1] 加入 c，再应用反向补丁。原 ReversePatch 删除父节点 r。gold 根据被添加子节点生成 /r[1]/c，再由 ApplyPatch 删除 c，得到原文档 <r/>。mustDoc/docStr 只封装解析和序列化。静态语义支持目标与测试；按用户要求不执行这些原补丁新增辅助函数的 gold 版本。", "correct_composition", detection=True, generation=True, evidence=paths("T11", "reverse.go", "patch.go"))

    mark("T13/A_final/1/h1 T13/B_versions/1/h1 T13/B_versions/2/h1 T13/B_versions/2/h3", "目标跨越不同编译布局，并按全局变量名称期待重绑定。两个实现都保留函数指令中的全局槽位索引。gold 也不重写为目标程序的同名槽位。B/2/h3 的裸函数对照同样失败，不能归因于嵌套数组。", "reference_also_rejects", evidence=paths("T13", "call.go", "objects.go", "script.go"))
    mark("T13/B_versions/1/h2 T13/B_versions/2/h2 T13/C_history/1/h1 T13/C_history/2/h1 T13/D_probe/2/h1 T13/E_observations/1/h1 T13/E_observations/2/h1", "两个不同闭包共享同一捕获变量。整体转移后，inc 的写入应由 get 读到。原补丁按函数分别复制捕获值，原执行显示 inc 更新而 get 保持旧值。gold 的 compiledCloneState 用 pointers 映射复制 ObjectPtr，两个闭包复用同一新指针。runCompiled/compiledFn 是薄的构建和取值辅助函数。按用户要求，仅对 gold 做静态语义判断。", "correct_shared_identity", detection=True, generation=True, fixed=["T13-R1"], evidence=paths("T13", "call.go", "script.go", "objects.go"))

    mark("T14/B_versions/2/h1", "原 PublishAttempts 直接断言 []PublishAttempt，JSON 解码后的 []interface{} 会被丢弃。gold 用 tryCastExtra 恢复类型，确有语义差异。但需求要求发布输出排序，没有明确要求读回接口。生成测试还要求 AddPublishAttempt 后立刻排序；gold 在显式 SortPublishAttempts 阶段排序。当前完整测试不满足 gold 通过条件。保留读回差异作为未定范围候选。", "contract_underdetermined", uncertain=True, evidence=paths("T14", "internal/artifact/artifact.go", "internal/artifact/publish_attempts.go"))

    mark("T17/A_final/1/h1 T17/C_history/1/h1 T17/D_probe/1/h1 T17/E_observations/1/h1", "需求规定仅在字段或位置不存在时采用默认值。生成测试将实际存在的值设为 undefined。相同测试在原补丁失败，在 gold 通过。它命中存在性与取值被混同的既定目标。", "correct_presence_distinction", detection=True, generation=True, fixed=["T17-R1"])
    mark("T17/A_final/2/h1 T17/A_final/2/h2", "生成测试在两个补丁上均通过。没有证据表明不可变数组 rest 或默认值引用前一绑定存在该缺陷。", "original_already_satisfies")
    mark("T17/A_final/2/h3", "候选要求嵌套 rest 使用特定的不同错误文本。需求未规定该文本。没有证据表明它构成可修复的行为组合缺口。", "unsupported_diagnostic_oracle")
    mark("T17/C_history/2/h1 T17/D_probe/2/h1 T17/E_observations/2/h1", "代码先 out=a，再 out=len(rest)。空 rest 的长度是 0。测试却要求最终 out 为 9。两个补丁都失败，原因是断言观察了被覆盖后的值；不是默认值与 rest 的实现错误。", "asserted_value_overwritten")

    mark("T23/A_final/1/h2", "候选要求初始化图必须穿过无 initializer 的节点检查环。gold 同样只保留有 initializer 的直接依赖，运行时解析 a→b→a 仍失败。动态 gold 比较还因原新增测试文件中的类型差异无法收集测试，不能据此计成功。", "reference_also_rejects", evidence=paths("T23", "src/container.ts"))
    mark("T23/B_versions/2/h1", "c 没有依赖 a，因此它与 a 同在第 0 层。c 在第 0 层失败后，b 所在的下一层不会启动。测试要求 initialized b 出现，实际没有建立 b 与 c 同层并行的条件。gold 也逐层等待。", "condition_not_established", evidence=paths("T23", "src/container.ts"))
    mark("T23/E_observations/2/h3", "a→b→a 是实际对象解析环。b 没有 initializer 不会消除对象依赖环。要求 initialize 成功不成立。", "wrong_relation_abstraction", evidence=paths("T23", "src/container.ts"))

    mark("T24/A_final/1/h2 T24/A_final/1/h3 T24/A_final/2/h3 T24/E_observations/1/h2 T24/E_observations/1/h3", "测试先因 anyOf 或 number 未导入而失败。静态检查也不支持所称缺口：anyOf 委托元素的 map 解析、JSON Schema 或 Zod 处理；这些 map 处理会检查 requiredIf。DTO 路径明确复制 requiredIf，discriminate 保留已有属性。相关可执行 C 组测试已在原补丁通过。", "missing_import_and_wrong_delegation", evidence=paths("T24", "src/schema/actions/parse/anyOf.ts", "src/schema/actions/parse/map.ts", "src/schema/actions/jsonSchemer/formattedValue/anyOf.ts", "src/schema/actions/fromDTO/fromSchemaDTO/anyOf.ts"))
    mark("T24/C_history/1/h1 T24/E_observations/1/h1", "测试对普通字符串使用不受该入口支持的 $set 扩展，先被类型检查拒绝。即使写入被支持，同次更新提供有效依赖值也不等于依赖缺失。测试要求额外 attribute_exists，没有独立要求支持。", "unsupported_input_and_oracle")
    mark("T24/C_history/1/h2 T24/C_history/1/h3", "原补丁已通过这些 anyOf Zod 或 DTO 测试。委托调用保留了规则。不能因当前函数体没有直接调用 requiredIf 检查就断言缺失。", "original_already_satisfies")
    mark("T24/E_observations/2/h2", "formatter 先用 z.preprocess 解码保存名，再进入 withRequiredIf；parser 先检查解码输入，再编码名称。模型颠倒了包装函数的实际执行顺序。测试同时缺少 ZodSchemer 导入。", "wrong_composition_order", evidence=paths("T24", "src/schema/actions/zodSchemer/formatter/map.ts", "src/schema/actions/zodSchemer/formatter/utils.ts", "src/schema/actions/zodSchemer/parser/map.ts"))

    mark("T28/A_final/1/h2 T28/A_final/2/h3", "持久化输入没有 data。两个实现都在恢复入口跳过无 data 的记录；没有进入候选描述的现存数据/错误合并。该测试不满足本轮 gold 通过标准。", "input_filtered_before_target", evidence=paths("T28", "packages/query-persist-client-core/src/createPersister.ts", "packages/query-persist-client-core/src/restore.ts"))
    mark("T28/A_final/2/h1 T28/A_final/2/h2", "A/2/h1 区分两条恢复语义：明确返回恢复标记时，应采用给定状态；原实现却复用批量合并，保留较新 live data。gold 标记路径直接 setState。A/2/h2 组合新持久化错误与两端 false 的 invalidation；原实现额外把 error!=null 当作 invalidation，gold 只合并两端标记。辅助函数只构造状态和存储。两份测试在原补丁真实失败，gold 侧以静态语义确认。它们没有执行框架挂载，因此不算 T28-R1。", "correct_restore_path_distinction", detection=True, generation=True, evidence=paths("T28", "packages/query-core/src/query.ts", "packages/query-core/src/persister.ts", "packages/query-persist-client-core/src/restore.ts"))
    mark("T28/B_versions/1/h1 T28/B_versions/2/h1 T28/E_observations/1/h1", "errorState 辅助函数固定写入 fetchFailureCount=2。测试没有把它改成目标要求的 5 或 3，却断言这些值。原补丁实际保留了输入中的 2。gold 也读取持久化计数。", "helper_does_not_establish_condition", evidence=paths("T28", "packages/query-persist-client-core/src/__tests__/persisterRestoreResult.test.ts", "packages/query-core/src/query.ts", "packages/query-persist-client-core/src/restore.ts"))
    mark("T28/B_versions/2/h2", "persistedQuery 使用 JSON.stringify。new Error('persisted-error') 会被序列化为 {}，测试随后要求 error.message 存在。两个补丁都不能恢复序列化前丢失的 message。代码实际保留的错误对象不是模型声称的字符串错误。", "serialization_loses_condition", evidence=paths("T28", "packages/query-persist-client-core/src/__tests__/persisterRestoreResult.test.ts"))
    mark("T28/C_history/1/h1 T28/C_history/2/h2 T28/D_probe/2/h2 T28/E_observations/2/h2", "需求要求按错误时间选择错误元数据。候选却要求保留数值更大的 live failureCount。两个补丁都选择较新持久化错误对应的计数。辅助函数还固定输出 2，而模型声称输入为 1 或 3。", "wrong_freshness_oracle", evidence=paths("T28", "packages/query-core/src/query.ts", "packages/query-persist-client-core/src/restore.ts"))
    mark("T28/C_history/1/h2 T28/E_observations/1/h2", "原补丁的 fetchInfiniteQuery 恢复错误与分页状态组合已通过 C/1/h2 测试。E 的同类测试因 queryClient 未定义而失败。没有发现该目标上的实现差异。", "original_already_satisfies")
    mark("T28/C_history/1/h3 T28/E_observations/1/h3", "候选直接调用原补丁新增 Query.restore，未指定公开的恢复标记路径。按对应的批量恢复语义，gold 也对两端 invalidation 做 OR。E 还把时间设为 5000，早于真实 live 时间，却声称持久化更新。不能把缺少同名私有方法当作 gold 通过。", "private_path_and_wrong_timestamp", evidence=paths("T28", "packages/query-core/src/query.ts", "packages/query-persist-client-core/src/restore.ts"))
    mark("T28/C_history/2/h3 T28/D_probe/2/h3 T28/E_observations/2/h3", "输入明确令 live data 时间更新。需求要求保留更新的 data 及其 pageParams。测试反而要求采用较旧持久化 pages/pageParams。两个实现都应拒绝该断言。", "wrong_freshness_oracle", evidence=paths("T28", "packages/query-core/src/query.ts", "packages/query-persist-client-core/src/restore.ts"))

    mark("T29/A_final/1/h1 T29/A_final/2/h1 T29/A_final/2/h3 T29/B_versions/2/h2", "原实现每次运行 tracking query 时重新计算当前谓词，并与保留的状态比较。所给单次改变和关系过滤条件可正确处理。相关 C 组控制已通过。当前生成代码还把依赖 describe 内部 world 的测试追加到外部，首先触发 ReferenceError。", "original_satisfies_and_bad_scope", evidence=paths("T29", "packages/core/src/query/query.ts", "packages/core/src/query/utils/check-query-predicate-tracking.ts"))
    mark("T29/A_final/1/h2", "有效目标是两次查询之间发生 true→false→true：先移除依赖，再重新加入。原实现仅比较查询时的真值，错过中间的 false。gold 在 removeTraitFromEntity 中记录 Removed 事件，再次 add 不清除该事件。静态语义支持检测。生成代码的 world 不在作用域内，实际只产生 ReferenceError，故补测失败。", "correct_event_sequence_bad_scope", detection=True, evidence=paths("T29", "packages/core/src/query/utils/check-query-predicate-tracking.ts", "packages/core/src/query/query.ts", "packages/core/src/trait/trait.ts"))
    mark("T29/A_final/1/h3", "混合 Or 的问题有代码依据：原实现把 plain 条件与 tracking 条件分开约束。但 gold 的 tracking 初始填充也仅加入 tracking 匹配项，不能保证 plain-only 实体进入结果。因此不满足 gold 通过标准。生成代码另有 world 作用域错误。", "real_issue_reference_not_fixed", evidence=paths("T29", "packages/core/src/query/query.ts"))
    mark("T29/A_final/2/h2", "Removed 查询第一次注册前没有该查询的基线。两个实现均不能凭新建查询追溯此前的丢失事件。候选把存在一个谓词对象等同于已经注册并观察查询。", "missing_observation_baseline", evidence=paths("T29", "packages/core/src/query/query.ts"))
    mark("T29/B_versions/1/h1 T29/B_versions/2/h1", "迭代集合为 query(isHealthy(), Health)。b 初始不健康，所以没有进入回调。代码从未把 b 变健康，却要求结果包含 b。world 的作用域错误发生得更早。", "condition_not_established", evidence=paths("T29", "packages/core/src/query/query-result.ts"))
    mark("T29/B_versions/1/h2", "这个候选混合两个要求。中间 remove/add 事件值得保留；但首段额外要求 destroy 后 Removed 不包含旧实体，gold 的 removeTrait 会记录该事件。整个候选及测试不能满足 gold 通过。生成测试另有 world 作用域错误。", "mixed_valid_and_invalid_target", evidence=paths("T29", "packages/core/src/entity/entity.ts", "packages/core/src/trait/trait.ts"))
    mark("T29/B_versions/1/h3 T29/B_versions/2/h3", "每次调用 isHealthy() 都产生不同谓词实例。测试重复创建实例，却期待后一次沿用前一次的查询基线。需求明确每次调用返回不同实例。共享同一实例的 C/1/h3 已通过。当前测试另有 world 作用域错误。", "object_identity_not_preserved")
    mark("T29/C_history/1/h1 T29/C_history/1/h2 T29/C_history/1/h3", "这些补测在原补丁通过。单次依赖删除、迭代后查询或关系过滤没有揭示所称原补丁错误。", "original_already_satisfies")
    mark("T29/C_history/2/h1 T29/E_observations/2/h1", "updateEach 退出时把回调的 health 对象写回，覆盖回调中 entity.set 的修改。普通谓词控制也失败。gold 执行相同测试同样失败。不能归因于仅 tracking 谓词的延迟更新。", "control_also_fails_reference_not_fixed")
    mark("T29/C_history/2/h2 T29/E_observations/2/h2", "销毁实体产生 Removed/Changed 事件。测试只断言数组为空，没有验证数组中的实体是否为新实例，也没有验证所称完整 ID 复用。gold 同样拒绝该断言。不能将记录旧删除事件直接视为新实体继承状态。", "wrong_observation_identity")

    for key, row in rows.items():
        if key in judgments:
            continue
        if row["target"]["decision"] == "gap":
            raise AssertionError("Unreviewed affirmative target: " + key)
        judgments[key] = {
            "detection": "no_affirmative_gap", "generation": "not_claimed",
            "false_positive": False, "fixed_hits": [], "category": row["target"]["decision"],
            "reason": "最终输出没有声明修复相关组合缺口。这不是证明任务不存在缺口，也不自动接受模型给出的 selection/oracle 分类。固定目标的漏检由独立标签计算。",
        }

    # paths() above accepts repository-relative names. Original trees have one
    # extra repository component, unlike materialized reference trees.
    for judgment in judgments.values():
        judgment["evidence"] = [e[:len(ORIGINAL)+4] + "/repository" + e[len(ORIGINAL)+4:] if e.startswith(ORIGINAL+"/T") else e for e in judgment.get("evidence", [])]
        judgment["evidence"] = [e for e in judgment["evidence"] if (ROOT / e).is_file()]

    for name, inv in inventories.items():
        task_labels = {}
        for task in inv["tasks"]:
            if not task["final"].get("targets"):
                task_labels[task["key"]] = {
                    "status": "technical_unknown" if task["technical_unknown"] else "no_affirmative_output",
                    "reason": "未得到满足输出格式及目标约束的最终结果。保留在任务分母中；不等同于判断没有缺口。",
                }
        result = {"created_at": datetime.now(timezone.utc).isoformat(),
                  "reviewer": "Codex individual evidence-based semantic assessment; no independent human annotator.",
                  "scope": "Final outputs only. Original-only helpers receive static reference assessment. No modified test is credited.",
                  "targets": {r["key"]: judgments[r["key"]] for r in inv["targets"]}, "tasks": task_labels}
        dest = Path(name) / "evaluation/review.json"
        dest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"run": Path(name).name, "reviewed_targets": len(result["targets"]),
                          "affirmative": sum(r["target"]["decision"] == "gap" for r in inv["targets"]),
                          "unresolved": [k for k, v in result["targets"].items() if v["detection"] == "unresolved"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
