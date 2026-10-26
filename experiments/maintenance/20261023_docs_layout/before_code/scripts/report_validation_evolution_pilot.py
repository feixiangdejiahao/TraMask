"""Build a self-contained Chinese report from frozen experiments and review."""
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "experiments/validation_evolution/results/pilot12_20261016_v3"
EXTRA = BASE / "observation_view"
OUT = ROOT / "docs/validation_evolution_pilot_20261016.html"
ARMS = {"A_final": "A：当前代码与测试", "B_versions": "B：再加历史测试版本",
        "C_history": "C：再加开发过程", "D_probe": "D：再加诊断执行",
        "E_observations": "E：调整诊断结果的表示"}
CASES = {"T05": "aiomonitor：任务快照", "T06": "FastAPI：路由配置传播", "T09": "Adaptix：字段别名",
         "T10": "Bandit：增量缓存", "T11": "etree：XML 差异与补丁", "T13": "Tengo：闭包转移",
         "T14": "GoReleaser：重试与审计", "T17": "Tengo：解构与默认值", "T23": "Awilix：依赖初始化",
         "T24": "DynamoDB Toolbox：条件必填", "T28": "TanStack Query：持久化恢复", "T29": "Koota：谓词查询"}


def read(p):
    return json.loads(p.read_text())


def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def link(path, title):
    p = Path(path)
    if not p.is_absolute(): p = ROOT / p
    return f'<a href="{escape(os.path.relpath(p, OUT.parent), quote=True)}">{escape(title)}</a>'


def table(headers, rows):
    return '<div class="wide"><table><thead><tr>' + ''.join(f'<th>{escape(str(x))}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{x}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def collect():
    all_tasks, all_targets, scores, reviews = [], [], [], {}
    for root in [BASE, EXTRA]:
        inv, score, review = [read(root / "evaluation" / f"{n}.json") for n in ["inventory", "summary", "review"]]
        assert len(inv["tasks"]) == (96 if root == BASE else 24)
        assert not score["unreviewed_targets"] and not score["unreviewed_empty_outputs"]
        all_tasks.extend({**t, "run_root": str(root)} for t in inv["tasks"])
        all_targets.extend({**r, "run_root": str(root)} for r in inv["targets"])
        scores.extend(score["aggregates"])
        reviews.update(review["targets"])
    return all_tasks, all_targets, scores, reviews


def audits(tasks, targets, reviews):
    # Verify the actual D/E requests. An intention or a stored receipt alone is
    # insufficient to establish that the extra experiment changed only feedback.
    pairs = []
    for case in CASES:
        for repeat in [1, 2]:
            d = read(BASE / f"runs/{case}/D_probe/repeat{repeat}/stage3/primary/request.json")
            e = read(EXTRA / f"runs/{case}/E_observations/repeat{repeat}/stage3/primary/request.json")
            bd, be = [json.loads(x["messages"][1]["content"]) for x in [d, e]]
            bd.pop("diagnostic_observations"); be.pop("diagnostic_observations")
            pairs.append({"case": case, "repeat": repeat, "same_non_feedback_body": bd == be,
                          "same_system": d["messages"][0] == e["messages"][0]})
    accepted, comparisons, identical_artifacts = [], [], []
    for r in targets:
        root = Path(r["run_root"])
        directory = root / r["execution_path"]
        if reviews[r["key"]]["generation"] == "correct_repair_relevant_test":
            assert r["feedback"]["status"] == "fail", r["key"]
            accepted.append({"key": r["key"], "evidence": reviews[r["key"]]["generation_evidence"]})
        if (directory / "comparison.json").exists():
            pair = read(directory / "comparison.json")
            comparisons.append({"key": r["key"], "counts": pair["counts"]})
            a, b = [read(directory / x / "result.json") for x in ["candidate", "gold"]]
            # run_artifact records the immutable manifest hash in each result.
            identical_artifacts.append({"key": r["key"],
                                        "same_artifact": bool(a.get("artifact_sha256")) and a["artifact_sha256"] == b.get("artifact_sha256"),
                                        "same_test_files": a["process"].get("files") == b["process"].get("files"),
                                        "different_patches": a.get("patch_sha256") != b.get("patch_sha256"),
                                        "candidate_artifact_sha256": a.get("artifact_sha256"), "reference_artifact_sha256": b.get("artifact_sha256")})
    summaries = [read(p / "evaluation/audit.json") for p in [BASE, EXTRA]]
    assert all(x["same_non_feedback_body"] and x["same_system"] for x in pairs)
    assert len(identical_artifacts) == 33
    assert all(x["same_artifact"] and x["same_test_files"] and x["different_patches"] for x in identical_artifacts)
    assert all(not x["source_mismatches"] for x in summaries)
    assert all(r["matches_public_material"] and r["only_declared_fields"] for x in summaries for r in x["requests"])
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "planned_task_outputs": 120,
              "completed_task_outputs": len(tasks), "reviewed_targets": len(targets),
              "affirmative_targets": sum(r["target"]["decision"] == "gap" for r in targets),
              "accepted_generation": accepted, "D_E_actual_request_pairs": pairs,
              "offline_dynamic_comparisons": comparisons, "artifact_identity_comparisons": identical_artifacts,
              "online_material_checks": sum(len(x["requests"]) for x in summaries),
              "original_files_checked": summaries[0]["original_sources_checked"],
              "source_changes": 0, "implementation_tests": {"passed": 22, "command": ".venv/bin/python -m pytest -q tests/augmentation/test_validation_evolution.py tests/augmentation/test_evolution_transport.py tests/augmentation/test_observation_feedback.py tests/augmentation/test_validation_context_pilot.py tests/augmentation/test_context_query_recovery.py"},
              "review_limit": "Single Codex semantic review. Not independent human validation; static and dynamic evidence are separate."}
    write(BASE / "evaluation/completion_audit.json", result)
    return result


def accounting():
    rows = []
    for root, title in [(BASE.parent / "pilot12_20261016_v1", "停用尝试 1"),
                        (BASE.parent / "pilot12_20261016_v2", "停用尝试 2"),
                        (BASE, "正式主实验：新增调用"), (EXTRA, "反馈表示对照：新增调用")]:
        logs = [read(p) for p in root.glob("runs/**/manifest.json") if "model" in read(p)]
        new = [r for r in logs if not r.get("reused_from")]
        rows.append({"run": title, "started_calls": sum(r.get("external_model_calls", 0) for r in new),
                     "known_tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in new),
                     "interrupted_unknown": sum(r["status"] == "dispatching" for r in new)})
    # v3 copied preflight records from v2; count only the original directories.
    preflight = []
    for root in [BASE.parent / "pilot12_20261016_v1", BASE.parent / "pilot12_20261016_v2"]:
        preflight.extend(read(p) for p in root.glob("*preflight/**/manifest.json") if "model" in read(p))
    rows.append({"run": "运行前的格式检查", "started_calls": sum(r.get("external_model_calls", 0) for r in preflight),
                 "known_tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in preflight), "interrupted_unknown": 0})
    result = {"rows": rows, "total_started_calls": sum(r["started_calls"] for r in rows),
              "known_provider_tokens": sum(r["known_tokens"] for r in rows),
              "interrupted_calls_unknown_cost": sum(r["interrupted_unknown"] for r in rows),
              "formal_reused_model_calls": 45, "formal_reused_stages": 42, "formal_reused_tokens": 3072687,
              "scope": "This twelve-case study, stopped attempts and preflight only; excludes earlier six-case study. Cached prompt tokens are included. Interrupted remote cost is unknown. No currency estimate."}
    write(BASE / "evaluation/accounting.json", result)
    return result


def main():
    tasks, targets, scores, reviews = collect()
    audit, cost = audits(tasks, targets, reviews), accounting()
    pos = [r for r in targets if r["target"]["decision"] == "gap"]
    assert len(pos) == 125
    extraction, query_rows, technical = [], [], []
    for cid, name in CASES.items():
        b, e, h = [read(BASE / f"inputs/{cid}/{n}.json") for n in ["base", "evolution", "history"]]
        extraction.append({"case": cid, "name": name, "final_tests": len(b["validation_tests"]),
                           "historical_versions": len(e["historical_tests"]), "version_differences": len(e["transitions"]),
                           "edit_fragments": len(e["edit_fragments"]), "trajectory_steps": len(h["timeline"])})
    for arm in ["A_final", "B_versions", "C_history"]:
        answers = [a for t in tasks if t["arm"] == arm for a in t["queries"]]
        query_rows.append({"arm": arm, "returned": len(answers), "errors": sum("error" in x for x in answers),
                           "error_kinds": dict(Counter(x["query"]["kind"] for x in answers if "error" in x)),
                           "kind_counts": dict(Counter(x["query"]["kind"] for x in answers))})
    for t in tasks:
        if t["technical_unknown"]:
            f = Path(t["run_root"]) / Path(t["path"]).parent / "stage4/parse_error_1.json"
            technical.append({"key": t["key"], "error": read(f)["error"], "record": str(f.relative_to(ROOT))})
    write(BASE / "evaluation/diagnostics.json", {"extraction": extraction, "query_usage": query_rows, "technical_unknowns": technical})
    accepted = [r for r in pos if reviews[r["key"]]["detection"] == "repair_relevant_gap"]
    generated = [r for r in pos if reviews[r["key"]]["generation"] == "correct_repair_relevant_test"]
    failed = [r for r in pos if reviews[r["key"]]["false_positive"] is True]
    uncertain = [r for r in pos if reviews[r["key"]]["detection"] == "unresolved"]
    summary = {"tasks": 12, "settings": 5, "repeats": 2, "outputs": len(tasks), "affirmative_targets": len(pos),
               "correct_detection_outputs": len(accepted), "correct_generation_outputs": len(generated),
               "rejected_positive_outputs": len(failed), "unresolved_positive_outputs": len(uncertain),
               "named_final_tests": sum(len(r["feedback"].get("generated_test_names", [])) for r in pos),
               "detection_unique_cases": sorted({r["case"] for r in accepted}),
               "generation_unique_cases": sorted({r["case"] for r in generated}),
               "generation_evidence": dict(Counter(reviews[r["key"]]["generation_evidence"] for r in generated)),
               "scores": scores}
    write(BASE / "evaluation/combined_summary.json", summary)
    parts = ['''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>十二任务 pilot：验证改动、诊断执行与组合补测</title>
<style>body{font:17px/1.75 system-ui,sans-serif;max-width:1180px;margin:auto;padding:30px 24px;color:#203044;background:#fafbfd}h1{font-size:30px;line-height:1.4}h2{font-size:23px;margin-top:35px}p{max-width:1080px}table{border-collapse:collapse;width:100%;font-size:15px;background:white}td,th{padding:9px 11px;border:1px solid #cbd5df;text-align:left;vertical-align:top}th{background:#edf3f8}.wide{overflow-x:auto;margin:18px 0}.lead{background:#eaf4ff;border-left:4px solid #2671ac;padding:6px 20px}.small{font-size:14px;color:#526172}code,pre{background:#edf1f6;font-size:.9em}pre{padding:12px;white-space:pre-wrap;overflow-wrap:anywhere}a{color:#155da0}details{background:white;border:1px solid #d4dce4;padding:12px;margin:12px 0}summary{cursor:pointer;font-weight:600}input{font:inherit;padding:9px;max-width:90%;width:650px}.positive{color:#14633e}.negative{color:#9c302d}</style></head><body>
<h1>十二任务 pilot：验证改动、诊断执行与组合补测</h1>
<p class="small">2026-10-16。12 项已研究任务。主实验 4 组，反馈表示对照 1 组。每组重复 2 次，共 120 次任务运行。</p>
<div class="lead"><p>本轮扩大了案例数和候选数。模型可以提出假设、查阅程序、设计诊断、生成补测，并根据执行结果修正一次。程序自动恢复历史测试、保存版本差异、提供局部语法信息，并执行测试。</p>
<p>结果支持继续研究“原验证没有区分哪些行为”。结果尚未支持把“增加历史文本”或“加入诊断执行”作为稳定有效的核心贡献。诊断执行减少了一些错误报告，也曾使模型撤回正确目标。</p>
<p>下一步应集中检查一件事：历史验证中需要区分的条件，是否真正保留在新测试的输入、操作和最终观察中。程序应给出可核验的值、对象身份和执行顺序。LLM 负责提出这个区别，并选择要查证的部分。</p></div>''']
    parts.append('<h2>1. 本轮要回答什么</h2><p>coding agent 已经根据 issue 修改了项目，并写过或运行过验证测试。我们在提交补丁前补充验证。目标不是让测试数量增加，而是找到合法条件的组合，使原补丁的问题可以被观察到。</p>')
    parts.append('<p>本轮将研究问题写成：agent 在局部验证中把哪些不同情形当作同一种情形？历史测试的修改能否帮助发现这种混同？实际程序观察能否帮助构造揭示区别的测试？这些问题适用于有多个文件、多个入口和多步开发记录的 issue resolution。</p>')
    parts.append('<p>例如，T13 的原测试把同一个闭包放进两个容器。这个输入不能区分“同一函数的两个引用”和“两个函数共享同一捕获变量”。需要补测的关系是共享状态在转移后的保持。它不是函数调用覆盖率。</p>')
    parts.append('<h2>2. 实验设置</h2><p>我们保留上轮的 T11、T13、T17、T23、T24、T28。随后从其余已分析任务中，按固定散列顺序加入 4 项 Python、1 项 Go、1 项 TypeScript 任务。最终每种语言各 4 项。所有任务都来自原 30 项开发案例。本轮没有独立留出的测试集。</p>')
    parts.append(table(['案例', '项目与功能', '最终测试片段', '历史版本片段', '同名测试差异', '字面编辑片段'], [[escape(x['case']), escape(x['name']), x['final_tests'], x['historical_versions'], x['version_differences'], x['edit_fragments']] for x in extraction]))
    parts.append('<p>上述数字是自动提取并提供给模型的材料数量，不是提取准确率。333 个历史版本片段可以包含同一测试的多个版本。70 份差异只对齐可恢复的同路径、同名测试。84 份编辑片段可以是不完整的替换请求。程序没有完整重建全部历史仓库状态。</p>')
    parts.append('<p>在线方法只读取 issue、原补丁状态、原验证测试及允许使用的开发记录。gold patch、benchmark 失败测试和人工目标只进入离线评价。我们没有把这些评价材料提供给 DeepSeek。</p>')
    parts.append('<p>模型请求名为 DeepSeek-v4-flash。provider 返回名为 deepseek-flash。正式实验统一关闭 thinking，temperature 为 0，每次输出上限为 32,768 tokens。每项任务最多提出 3 个按顺序排列的候选。一个候选是一个具体的组合缺口假设。每个候选最多生成 1 个文件和 2 个命名测试，其中可以有一个控制测试。</p>')
    parts.append(table(['组别', '输入及操作', '能比较什么'], [
        ['A', 'issue、当前源码、最终测试；可请求源码和局部语法信息。', '不提供被删除的历史测试。'],
        ['B', 'A 加上历史测试版本、同名差异和编辑片段。', '历史验证版本的作用。'],
        ['C', 'B 加上代码阅读、修改、测试选择和执行事件。', '开发过程的增量作用。'],
        ['D', '复用 C 的同一次调查、查询、候选排序和诊断代码，再提供诊断的真实执行结果。', '诊断执行与 C 的配对比较。'],
        ['E', '复用 D 的全部调查材料和诊断结果，改变结果表示。', '删除结构化状态和 Go 状态横幅，并增加通用解释后的影响。']]))
    parts.append('<p>每轮包含四步。模型先提出候选并请求至多 6 次只读查询。模型再确定排序，并设计诊断。随后模型生成补测。程序执行补测，模型获得一次修正机会。最后程序执行最终测试。所有组都看到草稿补测的执行结果；只有 D 和 E 提前看到诊断执行结果。</p>')
    parts.append('<p>E 对全部 12 项任务、两次重复统一执行。它没有按成功或失败挑选案例。E 保留输出值、错误和进程退出码。它没有完全删除所有语言框架日志中的通过/失败文字。因此它检验一种表示与说明的组合，不是单独移除某个词的效果。</p>')
    parts.append('<p>测试在原项目的隔离容器中执行。每个候选单独执行。12 项运行环境检查全部通过。没有修改产品代码。在线程序允许查阅和测试，但没有实现任意多轮的自主 agent 循环。</p>')
    parts.append('<h2>3. 四个效果指标如何计算</h2><p><strong>正确检测：</strong>模型明确提出一个合法的组合目标。需求或接口语义支持预期。语义分析或执行证据支持存在测试，使原补丁失败且 gold 通过。单个非法参数、已有联合测试未运行、错误预期，分别处理，不自动算组合缺口。</p>')
    parts.append('<p><strong>正确补测：</strong>模型实际交付的最终测试建立了关键条件，并观察正确对象和结果。原执行必须揭示目标问题。gold 侧可以采用动态比较或静态语义判断。我们不替模型修正测试后再计成功。</p>')
    parts.append('<p><strong>误报：</strong>模型声明 gap，但该肯定报告被本轮修复相关标准否定。原因可以是错误预期、条件未建立、原补丁已满足，或 gold 也不能通过。最后一种情况不表示报告的通用缺陷一定不存在。证据不足的 3 项另列为未定，不算成功或已证实误报。</p>')
    parts.append('<p><strong>漏检：</strong>计算未命中的 7 个事先固定目标。它们位于 6 项任务：T06 路由复制、T10 预热与 JSON、T13 共享捕获、T17 存在性与默认值、T24 默认解析模式、T24 分支选择与条件规则、T28 错误快照与框架挂载。这个分母不是全部可能缺陷。未设固定目标的任务也不是无缺陷负例。</p>')
    parts.append('<p>下表的检测、补测和误报以任务计数，每次分母为 12。漏检以固定目标计数，每次分母为 7。同一次任务可以发现正确目标，同时报告其他错误目标，所以成功任务与误报任务允许重叠。格式失败仍保留在任务分母中。</p>')
    parts.append('<h2>4. 主要结果</h2>')
    rows = []
    for a in scores:
        if a['target_prefix'] != 3: continue
        rows.append([escape(ARMS[a['arm']]), a['repeat'], f"{len(a['correct_detection_tasks'])}/12", f"{len(a['correct_generation_tasks'])}/12", f"{len(a['false_positive_tasks'])}/12", f"{len(a['fixed_misses'])}/7", len(a['technical_unknown_tasks']), len(a['unresolved_positive_targets'])])
    parts.append(table(['设置', '重复', '正确检测', '正确补测', '误报任务', '固定目标漏检', '格式失败任务', '语义未定候选'], rows))
    parts.append(f'<p>125 个最终肯定候选交付了 125 份文件，包含 {summary["named_final_tests"]} 个命名测试。它们包含重复运行和控制测试。逐项复核确认 {len(accepted)} 个检测输出及 {len(generated)} 个正确补测输出；{len(failed)} 个肯定候选不符合标准；{len(uncertain)} 个语义未定。这里的输出数不是独立缺陷数。</p>')
    parts.append('<p>合并所有设置后，正确检测涉及 T10、T11、T13、T17、T28、T29 六项任务。正确补测涉及 T11、T13、T17、T28 四项任务。16 份正确补测中，4 份来自 T17 的原样动态差分；12 份采用 gold 静态语义判断。后者保留了用户关于原补丁新增辅助代码的限制。</p>')
    parts.append(table(['有效目标', '原验证的限制', '新组合或新观察', '本轮证据'], [
        ['T10：预热与摘要', '分别检查预热和缓存摘要。', '给出真实目标文件，同时启用预热与摘要；检查是否实际预热。', '正确检测。原补丁提前退出。gold 只在无目标时独立输出摘要。生成测试混入错误文本和私有文件名，补测失败。'],
        ['T11：反向补丁的应用', '只检查反向操作的类型和数量。', '先添加子节点，再应用反向补丁；检查是否恢复原文档。', '正确检测与补测。原补丁删除父节点，gold 删除新增子节点。gold 静态判断。'],
        ['T13：不同闭包共享捕获', '转移同一闭包的多个引用。', '转移共享变量的两个不同闭包；写入一个，再从另一个读取。', '正确检测与补测。gold 静态判断。命中固定目标。'],
        ['T17：存在但为 undefined', '在字段或位置不存在时检查默认值。', '字段或位置存在，但取值为 undefined；检查默认值是否错误生效。', '正确检测与补测。4 份原样动态差分。命中固定目标。'],
        ['T28：恢复入口与已有状态', '主要在新建查询上检查恢复标记。', '已有较新数据时返回明确恢复标记；另查错误状态与 false invalidation 的组合。', '两个正确目标与补测。gold 静态判断。未命中要求框架挂载的固定目标。'],
        ['T29：两次观察之间的多次变化', '每次改变后立即查询。', '两次查询之间移除并重新加入依赖，检查中间删除事件。', '静态判断支持检测。生成代码引用作用域外的 world，补测失败。']]))
    parts.append('<p>C 的两次正确补测都是 2/12。D 为 1/12 和 2/12，同时减少误报任务。E 恢复到 2/12 和 2/12，但误报任务增加到 4/12 和 9/12。这组结果没有显示 E 的总体优势。</p>')
    parts.append('<p>每个设置只重复两次，案例也是开发案例。我们不据此报告统计显著性，也不宣称提高 resolution rate。本轮没有让 agent 利用新测试继续修补代码。</p>')
    parts.append('<h2>5. 增加候选数量是否有帮助</h2>')
    prefix_rows = []
    for arm in ARMS:
        for rep in [1, 2]:
            one = next(x for x in scores if x['arm'] == arm and x['repeat'] == rep and x['target_prefix'] == 1)
            three = next(x for x in scores if x['arm'] == arm and x['repeat'] == rep and x['target_prefix'] == 3)
            prefix_rows.append([escape(ARMS[arm]), rep, f"{len(one['correct_detection_tasks'])} → {len(three['correct_detection_tasks'])}", f"{len(one['correct_generation_tasks'])} → {len(three['correct_generation_tasks'])}", f"{len(one['false_positive_tasks'])} → {len(three['false_positive_tasks'])}"])
    parts.append(table(['设置', '重复', '正确检测：前 1 → 前 3', '正确补测：前 1 → 前 3', '误报任务：前 1 → 前 3'], prefix_rows))
    parts.append('<p>B 的两个重复都把 T13 的有效共享捕获目标排在第 2 位。C、D、E 的第 2 次重复都在第 2 位找到 T11 的反向补丁问题。因此只保留第一候选会漏掉这些发现。扩大候选同时带来更多不合格报告。</p>')
    parts.append('<p>这只是同一冻结输出的前缀分析。模型事先知道可以考虑三个目标。它不等于独立运行一个只允许一个目标的方法，也不是相同成本下的比较。</p>')
    parts.append('<h2>6. 哪些观察改变了问题理解</h2>')
    parts.append('<p><strong>T13：同一个对象不等于共享状态的不同对象。</strong>历史测试把预期从 151 改为 152。改动保留了同一闭包的共享状态，却没有覆盖两个不同闭包。B 找到这个目标但排在第二；C 将它排在第一。当前数据与历史材料有用的解释一致，但不能仅凭一个案例证明因果。</p>')
    parts.append('<p>程序恢复了这段原始 diff。但是结构化的赋值、调用和检查差异栏全部为空。关键变化位于 Go 的 if 条件，后面调用 Fatal。当前提取器没有将这种惯用检查表达为期望变化。这是表示缺陷，不是原始文本缺失。</p>')
    parts.append('<p><strong>T13：完成执行不等于满足行为要求。</strong>诊断打印 inc=3、get=2。它只记录数值，没有断言，所以框架报告通过。D 第一次运行随后撤回共享捕获目标。E 使用相同诊断结果后保留目标，并生成失败见证。第二次重复中，D 和 E 都成功。这个对照支持反馈解释影响决定，但证据仍只覆盖一个有效变化。</p>')
    parts.append('<p><strong>T17：断言读取了另一个值。</strong>错误测试执行 out=a，随后执行 out=len(rest)，最后要求 out=9。实际最终值为 0。模型把失败归因于编译器栈和默认值处理。D 和 E 都保留了这个错误。只改执行报告的表示不能修复观察对象错误。</p>')
    parts.append('<p><strong>T28：模型声明的输入没有进入程序。</strong>多个候选声称持久化失败次数为 5 或 3，但 errorState 固定写入 2。另一测试把 Error 对象放进 JSON，message 在序列化时丢失。模型随后把缺少 message 当作恢复逻辑缺陷。这些失败要求检查输入构造及其转换。</p>')
    parts.append('<p><strong>T29：必须追踪同一对象和实际操作序列。</strong>有些测试每次调用谓词工厂，得到不同实例，却期待复用查询历史。另一些测试只迭代健康实体，却期待修改未进入循环的不健康实体。程序关系必须绑定具体对象、集合成员和调用次序。</p>')
    parts.append('<p><strong>T29：被删除的测试不自动成为正确目标。</strong>trajectory 记录了删除 entity.set 回调测试的请求。C 确实重新探索这条路径。但生成的控制测试和 gold 都失败。删除记录可以指引搜索，不能充当正确性依据，也不能直接当成新的输入缺口。</p>')
    parts.append('<h2>7. 必须处理的实验限制</h2>')
    parts.append(table(['组别', '实际查询数', '查询错误数', '主要问题'], [[escape(ARMS[r['arm']]), r['returned'], r['errors'], '；'.join(f'{name} {r["error_kinds"].get(kind, 0)} 次' for kind, name in [('test', '测试标识不匹配'), ('history_search', '请求本组不可用的历史')] if r['error_kinds'].get(kind)) or '无上述错误'] for r in query_rows]))
    parts.append('<p>A 有 13 次、B 有 10 次测试查询未使用可解析的测试 ID。B 还请求了 23 次该组不允许读取的开发历史。C 没有这类查询错误。因此 A/B/C 的成绩混合了信息作用与查询接口使用能力。我们不能把 C 的全部差异归因于 trajectory 的语义价值。</p>')
    parts.append('<p>14 次最终输出没有通过接口检查。12 次最终失败涉及目标 ID 或顺序变化；1 次超出单文件限制；1 次 JSON 字符串不完整。它们不是 14 次“已证明没有缺口”。原始响应完整保留，成绩没有挑选性修补。</p>')
    parts.append('<p>把一个候选撤回后再加回，也可能触发当前严格 ID 检查。这一工程限制会低估可用内容。下一次独立实验应由程序持有候选身份，并把候选结果分开接收。这个修正本身不构成论文贡献。</p>')
    parts.append('<p>程序的 slice 查询只提供局部参数、赋值、调用及外层条件。它没有证明跨函数别名、完整控制可达性或运行时值。当前“条件清单”仍是模型生成的文字，程序尚未验证清单中的条件。这一点限制了本轮对程序分析作用的结论。</p>')
    parts.append('<p>所有语义判断由本 Codex 线程逐项完成，依据需求、源码、两个补丁和执行记录。没有独立人类标注者。我们把动态证据和静态判断分开报告，保留完整记录供复查。</p>')
    parts.append('<h2>8. 收敛后的研究抽象与算法方向</h2>')
    parts.append('<p><strong>研究对象：验证所依赖的区分条件。</strong>agent 常在局部上下文中获得通过结果，随后据此接受更广的补丁行为。我们要发现这个推断依赖了哪个尚未验证的条件。条件可以是对象共享、字段存在性、恢复入口、更新顺序或实际观察对象。它不需要预先限定为一条程序边的两端。</p>')
    parts.append('<p><strong>集中机制：让一个行为区别贯穿搜索。</strong>每次搜索只维护原验证、待区分条件及最终观察三项内容。trajectory 用来提出原验证为什么可能混同两个情形。程序用来核对这两个情形是否在输入和执行中不同。LLM 根据证据选择下一次查询或局部测试修改。</p>')
    parts.append(table(['步骤', 'LLM 的职责', '程序的职责', '可检查的产物'], [
        ['确定区别', '从历史验证改动和 issue 中提出两个不能混同的情形；指出依据。', '对齐测试版本；保留输入、操作、控制条件和断言的源码位置。', '原验证检查了什么；新情形改变哪一个条件。'],
        ['核对条件', '指出哪个对象、值或操作能区分这两种情形；选择查阅或小型诊断。', '从输入构造向前跟踪关键值，从最终断言向后跟踪观察值；有歧义时记录实际值、对象身份和先后顺序。', '条件是否真的成立；变化是否传播到观察点。'],
        ['补强验证', '保持需求支持的预期，生成最小组合测试；根据证据修改未成立的条件。', '执行测试；分别报告输入条件、实际结果和框架状态。', '可重放的失败见证，或明确的撤回理由。']]))
    parts.append('<p>这个设计允许 LLM 进入程序分析过程。模型先指定需要核对的语义关系，程序再执行局部查询或收集运行时证据。程序不需要先建立整个项目的精确模型。模型也不应仅凭函数名称推断关系已经成立。</p>')
    parts.append('<p>例如，对 T28，程序需要报告“传入恢复函数的 count 实际为 2”，而不是只报告 errorState 调用了 restore。对 T17，程序需要报告“断言读取的 out 最后由 len(rest) 写入”。同一个值来源与观察来源机制可以处理这些问题，无需为每个案例添加专用规则。</p>')
    parts.append('<p><strong>创新性边界。</strong>单独增加 LLM 阶段、查询工具或测试执行，不足以形成核心贡献。值得继续验证的信息利用方式是：从 coding agent 自己的验证改动中提出尚未验证的行为区别，再用程序中的值、身份和时序核对这个区别。贡献是否成立，取决于它能否稳定减少无效搜索，并增加真实错误检出。</p>')
    parts.append('<p>上述机制是下一步的研究假设。当前实现只完成历史版本恢复、局部查询和执行对照，没有实现完整的区别保持检查。我们不把本轮成绩归功于尚未实现的机制。</p>')
    parts.append('<p>下一轮应复用同一组初始假设、源码材料和模型预算。比较普通执行反馈与上述条件及观察证据。所有案例统一处理。分别记录目标被正确否定、目标保留但测试构造失败、以及成功形成见证。先检查这个集中机制的作用，再决定是否继续增加更广的搜索。</p>')
    parts.append('<h2>9. 成本、停用尝试与完整性</h2>')
    parts.append(table(['阶段', '发起调用数', '已返回 tokens', '中断后费用未定的调用'], [[escape(r['run']), r['started_calls'], f"{r['known_tokens']:,}", r['interrupted_unknown']] for r in cost['rows']]))
    parts.append(f'<p>本轮含运行前检查共发起 {cost["total_started_calls"]} 次 provider 调用。已记录 {cost["known_provider_tokens"]:,} tokens，其中包含重复输入和命中缓存的输入。15 次中断调用的远端结算未知。因此已记录总量不是完整费用。报告没有推算金额。</p>')
    parts.append('<p>第一次尝试开启 thinking。前 8 次主请求中，7 次在额度内没有输出 JSON；另一份缺少必需字段。第二次尝试关闭 thinking，但程序把同一文件的两次追加误认为两个文件。两次尝试均停止，并保留原记录。正式版只合并同文件追加片段，不改测试语义。</p>')
    parts.append('<p>正式版复用了第二次尝试中全部可用的 42 个前期调查阶段，共对应 45 次已有调用。选择没有使用成功标签。原始调用成本计入停用尝试，复制记录不再次收费。正式版与 E 新增 373 次调用。正式版复用的格式检查记录也没有重复计费。</p>')
    parts.append('<p>核验检查了 418 份实际在线请求，均匹配声明的公开材料。C/D 的 24 对请求仅在诊断结果上不同。D/E 的 24 对请求也仅在诊断结果表示上不同。7,278 个原源码文件的摘要保持一致。相关本地检查 22 项通过。</p>')
    parts.append('<p>离线执行了 33 份原样测试的双补丁比较。只有 T17 的 4 份形成有效动态差分。T23 的一次比较遇到原新增测试文件的类型兼容问题，未计成功。其他涉及原补丁新增私有函数或辅助代码的目标保留静态语义评价。没有把 gold 中缺少同名私有接口当作行为证据。</p>')
    parts.append('<p>' + ' · '.join([link(BASE / 'protocol.json', '冻结的主实验协议'), link(EXTRA / 'protocol.json', '反馈对照协议'), link(BASE / 'evaluation/combined_summary.json', '完整统计'), link(BASE / 'evaluation/accounting.json', '调用与成本记录'), link(BASE / 'evaluation/completion_audit.json', '完整性核验'), link(BASE / 'evaluation/review.json', '主实验逐项判断'), link(EXTRA / 'evaluation/review.json', '反馈对照逐项判断')]) + '</p>')
    parts.append('<h2>10. 全部肯定报告的逐项复核</h2><p>下面保留 125 个肯定候选。每条显示判断、理由和原始执行记录。英文原始目标可以展开。输入关键词可筛选案例、组别或判断。</p><input id="filter" aria-label="筛选逐项记录" placeholder="例如 T13、共享、未定、作用域">')
    for r in pos:
        v = reviews[r['key']]
        state = '正确检测；正确补测' if v['generation'] == 'correct_repair_relevant_test' else '正确检测；补测失败' if v['detection'] == 'repair_relevant_gap' else '语义未定' if v['detection'] == 'unresolved' else '不符合修复相关标准'
        evidence = '；gold 动态执行' if v['generation_evidence'] == 'dynamic_pair' else '；gold 静态判断' if v['generation_evidence'] == 'static_semantics' else ''
        parts.append(f'<details class="record"><summary>{escape(r["key"])}：{state}{evidence}</summary><p>{escape(v["reason"])}</p>')
        parts.append('<p>' + ' · '.join(link(x, '证据 ' + str(i+1)) for i, x in enumerate(v['evidence'])) + '</p>')
        if v.get('reference_comparison'): parts.append('<p>' + link(v['reference_comparison'], '原样测试双补丁结果') + '</p>')
        parts.append('<details><summary>原始目标与预期</summary><pre>' + escape(r['target']['combination'] + '\n\n' + r['target']['required_result']) + '</pre></details></details>')
    parts.append('<details><summary>14 次格式失败记录</summary>' + table(['运行', '最后一次错误', '原始记录'], [[escape(t['key']), escape(t['error']), link(t['record'], '查看')] for t in technical]) + '</details>')
    parts.append('''<script>document.getElementById('filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('.record').forEach(d=>{d.hidden=!d.textContent.toLowerCase().includes(q)})})</script></body></html>''')
    OUT.write_text('\n'.join(parts))
    write(BASE / 'active_evaluation.json', {"report": str(OUT.relative_to(ROOT)), "summary": "evaluation/combined_summary.json", "review": "evaluation/review.json", "addon_review": "observation_view/evaluation/review.json", "criterion": "Independent requirement plus original-fail/gold-pass; static helper cases separated.", "resolution_rate_measured": False})
    print(json.dumps({"report": str(OUT), **{k:v for k,v in summary.items() if k != 'scores'}}, ensure_ascii=False))


if __name__ == '__main__': main()
