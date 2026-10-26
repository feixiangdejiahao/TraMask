"""Build a self-contained report only after all final claims are reviewed."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.review_augmentation_pilot30_v2 import inventory, OUT
from scripts.run_augmentation_pilot30_v2 import RUN, OLD, read, receipt, check_protocol
from augmentation.pipeline import write_json

REPORT = ROOT / "docs/augmentation_pilot30_v2_20261008.html"


def link(path, label):
    return '<a href="' + escape(os.path.relpath(path, REPORT.parent), quote=True) + '">' + escape(label) + '</a>'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th>' + escape(str(x)) + '</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + escape(str(x)) + '</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def build():
    protocol = check_protocol()
    cases = read(RUN / "cases.json")
    claims = inventory()
    reviews = []
    for claim in claims:
        path = OUT / "reviews" / (claim["case"] + "__" + claim["candidate"] + ".json")
        review = read(path)
        assert review["id"] == claim["id"]
        assert review["assessment_sha256"] == claim["assessment"]["sha256"]
        assert review["classification"] in {"true_positive_reference", "true_positive_new_target",
                                             "false_positive_for_fault_revealing_gap", "unresolved"}
        for evidence in review["evidence"]:
            assert receipt(evidence["path"]) == evidence, evidence["path"]
        reviews.append({**review, "case": claim["case"], "review": receipt(path)})
    refs = read(OLD / "benchmark_reverse_v4/combined_targets.json")["targets"]
    assert receipt(OLD / "benchmark_reverse_v4/combined_targets.json") == protocol["reference_labels"]
    ref_ids = {r["id"] for r in refs}
    detected = {x for r in reviews for x in r["detected_targets"]}
    generated = {x for r in reviews for x in r["generated_targets"]}
    assert generated <= detected <= ref_ids
    correct_cases = sorted({r["case"] for r in reviews if r["detection_correct"]})
    generated_cases = sorted({r["case"] for r in reviews if r["generation_correct"]})
    fp = [r for r in reviews if r["classification"] == "false_positive_for_fault_revealing_gap"]
    pending = [r for r in reviews if r["classification"] == "unresolved"]
    extraction, generation_rows, task_rows = [], [], []
    for case in cases:
        directory = RUN / "cases" / case["id"]
        extracted = read(directory / "extraction.json")
        generated_row = read(directory / "generation.json")
        assert generated_row["status"] == extracted["status"] == "complete"
        extraction.append(extracted)
        generation_rows.append(generated_row)
        cr = [r for r in reviews if r["case"] == case["id"]]
        targets = [r["id"] for r in refs if r["case"] == case["id"]]
        task_rows.append({"case": case["id"], "task": case["task"], "language": case["language"],
                          "extracted_tests": extracted["counts"]["tests"],
                          "extracted_candidates": extracted["counts"]["candidates"],
                          "selected_candidates": len(extracted["selected"]),
                          "final_claims": len(cr), "correct_detection": case["id"] in correct_cases,
                          "correct_generation": case["id"] in generated_cases,
                          "false_positive_claims": sum(r in fp for r in cr),
                          "unresolved_claims": sum(r in pending for r in cr),
                          "detected_reference_targets": sorted(set(targets) & detected),
                          "generated_reference_targets": sorted(set(targets) & generated),
                          "missed_reference_targets": sorted(set(targets) - detected),
                          "new_targets": sorted({r["new_eligible_target"] for r in cr if r["new_eligible_target"]}),
                          "statuses": generated_row["statuses"]})
    calls = [read(p) for p in RUN.glob("cases/*/agent/*/round*/manifest.json")]
    results = [read(p) for p in RUN.glob("cases/*/agent/*/result.json")]
    execution = [read(p) for p in RUN.glob("cases/*/agent/*/round*/execution/result.json")]
    actions = [read(p) for p in RUN.glob("cases/*/agent/*/round*/action.json")]
    feedback = [read(p) for p in RUN.glob("cases/*/agent/*/round*/feedback.json")]
    positive_cases = sorted({r["case"] for r in refs})
    recovery_paths = [RUN / "cases/T01/function-record-recovery.json",
                      RUN / "cases/T01/recovery-extraction-receipt.json",
                      RUN / "cases/T19/text-hash-recovery.json"]
    harness_recoveries = [read(p) for p in OUT.glob("harness_recovery/*/*/candidate/result.json")]
    valid_passing = {"valid_augmentation_without_original_patch_defect", "valid_passing_supplement",
                     "valid_passing_supplement_after_harness_recovery"}
    def exclusion_group(review):
        if review["subtype"] in valid_passing:
            return "valid_test_passes_original_patch"
        if review["subtype"] == "not_gold_compatible":
            return "gold_does_not_satisfy_generated_expectation"
        if review["subtype"] == "basic_api_error_not_combination":
            return "basic_api_error_not_combination"
        return "test_error_and_no_confirmed_combination_defect"
    assert len(claims) == len(reviews)
    assert len(results) == sum(len(x["selected"]) for x in extraction)
    assert sum(c["external_model_calls"] for c in calls) == sum(g["model_calls"] for g in generation_rows)
    summary = {
        "version": "pilot30-v2-reviewed-results.v1", "status": "complete",
        "report_created_at": datetime.now(timezone.utc).isoformat(),
        "run_started_at": protocol["created_at"], "cases_completed": len(task_rows),
        "correct_detection_tasks": correct_cases, "correct_generation_tasks": generated_cases,
        "correct_detection_task_count": len(correct_cases), "correct_generation_task_count": len(generated_cases),
        "final_claim_count": len(claims), "correct_claim_count": sum(r["detection_correct"] for r in reviews),
        "false_positive_claim_count": len(fp), "false_positive_affected_tasks": sorted({r["case"] for r in fp}),
        "false_positive_groups": dict(Counter(exclusion_group(r) for r in fp)),
        "unresolved_claim_count": len(pending),
        "reference": {"targets": len(refs), "positive_tasks": positive_cases,
                      "detected_targets": sorted(detected), "generated_targets": sorted(generated),
                      "missed_targets": sorted(ref_ids - detected), "missed_target_count": len(ref_ids - detected),
                      "target_recall": len(detected) / len(refs),
                      "detected_tasks": sorted({r["case"] for r in refs if r["id"] in detected}),
                      "tasks_without_reference_hit": sorted({r["case"] for r in refs} - {r["case"] for r in refs if r["id"] in detected}),
                      "known_positive_tasks_without_any_confirmed_detection": sorted(set(positive_cases) - set(correct_cases))},
        "new_targets": sorted({r["new_eligible_target"] for r in reviews if r["new_eligible_target"]}),
        "final_test_execution": dict(Counter(c["run_status"] for c in claims)),
        "offline_harness_recovery_execution": dict(Counter(x["status"] for x in harness_recoveries)),
        "final_claim_rounds": dict(Counter(c["round"] for c in claims)),
        "final_claims_at_last_round": sum(c["round"] == protocol["agent"]["max_rounds"] for c in claims),
        "operational_recoveries": [receipt(p) for p in recovery_paths],
        "offline_harness_recoveries": [receipt(p) for p in sorted(OUT.glob("harness_recovery/*/*/summary.json"))],
        "extraction": {"total_candidates": sum(x["counts"]["candidates"] for x in extraction),
                       "total_selected_candidates": sum(len(x["selected"]) for x in extraction),
                       "total_test_records": sum(x["counts"]["tests"] for x in extraction),
                       "sum_seconds": sum(x["seconds"] for x in extraction)},
        "model": {"requested": protocol["model"], "returned": dict(Counter(c.get("response_model") for c in calls if c.get("response_model"))),
                  "external_calls": sum(c["external_model_calls"] for c in calls),
                  "provider_statuses": dict(Counter(c["status"] for c in calls)),
                  "provider_reported_tokens": sum((c.get("usage") or {}).get("total_tokens", 0) for c in calls),
                  "charged_tokens": sum(r["charged_tokens"] for r in generation_rows),
                  "actions": dict(Counter(a["action"] for a in actions)),
                  "action_error_count": sum(x.get("status") == "action_error" for x in feedback),
                  "action_errors": dict(Counter(x["error"] for x in feedback if x.get("status") == "action_error")),
                  "final_candidate_statuses": dict(Counter(x["status"] for x in results)),
                  "stop_reasons": dict(Counter(x["stop_reason"] for x in results)),
                  "original_patch_execution_attempts": len(execution)},
        "resolution_rate_after_repair": None, "false_positive_rate": None,
        "interpretation": "A correct augmentation reveals an original-patch combination error with gold-compatible semantics. It does not establish a completed repair. The 12 tasks lacking a frozen positive target are not validated negative tasks.",
        "reviewer": "Codex semantic review of every final proposal with execution and static source evidence; no independent human review.",
        "protocol": receipt(RUN / "protocol.json"), "claims": receipt(OUT / "claims.json"),
        "tasks": task_rows, "reviews": reviews,
    }
    write_json(RUN / "summary.json", summary)
    render(summary)
    print(json.dumps({k: summary[k] for k in ("cases_completed", "correct_detection_task_count", "correct_generation_task_count", "false_positive_claim_count", "reference", "new_targets", "model")}, ensure_ascii=False, indent=2))


def render(s):
    ref = s["reference"]
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>30 个任务：改进算法的提取与组合补测结果</title><style>body{max-width:1160px;margin:35px auto;padding:0 20px;font:16px/1.8 system-ui,sans-serif;color:#18252e;background:#fafbfd}table{border-collapse:collapse;background:white;width:100%;font-size:14px}th,td{border:1px solid #d6dfe5;padding:9px;text-align:left;vertical-align:top}th{background:#eaf1f6}.scroll{overflow:auto}details{background:white;border:1px solid #d6dfe5;margin:10px 0;padding:12px}summary{font-weight:bold;cursor:pointer}a{color:#08628e}code{overflow-wrap:anywhere}h1{font-size:28px}h2{font-size:23px}</style><h1>30 个任务：提取与组合补测结果</h1><p>实验启动：2026-10-08。完成及复核：2026-10-09。算法版本：joint-observation-augmentation.v2。T01 使用了下文列出的提取修复。</p>']
    parts.append(f'<p>本轮完成 30 个任务的程序提取和模型处理。方法在 {s["correct_detection_task_count"]} 个任务上正确检测到能揭示原补丁错误的组合缺口，在 {s["correct_generation_task_count"]} 个任务上生成了正确的组合测试。</p>')
    parts.append(table(['指标','结果','计数单位'], [
        ['正确检测', str(s['correct_detection_task_count']) + '/30', '任务。每个任务至少有一项经核验的组合错误。'],
        ['正确补测', str(s['correct_generation_task_count']) + '/30', '任务。生成代码保持不变，并有有效错误断言。'],
        ['误报', str(s['false_positive_claim_count']) + '/' + str(s['final_claim_count']), '最终保留的缺口建议。一项建议可以包含多个测试。'],
        ['漏报', str(ref['missed_target_count']) + '/' + str(ref['targets']), '预先固定的组合错误目标。未知任务不作为负例。'],
    ]))
    parts.append('<p>任务数、建议数和目标数是不同单位。不能直接相加。一个任务可以同时包含正确建议和误报，也可以命中一个目标但漏掉另一个目标。</p>')
    parts.append(f'<p>误报涉及 {len(s["false_positive_affected_tasks"])} 个任务。另有 {s["unresolved_claim_count"]} 项建议仍缺少足够证据；这些建议不计成功，也不强行计为误报。</p>')
    parts.append('<p>这里的“误报”按错误检出目标计数。有效补充测试如果只增加覆盖，却不能揭示所提组合中的原补丁错误，也记为本轮误报。这不表示测试没有覆盖价值。因 gold 也不满足预期而被排除的建议，另列原因，不能直接称为虚假问题。</p>')
    groups = {'valid_test_passes_original_patch':'有效补充测试在原补丁上通过',
              'gold_does_not_satisfy_generated_expectation':'gold 也不满足生成测试的预期',
              'basic_api_error_not_combination':'暴露基本接口错误，未进入所提组合',
              'test_error_and_no_confirmed_combination_defect':'测试自身有错误，语义检查也未确认所提组合错误'}
    parts.append(table(['未计成功的原因','最终建议数'], [[groups[k],v] for k,v in s['false_positive_groups'].items()]))
    parts.append('<h2>实验设置</h2><p>本轮沿用原 pilot 的 30 个 trial。Python、Go、TypeScript 各 10 个。输入包括完成后的原补丁、代码仓库、公开任务要求和原 agent 的 trajectory。程序分析提取相关测试、条件、操作关系及历史信息。模型据此判断缺口并生成补测。</p>')
    parts.append('<p>一个 trial 指原 agent 的一次任务尝试。trajectory 指这次尝试中的代码阅读、修改、测试选择和执行记录。gold 指 benchmark 提供的参考补丁。本轮不重新运行原 agent 的开发过程，而是在其原补丁上执行新增测试。</p>')
    parts.append('<p>每个任务最多保留 400 个程序候选。算法按关系类型和原有优先级自动选择最多 8 个候选。没有人工挑选有利候选。每个候选最多调用模型 3 次，最多执行测试 2 次。每次输出上限为 32,768 token。每个任务总预算为 100 万 token。</p>')
    parts.append('<p>程序分析围绕补丁关联的操作搜索条件组合。搜索深度上限为 6，组合阶数上限为 3。输入保留同一次测试调用中的条件、对象身份、操作顺序和断言。模型可按需查看相关源码和开发历史。程序候选只是待检查的问题，不是已确认错误。</p>')
    parts.append(f'<p>程序共提取 {s["extraction"]["total_test_records"]:,} 条测试记录，保留 {s["extraction"]["total_candidates"]:,} 个候选，并自动选择 {s["extraction"]["total_selected_candidates"]} 个候选交给模型。30 个任务全部完成处理，但部分候选因预算或交互错误而没有形成结论。</p>')
    parts.append('<p>模型可以请求补充源码、测试、程序关系和历史信息。模型也可以运行原测试或生成测试。执行结果会返回给模型。所有测试在已有 benchmark 镜像的独立容器中运行，容器不连接网络。模型不能更改生产代码。Python 任务还记录部分条件和操作的运行事件。</p>')
    parts.append(f'<p>本轮请求模型 {escape(s["model"]["requested"])}。provider 实际返回 {escape(json.dumps(s["model"]["returned"], ensure_ascii=False))}。共调用 {s["model"]["external_calls"]} 次。provider 报告总用量为 {s["model"]["provider_reported_tokens"]:,} token。报告按实际返回标识记录模型，不推测 provider 的内部路由。</p>')
    parts.append('<h2>判定规则</h2><p>正确检测必须指出具体的条件组合。该组合必须揭示原补丁错误，并符合 gold 的正确语义。公开任务要求必须支持测试预期。仅缺少测试、代码存在差异或测试失败，都不够。</p>')
    parts.append('<p>正确补测还要求生成测试使用有效接口，实际构造所需组合，并检查能暴露错误的结果。测试导入失败、编译失败和执行超时不算成功。对依赖原补丁新增私有辅助代码的测试，按用户要求检查 gold 的静态语义，不强行执行 gold。</p>')
    parts.append('<p>gold、benchmark 失败测试和既有目标只用于离线评价。模型生成阶段未接收这些材料。对于已通过原补丁的有效测试，无需执行 gold 来证明它未揭示原补丁错误。对于失败测试，先检查失败位置，再比较 gold 语义；必要时执行相同测试。</p>')
    parts.append('<p>原测试已经检查了同一组合，但没有执行时，应记为选测问题。原断言与公开要求冲突时，应记为断言问题。这两类问题不计为新组合缺口。</p>')
    parts.append('<p>每个候选只评价最后保留的测试建议。模型后来撤回的建议不计最终成功。中间建议、运行失败和修改过程仍保留在记录中。Codex 逐项复核最终建议；本轮没有独立人类复核。</p>')
    parts.append('<h2>与固定参照目标的对照</h2><p>本轮开始前已有 23 个确认目标，分布在 18 个任务中。它们均要求原补丁失败、gold 语义通过。其余 12 个任务没有已确认的参照目标，但不能当作没有组合缺口的负例。因此本轮报告误报数量，不计算需要真实负例分母的误报率。</p>')
    parts.append(f'<p>方法命中固定目标 {len(ref["detected_targets"])} 项，正确补测 {len(ref["generated_targets"])} 项，漏掉 {ref["missed_target_count"]} 项。固定目标召回率为 {ref["target_recall"]:.1%}。新增确认目标共 {len(s["new_targets"])} 项；它们不改变本轮固定分母。</p>')
    parts.append('<p>本轮的成功来自 T08 新发现的组合错误。解析头部尚未遇到终止空行时，输入就出现关闭分界线。原补丁错误地接受该输入。gold 拒绝该输入。生成测试在原补丁上失败、gold 上通过。原验证分别检查正常头部、非法头部行和结束分界线，但没有检查这个跨阶段组合。</p>')
    parts.append('<p>T08 的新目标与原有两个目标不同。原目标分别检查缺少最后关闭分界线，以及带引号的边界值包含分号。因此，“正确检测 1 个任务”和“漏掉 23 个固定目标”可以同时成立。</p>')
    parts.append(table(['固定目标','组合','检测','正确补测'], [[t['id'],t['description'],'命中' if t['id'] in ref['detected_targets'] else '遗漏','是' if t['id'] in ref['generated_targets'] else '否'] for t in read(OLD / 'benchmark_reverse_v4/combined_targets.json')['targets']]))
    parts.append('<h2>逐任务结果</h2><p>“测试记录”包含原仓库测试和 trajectory 中恢复的历史版本。因此它不等于独立测试数量。“候选”表示程序关系假设，不表示已经检测到缺口。</p>')
    parts.append(table(['任务','测试记录','提取候选','送入模型','最终建议','检测正确','补测正确','误报建议','命中固定目标','新目标'], [[r['case']+' '+r['task'],r['extracted_tests'],r['extracted_candidates'],r['selected_candidates'],r['final_claims'],'是' if r['correct_detection'] else '否','是' if r['correct_generation'] else '否',r['false_positive_claims'],', '.join(r['detected_reference_targets']) or '无',', '.join(r['new_targets']) or '无'] for r in s['tasks']]))
    parts.append('<h2>每项最终建议的依据</h2>')
    labels = {'true_positive_reference':'正确：命中固定目标','true_positive_new_target':'正确：新增目标','false_positive_for_fault_revealing_gap':'误报：未揭示组合错误','unresolved':'证据不足'}
    ordinals = Counter()
    for r in s['reviews']:
        ordinals[r['case']] += 1
        label = r['case'] + ' 建议 ' + str(ordinals[r['case']])
        parts.append('<details><summary>'+escape(label+' · '+labels[r['classification']]+' · '+r['title'])+'</summary><p>'+escape(r['reason'])+'</p>')
        if r.get('original_validation'): parts.append('<p>'+escape(r['original_validation'])+'</p>')
        if r.get('reference_relation'): parts.append('<p>'+escape(r['reference_relation'])+'</p>')
        parts.append('<p>'+link(r['review']['path'],'复核记录')+'</p></details>')
    parts.append('<h2>运行结果与限制</h2>')
    run_labels = {'pass':'通过','fail':'至少一项测试失败','error':'导入、编译或测试收集错误','not_executed':'执行配置错误，未运行'}
    parts.append(table(['最终测试建议的原补丁运行结果','数量'],[[run_labels[k],v] for k,v in sorted(s['final_test_execution'].items())]))
    parts.append('<p>上述运行数量保留在线原始记录。T28 的两项建议因执行器没有识别工作区根目录的 Vitest 而未运行。离线核验补正了执行命令，未改测试代码；两项均通过。模型没有收到这次离线反馈。</p>')
    status_labels = {'generated_test_unverified':'保留了测试建议，等待语义复核','model_no_gap':'模型判断该候选没有缺口',
                     'unknown':'没有形成最终结论','model_selection_problem':'模型判断属于已有测试的选择问题','model_unknown':'模型明确表示无法判断'}
    parts.append(table(['模型处理结束时的状态','候选数量'],[[status_labels[k],v] for k,v in sorted(s['model']['final_candidate_statuses'].items())]))
    parts.append('<p>有效测试在原补丁上通过，不代表该任务没有其他错误。运行失败也不直接证明存在错误。上述四项效果指标使用语义复核结果，未把原始通过或失败数量当作正确性。</p>')
    parts.append('<h2>结果说明了什么</h2><p>当前方法仍主要寻找未检查的组合。多数输出可以增加覆盖，却不能区分当前错误实现与正确实现。若目标是帮助修复原补丁，候选优先级还需关注具体错误机制，以及测试能观察到的行为差异。</p>')
    parts.append(table(['任务','本轮生成测试的范围','固定目标需要的条件'], [
        ['T13','重复使用同一闭包，或分别复制各自闭包','两个不同闭包共享同一捕获变量，再一起复制'],
        ['T20','直接调用内部配置合并函数','先通过 CRD 配置校验，再进入运行时处理'],
        ['T24','显式传入 put 模式','省略模式参数，使用默认模式触发条件必填'],
        ['T28','恢复状态后直接读取查询结果','恢复错误状态后挂载观察者，触发后续刷新'],
    ]))
    parts.append('<p>这些例子表明，材料中出现相关函数或概念，并不保证测试保留了触发错误所需的对象关系、入口条件和操作顺序。后续改进应检查“是否构造了目标条件”，不能只检查“是否调用了目标函数”。本轮未做分阶段消融，不能把所有遗漏单独归因于程序分析或模型。</p>')
    parts.append(f'<p>交互预算还限制了反馈作用。{s["final_claim_count"]} 项最终建议中，{s["final_claims_at_last_round"]} 项在第 3 次调用才提交测试。此时模型预算已用完，无法读取这次执行结果后再修正测试。运行器提供了反馈接口，但本轮配置很少让最终测试获得一次反馈后的修正。</p>')
    parts.append(f'<p>本轮还记录了 {s["model"]["action_error_count"]} 次动作格式或引用错误，以及 2 次未完成的模型输出。Go 编译详情保存在原始日志中，但没有完整返回模型。部分 Vitest 反馈只返回前 30 条记录，可能让跳过的测试挤掉失败详情。这些执行与交互限制应先修正，再评价反馈机制的收益。</p>')
    parts.append('<h2>运行恢复与复现边界</h2><p>T01 首次提取因已解析函数引用缺少记录而中止。恢复程序从原始源码补回 45 条函数记录，并缓存相同的调用可达结果。T01 随后按原候选预算和模型预算运行。修复前没有模型调用。其他 29 个任务未使用这项提取修复。</p>')
    parts.append('<p>T19 在调用模型前遇到源码校验不一致。提取器校验的是换行标准化后的文本；运行器校验的是原始字节。恢复程序确认文本内容一致后继续运行。源码、模型输入和预算未改变。首次失败记录均保留。</p>')
    parts.append('<p>因此，本报告包含明确记录的运行恢复。它不是全部任务在完全相同实现上一次运行成功的结果。恢复没有使用 gold 或参照目标来选择候选。</p>')
    parts.append('<p>'+ ' · '.join(link(x['path'], '恢复记录 '+str(i+1)) for i,x in enumerate(s['operational_recoveries']))+'</p>')
    parts.append('<p>本轮没有修复原补丁，也没有重跑完整 benchmark。因此本轮未测量 resolution rate 的提升。错误检出测试只能提供修复线索。</p>')
    parts.append('<p>本轮使用固定候选预算和新的交互方式。原实验的调用预算不同。因此与旧结果的数量比较不构成受控消融实验。本轮评估的是当前配置的实际效果。</p>')
    parts.append('<p>旧方法在同一组 23 个固定目标中命中 1 项，即 T24-R1。本轮没有命中固定目标，只新增确认了 T08 的另一项错误。本轮结果尚未证明算法改进提高了错误检出能力。</p>')
    parts.append('<p>'+link(RUN/'protocol.json','冻结的实验设置')+' · '+link(RUN/'summary.json','完整统计')+' · '+link(OUT/'claims.json','最终建议与运行证据')+' · '+link(OLD/'benchmark_reverse_v4/combined_targets.json','固定参照目标')+'</p></html>')
    REPORT.write_text('\n'.join(parts))


if __name__ == '__main__':
    build()
