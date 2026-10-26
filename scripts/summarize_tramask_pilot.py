"""Build the TraMask pilot reading report from frozen reviews and executions.

No inference is made from shell return codes; scientific labels come from the
two independent original-context reviews and explicit downstream adjudications.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tramask_pilot.corpus import ROOT, RUN, read, receipt, write
from tramask_pilot.proposals import ARMS
from tramask_pilot.provider import BudgetLedger

OUT = RUN / "evaluation/pilot_v01"


def rel(path):
    return str(Path(path).relative_to(ROOT))


def build():
    cohorts = [read(RUN / name) for name in ("formal_failed_cohort.json", "formal_successful_cohort.json")]
    cases = [case for cohort in cohorts for case in cohort["cases"]]
    mapping = {x["case_id"]: x for x in read(RUN / "review_private_mapping.json")["packets"]}
    assert len(cases) == len({x["task"] for x in cases}) == len(mapping) == 40
    review_rows, marginal_a, marginal_b = [], Counter(), Counter()
    by_cohort = defaultdict(Counter)
    for case in cases:
        cid, pid = case["id"], mapping[case["id"]]["pair_id"]
        paths = [RUN / "blind_review" / ("reviewer_" + x) / (pid + ".json") for x in "ab"]
        a, b = map(read, paths)
        marginal_a[a["label"]] += 1
        marginal_b[b["label"]] += 1
        assert (a["label"], a["analyzable"], a["confirmed_mask"]) == (b["label"], b["analyzable"], b["confirmed_mask"]), "adjudication_required"
        by_cohort[case["cohort"]][a["label"]] += 1
        replay = Path(read(RUN / "runs" / cid / "active_replay.json")["directory"])
        fidelity = read(replay / "fidelity_check.json")
        review_rows.append({"case_id": cid, "trial": case["trial"], "task": case["task"],
                           "language": case["language"], "cohort": case["cohort"], "pair_id": pid,
                           "label": a["label"], "analyzable": a["analyzable"],
                           "confirmed_mask": a["confirmed_mask"],
                           "reviewer_a": receipt(paths[0]), "reviewer_b": receipt(paths[1]),
                           "packet_manifest": mapping[cid]["manifest"],
                           "fidelity_classification": fidelity["selected_output_fidelity"]["classification"],
                           "fidelity_review": receipt(replay / "fidelity_review.json"),
                           "reviewer_a_scope": a.get("scoped_pair"),
                           "reviewer_a_limitations": a.get("limitations", []),
                           "reviewer_b_limitations": b.get("limitations", [])})
    expected = sum(marginal_a[k] * marginal_b[k] for k in marginal_a) / 40**2
    agreement = sum(x["label"] == read(Path(x["reviewer_b"]["path"]))["label"] for x in review_rows) / 40
    original_review = {"status": "complete", "pairs": review_rows,
                       "label_counts": dict(marginal_a), "by_cohort": dict(by_cohort),
                       "agreement_fraction": agreement, "cohen_kappa": (agreement - expected) / (1 - expected),
                       "independence_scope": "Two fresh Codex threads manually read original public replay packets, blinded to repair results and each other's judgments. Same model family and shared evidence are not independent human validation.",
                       "disagreements": [], "adjudications": 0,
                       "frozen_before_post_experiment_review": [receipt(RUN / "blind_review/reviewer_a/freeze_receipts.json"), receipt(RUN / "blind_review/reviewer_b/freeze_receipt.json")]}
    write(OUT / "review.json", original_review)
    write(RUN / "cases.json", {"cases": cases, "unit": "One frozen trial/target-test pair per distinct task", "calibration_excluded": ["C01", "C02", "C03"]})

    arm_rows, group_rows, all_candidates = [], [], []
    for pilot, arms in ARMS.items():
        for arm in arms:
            groups, candidates, usages = [], [], []
            for cid in ("F023", "F034"):
                for repeat in (1, 2):
                    d = RUN / "runs" / cid / "downstream" / f"pilot{pilot}" / arm / f"repeat_{repeat:02d}"
                    recovery, manifest = read(d / "candidate_recovery.json"), read(d / "manifest.json")
                    rows = [read(p) for p in sorted(d.glob("candidate_*/evaluation.json"))]
                    assert len(rows) == 5 and manifest["external_model_calls"] == 1
                    for row in rows:
                        row = {**row, "case_id": cid, "pilot": pilot, "arm": arm, "repeat": repeat}
                        candidates.append(row)
                        all_candidates.append(row)
                    groups.append({"case_id": cid, "pilot": pilot, "arm": arm, "repeat": repeat,
                                   "raw_schema_valid": recovery["raw_schema_valid"],
                                   "executed_candidates": sum(bool(x.get("executed")) for x in rows),
                                   "first_unmasking_rank": next((x["rank"] for x in rows if x.get("validated_unmasking")), None),
                                   "first_general_augmentation_rank": next((x["rank"] for x in rows if x.get("augmented_assertion_discrimination")), None),
                                   "provider_tokens": manifest["usage"]["total_tokens"],
                                   "manifest": receipt(d / "manifest.json"),
                                   "candidate_recovery": receipt(d / "candidate_recovery.json")})
                    usages.append(manifest["usage"])
            arm_rows.append({"pilot": pilot, "arm": arm, "case_units": 2, "arm_repeat_units": 4,
                             "physical_calls": 4, "candidate_slots": 20,
                             "raw_schema_valid_responses": sum(g["raw_schema_valid"] for g in groups),
                             "executed_candidates": sum(bool(x.get("executed")) for x in candidates),
                             "subject_runs": sum(x.get("cost", {}).get("subject_runs", 0) for x in candidates),
                             "validated_unmasking_repeats": sum(g["first_unmasking_rank"] is not None for g in groups),
                             "general_augmentation_repeats": sum(g["first_general_augmentation_rank"] is not None for g in groups),
                             "general_augmentation_distinct_cases": len({g["case_id"] for g in groups if g["first_general_augmentation_rank"] is not None}),
                             "first_unmasking_ranks": [g["first_unmasking_rank"] for g in groups],
                             "recall_at_k": {str(k): sum(g["first_unmasking_rank"] is not None and g["first_unmasking_rank"] <= k for g in groups) / 4 for k in range(1, 6)},
                             "input_tokens": sum(x["prompt_tokens"] for x in usages),
                             "output_tokens": sum(x["completion_tokens"] for x in usages),
                             "total_tokens": sum(x["total_tokens"] for x in usages),
                             "slot_status_counts": dict(Counter(x["status"] for x in candidates))})
            group_rows.extend(groups)
    write(OUT / "downstream_groups.json", {"groups": group_rows, "arms": arm_rows})
    slots = Counter(x["status"] for x in all_candidates)
    setup_executed = [x for x in all_candidates if x.get("executed") and x["arm"] != "direct_augmentation"]
    operations = Counter(x["true_setup_operation_count"] for x in setup_executed)
    primary_setup = [x for x in setup_executed if x["pilot"] == 2 and x["arm"] == "trajectory" and x["repeat"] == 1]
    replication_setup = [x for x in setup_executed if x["pilot"] == 2 and x["arm"] == "trajectory" and x["repeat"] == 2]
    assert len(all_candidates) == 140
    assert not any(x.get("validated_unmasking") for x in all_candidates)
    post_paths = [RUN / "post_review" / f"reviewer_{who}_{cid}.json" for who in "ab" for cid in ("f023", "f034")]
    assert all(p.exists() for p in post_paths), "post_experiment_reviews_pending"
    acceptance = read(RUN / "post_review/root_acceptance.json")
    assert acceptance["all_material_issues_resolved"] is True
    assert {x["sha256"] for x in acceptance["review_receipts"]} == {receipt(p)["sha256"] for p in post_paths}
    replay_audit = read(OUT / "replay_audit.json")
    budget = BudgetLedger(RUN).snapshot()
    assert all(x["status"] == "settled" for x in budget["calls"].values())
    assert budget["committed_tokens"] <= 10_000_000
    providers = []
    for p in RUN.rglob("manifest.json"):
        m = read(p)
        if m.get("version") == "tramask-provider.v1":
            providers.append((p, m))
    assert len({m["budget_key"] for _, m in providers}) == len(budget["calls"])
    usage = Counter()
    phases = defaultdict(Counter)
    for p, m in providers:
        key = "preflight" if "preflight" in p.parts else "downstream" if "downstream" in p.parts else "target_hypothesis" if any(s.startswith("target_hypothesis") for s in p.parts) else "localization"
        phases[key]["calls"] += m["external_model_calls"]
        phases[key]["charged_tokens"] += m["budget"]["charged_tokens"]
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            usage[field] += m.get("usage", {}).get(field, 0)
    cost = {"provider_call_records": len(providers), "physical_provider_calls": sum(m["external_model_calls"] for _, m in providers),
            "global_cap": 10_000_000, "charged_input_output_tokens": budget["committed_tokens"],
            "provider_reported_usage": dict(usage), "phases": dict(phases),
            "requested_model": "deepseek-v4-flash", "response_model_aliases": sorted({m.get("response_model", "unknown") for _, m in providers}),
            "temperature": 0, "thinking": "disabled", "hidden_retries": False,
            "manual_codex_tokens": "Not measured by the DeepSeek provider ledger; excluded from this cap, not zero cost.",
            "downstream_physical_calls": 28, "downstream_candidate_PQ_pairs": sum(x.get("executed", False) for x in all_candidates),
            "downstream_instrumented_PQ_pairs": sum(x.get("executed", False) for x in all_candidates),
            "downstream_subject_runs": sum(x.get("cost", {}).get("subject_runs", 0) for x in all_candidates),
            "minimization_pairs": 0, "cost_per_validated_unmasking": None,
            "cost_per_validated_unmasking_reason": "No successful setup-unmasking witness; ratio undefined."}
    write(OUT / "cost.json", cost)
    limitations = [
        "40 distinct tasks are selected conditional on recoverable authored tests and manual replay qualification from this fixed corpus; 2/40 or 2/23 is not population prevalence across 211 failed trials or all coding agents.",
        "Only one bounded target/Q hypothesis per formal case was evaluated. Seventeen insufficient-evidence cases remain unknown, including absent/incompatible alternatives, missing target flip and failed instrumentation; they are not masking negatives.",
        "Replay qualification applies to selected command/test behavior. Whole-history byte identity is not claimed; recorded truncation, nondeterministic timing and manual mismatch resolutions remain visible. See replay_audit.json and each fidelity_review.json.",
        "Independent reviewers are two Codex threads with separate judgments and no repair leakage, not human experts or independent model families. Manual recovery/probe completion is part of this pilot, not end-to-end automation.",
        "F034 is a single-row mask. Other rows already detect Q before augmentation. The direct arm adds a discriminating row but neither unmasks the original row nor improves whole-command detection.",
        "F023's stale intermediate entry is subsequently filtered from public cache state. Observed internal masking may be benign redundancy; no missed delivered-P defect was established.",
        "F023 comparison aligns only each trace's explicit tmp_path binding; filenames, membership and original observation values remain intact. Added direct-test operands were not all instrumented: passing assertions mean no validated discrimination, not equality of all unrecorded state or the full cache JSON.",
        "Only 7/28 downstream responses satisfy the frozen strict schema. All raw failures are retained; mechanical envelope/escape recovery is reported as a separate secondary analysis, without semantic repair or new calls.",
        "History is a fixed 12-event chronological sample under 10 kB; local source is bounded to eight prefix/suffix file excerpts under 8 kB. No history advantage here does not establish that complete trajectory evidence is useless.",
        "The planned localization phase allocation was exceeded and disclosed in amendment004; the global 10-million input/output-token cap was obeyed. Protocol metadata timestamp and runtime/context corrections are retained in amendments001–007.",
        "F031 instrumentation failed and is retained as insufficient evidence. S030 probes add lint diagnostics, limiting its valid-discrimination conclusion to the runtime test layer; S007 qualifies runtime behavior, not compiler/formatter equivalence.",
        "Public issue contracts were sufficient for the new direct assertions; hidden verifiers/reference solutions were not supplied or used for generation. Zero new delivered-P defects are confirmed; no benchmark resolution-rate claim is made.",
        "Two physical calls per arm were made at temperature zero. Identical outputs can occur and are not independent task observations; task-level denominator remains two masks.",
    ]
    summary = {"status": "complete", "created_at": datetime.now(timezone.utc).isoformat(),
               "paper": receipt(ROOT / "TraMask_Behavioral_Masking.pdf"),
               "corpus": {k: read(RUN / "corpus_audit.json")[k] for k in ("trials", "tasks", "models", "missing_files")},
               "formal_trials": 40, "failed_trials": 30, "successful_trials": 10, "distinct_tasks": 40,
               "calibration_cases_excluded": 3,
               "pilot1": {"target_test_pairs": 40, "analyzable_pairs": sum(x["analyzable"] for x in review_rows),
                          "fixed_Q_pairs_executed": 25, "no_admissible_Q_pairs": 15,
                          "labels": dict(marginal_a), "by_cohort": dict(by_cohort), "confirmed_mask_pairs": 2,
                          "confirmed_mask_tasks": 2, "confirmed_mask_cases": ["F023", "F034"],
                          "review_agreement": agreement, "cohen_kappa": original_review["cohen_kappa"],
                          "count_ratio_all_pairs": "2/40 (5.0%)", "count_ratio_analyzable": "2/23 (8.7%)", "prevalence_claim": False},
               "pilot2": {"mask_pairs": 2, "arms": [x for x in arm_rows if x["pilot"] == 2],
                          "validated_context_factors": 0, "best_ranks": None,
                          "useful_history_evidence_categories": [], "trajectory_advantage_established": False,
                          "rank_and_runs_to_success": "No successful context factor; censored within the fixed budget, not zero runs to success."},
               "pilot3": {"mask_pairs": 2, "primary_stream": "Pilot2 trajectory repeat_01, frozen in calibration_protocol.json",
                          "legal_setup_candidates_executed": len(primary_setup),
                          "setup_operation_distribution": dict(Counter(x["true_setup_operation_count"] for x in primary_setup)),
                          "resolved_by_one_edit_cases": 0, "resolved_by_two_edits_cases": 0,
                          "unresolved_within_budget_cases": 2, "validated_unmasking_rate": 0,
                          "repeat_02_reproducibility": {"legal_setup_candidates_executed": len(replication_setup), "resolved_cases": 0, "unresolved_cases": 2},
                          "supplemental_all_setup_arms": {"legal_candidates_executed": len(setup_executed), "setup_operation_distribution": dict(operations), "resolved_cases": 0, "not_primary_pilot3": True},
                          "minimization": "Not applicable: no successful setup edit", "new_delivered_patch_defects": 0},
               "pilot4": {"arms": [x for x in arm_rows if x["pilot"] == 4],
                          "direct_general_augmentation_successful_repeats": 2,
                          "direct_general_augmentation_distinct_cases": 1,
                          "direct_new_whole_command_detection_cases": 0,
                          "all_setup_methods_unmasking_cases": 0},
               "downstream": {"physical_calls": 28, "slots": 140, "raw_schema_valid_responses": 7,
                              "slot_status_counts": dict(slots), "executed_candidates": cost["downstream_candidate_PQ_pairs"],
                              "subject_runs": cost["downstream_subject_runs"], "raw_and_recovered_tracks_separate": True,
                              "arm_execution_tables_track": "Mechanically recovered secondary candidate analysis; raw strict validity is reported separately per group.",
                              "raw_strict_operational_result": {"valid_responses": 7, "invalid_responses": 21, "validated_unmasking_repeats": 0, "general_augmentation_successful_repeats": 2}},
               "cost": cost, "limitations": limitations,
               "decision": "Scoped masking is reproducible in two tasks, but the fixed pilot provides no validated minimal-context unmasking or trajectory-ranking gain. Do not proceed to claim the full TraMask system's central effectiveness assumptions as established.",
               "post_experiment_independent_reviews": [receipt(p) for p in post_paths],
               "post_review_resolution": receipt(RUN / "post_review/root_acceptance.json"),
               "replay_audit": receipt(OUT / "replay_audit.json"),
               "protocol_amendments": [receipt(p) for p in sorted((RUN / "amendments").glob("*.json"))]}
    write(OUT / "summary.json", summary)
    write(RUN / "protocol.json", {"role": "Post-run navigation to the immutable staged protocols; not a retrospective preregistration",
          "original_protocols": [receipt(RUN / p) for p in ("calibration_protocol.json", "formal_localization_protocol.json", "formal_hypothesis_protocol.json", "downstream_protocol.json", "downstream_scoped_endpoint.json")],
          "amendments": summary["protocol_amendments"], "independent_repeats_per_downstream_arm": 2,
          "model": "deepseek-v4-flash", "provider_token_cap": 10_000_000})
    write(RUN / "active_evaluation.json", {"summary": receipt(OUT / "summary.json"), "review": receipt(OUT / "review.json"),
          "report": receipt(OUT / "report.html") if (OUT / "report.html").exists() else None})
    render(summary, review_rows, arm_rows)
    write(RUN / "active_evaluation.json", {"summary": receipt(OUT / "summary.json"), "review": receipt(OUT / "review.json"), "report": receipt(OUT / "report.html")})
    print(json.dumps({"status": "complete", "pairs": 40, "labels": dict(marginal_a), "tokens": cost["charged_input_output_tokens"], "report": str(OUT / "report.html")}, ensure_ascii=False))


def render(s, rows, arms):
    def table(headers, values):
        return '<table><thead><tr>' + ''.join('<th>' + escape(str(x)) + '</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + str(x) + '</td>' for x in row) + '</tr>' for row in values) + '</tbody></table>'
    def link(label, target):
        import os
        return '<a href="' + escape(os.path.relpath(target, OUT), quote=True) + '">' + escape(str(label)) + '</a>'
    labels = {'masking': '局部 masking', 'weak_oracle': '弱 oracle', 'valid_discrimination': '有效区分', 'insufficient_evidence': '证据不足', 'target_bypass': '目标未执行'}
    label_table = table(['分类', 'Failed（30）', 'Successful（10）', '合计'], [[labels[k], s['pilot1']['by_cohort']['failed'].get(k, 0), s['pilot1']['by_cohort']['successful'].get(k, 0), s['pilot1']['labels'].get(k, 0)] for k in labels])
    arm_table = table(['Pilot', '条件', '独立调用', '原始 schema 合格', '执行候选', '严格解除 masking', '新增行区分 / 调用', 'Tokens'], [[a['pilot'], escape(a['arm']), 4, str(a['raw_schema_valid_responses']) + '/4', a['executed_candidates'], str(a['validated_unmasking_repeats']) + '/4', str(a['general_augmentation_repeats']) + '/4', f"{a['total_tokens']:,}"] for a in arms])
    case_table = table(['案例', 'Task', '来源', '判断', '机械重放比较', '独立审阅'], [[link(x['case_id'], RUN / 'runs' / x['case_id']), escape(x['task']), escape(x['cohort']), labels[x['label']], link(x['fidelity_classification'], x['fidelity_review']['path']), link('A', x['reviewer_a']['path']) + ' / ' + link('B', x['reviewer_b']['path'])] for x in rows])
    post = ' · '.join(link(Path(x['path']).stem, x['path']) for x in s['post_experiment_independent_reviews'])
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TraMask 四项 Pilot 实验</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;max-width:1180px;margin:32px auto;padding:0 22px;color:#202832;background:#fafafa}}h1,h2{{line-height:1.3}}table{{border-collapse:collapse;width:100%;font-size:14px;margin:20px 0}}th,td{{border:1px solid #d5dce3;text-align:left;padding:8px;vertical-align:top;overflow-wrap:anywhere}}th{{background:#edf2f6}}a{{color:#0759a8}}.lead{{background:#e8f0f5;padding:20px;border-left:5px solid #345f7b}}code{{font-size:14px}}li{{margin:8px 0}}details{{margin:20px 0}}.scroll{{overflow:auto}}</style>
<h1>TraMask：四项 Pilot 实验结果</h1><p>2026-10-23 · {RUN.name} · 已完成 · DeepSeek-v4-flash · 每个条件两次独立调用</p>
<p class="lead">40 个不同任务中，两个独立 Codex 线程一致确认 2 个局部 masking。固定预算内，合法的一至两步 setup 修改解除 masking 为 <strong>0/2</strong>；没有建立 trajectory 条件的排序优势。直接测试增强在 1 个任务的两次重复中新增了区分性测试行，但该任务原有其他行已能检测 Q。结果支持继续研究 masking 的边界，尚不足以支持论文提出的完整系统效果假设。</p>
<p>{link('机器可读汇总', OUT/'summary.json')} · {link('全部逐案审阅', OUT/'review.json')} · {link('重放与排除审计', OUT/'replay_audit.json')} · {link('成本', OUT/'cost.json')} · {link('协议入口', RUN/'protocol.json')}</p>
<h2>Pilot 1：真实重放与分类</h2>
<p>211 条失败 trial 的必需材料齐全，涉及 90 个任务，记录模型均为 DeepSeek-v4-flash。先进行 3 个校准案例，再按固定种子和任务去重顺序，取得 30 条可重放失败 trial 与 10 条成功对照。40 个正式案例来自 40 个不同任务；校准、备用案例及环境排除不混入分母。逐案保存历史源码/测试、交付补丁 P、固定目标局部替代 Q、原始命令、观测和重放资格记录。</p>
<p>历史输出的机械比较为 5 个完全一致、23 个归一化一致、12 个不一致。40 个均有另外的人工语义资格审阅；12 个机械不一致没有被改写成完全匹配。资格只涵盖选定命令的测试行为，相关截断、时间/路径变化、恢复过程差异和逐案限制均保留。S007 仅支持 runtime 测试重放，S019 的历史复合命令返回 99，也不等于测试通过。</p>
<p>两位 reviewer 为新建 Codex 线程，分别手动阅读匿名原始证据包；在 40 份原判断全部冻结前不接触后续修复结果，也不读取对方判断。40/40 分类一致，Cohen κ=1.00；这不是人类专家一致性。40 个候选目标–测试对中，25 个构建并执行了固定 P/Q，15 个没有合格 Q；其中还各有 1 个缺少目标效应翻转、1 个插桩失败。最终可分析对共 23 个，另 17 个保留为证据不足，不当作负例。2/40（5.0%）和 2/23（8.7%）仅是本次条件样本内的计数比，不能外推为 211 条 trial 的 masking 流行率。</p>{label_table}
<h2>两个确认案例的边界</h2>
<p><strong>F023 · 缓存清理。</strong>第二次扫描后，P 清除已删除的 b.py 中间缓存项，Q 仍保留该项；后续持久化过滤使原测试读取到的 cache.json 模块集合在两者中均为 {{a.py}}。整个原始命令均通过。13 个合法后续候选（其中 7 个 setup、6 个直接增强）及其测量版本均执行；目标效应仍不同，原观察仍相同，新增断言也没有检测差异。该现象可能是后续过滤形成的冗余保护，不能据此声称交付补丁有漏检缺陷。{link('原始与候选证据', RUN/'runs/F023/downstream/evaluation.json')}</p>
<p><strong>F034 · 默认参数与 variadic。</strong>原表格最后一行 <code>func f(a = 1, b = 2, c...) {{ return c }}; f()</code> 中，省略参数的内部 payload 在 P/Q 间不同，但原返回值均为非 nil 的空数组。其他原有表格行已经使 Q 失败，故 mask 只在该行成立。直接增强两次都在第 1 名新增 <code>f(9)</code> 并观察 <code>[a,b,rest]</code>：P 返回 [9,2,[]]，Q 返回 [9,nil,[]]，公开需求独立支持前者。原 masked 行仍相同，整条命令的检测能力没有新增。{link('原始与候选证据', RUN/'runs/F034/downstream/evaluation.json')}</p>
<h2>Pilot 2–4：相同 Q、相同预算的对照</h2>
<p>两个 mask × 七个条件 × 两次物理调用，共 28 次请求、140 个固定排名槽位。每次最多 5 个候选；setup 条件要求最多两项语义操作，并原样保留目标调用、原公共观察和每条原断言。直接增强允许新增测试体/断言，单独统计。候选逐名审核和执行，遇到该方法的合法成功才停止，未执行的剩余槽位照常保留。</p>
<p>下表的候选执行、recall 与成功结果属于<strong>机械恢复后的补充分析</strong>；原始严格 schema 合格率单列。严格原始运营记录为 7 个合格响应、21 个不合格响应、0 个解除 masking 成功；两次直接增强成功均来自原始 schema 合格响应。不能把补充分析写成严格格式下的自动化成功率。</p>
<div class="scroll">{arm_table}</div>
<p><strong>Pilot 2：</strong>三个信息条件均没有找到可验证的解除 masking 因子，recall@1–5 均为 0；成功排名与到成功所需运行数在预算内未观测到，不能填成“0 次”。没有足够证据把 trajectory 引导的 masker 发现作为已验证贡献。这里的 history 是预算内的事件采样，结论不等同于完整轨迹无用。</p>
<p><strong>Pilot 3：</strong>按冻结协议，主干预流只采用 Pilot 2 trajectory 的 repeat_01：F023 执行 1 个合法的一项操作候选，F034 没有合格候选，解除率 0/2；一步 0/2、两步 0/2、预算内未解决 2/2。repeat_02 是单列的重复性检查，两个案例均没有合格可执行候选，也没有成功。其他条件合计的 8 个合法 setup 执行（4 个一项、4 个两项操作）仅作为补充暴露量，不能混作主 Pilot 3。没有成功 setup 编辑，故成功后最小化不适用。新确认交付补丁缺陷为 0。</p>
<p><strong>Pilot 4：</strong>直接增强有 2/4 个调用获得新增测试行的有效区分，均来自 F034，独立任务数为 1/2；普通变化、无历史 two-flip 和有历史 two-flip 均未解除原 mask。不能把直接增强这一结果写成原 mask 被解除或整套测试新检测到缺陷。</p>
<h2>原始失败、恢复分析与成本</h2>
<p>28 个响应中仅 7 个满足冻结的严格 schema。原始运营结果与机械恢复分析分开保留：缺失的外层 command/policy 只绑定到原请求，额外转义仅在能唯一恢复原 anchor 时处理；不补造语义字段、不改候选、不追加调用。全部 140 槽中，79 个 no_proposal、18 个结构无效、20 个语义/契约不合格、16 个已执行、7 个因同组第 1 名直接增强成功而未执行。16 个候选对应 16 个原始 P/Q 对加 16 个插桩 P/Q 对，共 64 次运行。</p>
<p>所有阶段共记账 <strong>{s['cost']['charged_input_output_tokens']:,} / 10,000,000 tokens</strong>，包含校准、目标定位、Q 提议及后续生成；共 {s['cost']['physical_provider_calls']} 次外部模型请求。请求模型为 deepseek-v4-flash，响应服务别名为 deepseek-flash。Codex 手动分析/review 的 tokens 不在 DeepSeek 账本内。早期阶段配额偏离、技术恢复及协议时间戳问题均以 amendment 保存；总上限未突破。</p>
<h2>独立后验复核</h2><p>原判断冻结后，两位 reviewer 再分别检查候选、公开契约和原始执行；后验文件与原始盲审文件分离：{post}。</p>
<h2>限制与论文决策</h2><ul>{''.join('<li>'+escape(x)+'</li>' for x in s['limitations'])}</ul>
<p>本次观察满足“多个任务中存在可重放的局部 masking”，但未满足“少量 setup 修改能在相当比例案例中恢复敏感性”和“轨迹信息在匹配预算下改善定位”。在新的证据出现前，应收窄可编辑上下文的目标类别，并把 trajectory 的帮助保留为待检验假设；不宜据本次结果宣称完整 two-flip 方法有效。</p>
<h2>40 个正式案例与证据入口</h2><div class="scroll">{case_table}</div>
<p>报告由 {link('summarize_tramask_pilot.py', ROOT/'scripts/summarize_tramask_pilot.py')} 从冻结记录生成。运行方法和读取顺序见 {link('运行 README', RUN/'README.md')}。原 PDF 保持不变。</p></html>'''
    (OUT / "report.html").write_text(body)


if __name__ == "__main__":
    build()
