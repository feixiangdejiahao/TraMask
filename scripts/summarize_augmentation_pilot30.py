"""Summarize the frozen pilot and its evaluation-only source reviews.

This script makes no model calls and does not execute or repair generated tests.
The evidence review is an input, not a label inferred from test pass/fail.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from scripts.run_augmentation_pilot30 import RUN, read, write

CONFIRMED = {"known_gap", "additional_gap"}
CORRECT_TEST = {"valid", "valid_failure", "partial_valid"}
LANGUAGES = {"python": "Python", "go": "Go", "typescript": "TypeScript"}
CLASS_NAMES = {"known_gap": "命中历史缺口", "additional_gap": "其他有效目标",
               "false_positive": "误报", "unresolved": "待定"}


def receipt(path):
    return {"path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def native_result(directory):
    for phase in ("native_environment_final", "native_environment", "native"):
        path = directory / phase / "summary.json"
        if path.exists():
            return read(path), path
    return None, None


def summarize():
    cases = read(RUN / "cases.json")
    truth = {r["id"]: r for r in read(RUN / "evaluation_truth.json")}
    result_status, decisions, provider_status, finish_reason = (Counter() for _ in range(4))
    response_models, request_configs, family, scope = (Counter() for _ in range(4))
    native_counts, raw_classes, accepted_classes, usage = (Counter() for _ in range(4))
    valid_native_counts, invalid_errors = Counter(), Counter()
    gaps_by_class, hits_by_class = Counter(), Counter()
    rows, review_receipts, collisions, provider_failures = [], [], [], []
    request_count = 0
    for case in cases:
        cid = case["id"]
        directory = RUN / "cases" / cid
        review_path = RUN / "evaluation/reviews" / (cid + ".json")
        review = read(review_path)
        assert review["status"] == "complete"
        review_receipts.append(receipt(review_path))
        annotated = {c["candidate"]: c for c in review["claims"]}
        assert len(annotated) == len(review["claims"])
        known = {g["source_gap_index_1based"]: g for g in truth[cid]["gaps"] if g["class"] in {"S", "M"}}
        gaps_by_class.update(g["class"] for g in known.values())
        prepared_path = directory / "prepared.json"
        prepared = read(prepared_path) if prepared_path.exists() else None
        candidates = {}
        if prepared:
            grouped = defaultdict(list)
            for c in prepared["candidates"]:
                grouped[c["id"]].append(c)
                # build_request uses the first candidate with this ID.
                candidates.setdefault(c["id"], c)
            for ident, variants in grouped.items():
                if len(variants) > 1:
                    collisions.append({"case": cid, "candidate": ident, "rows": len(variants),
                                       "identical": all(c == variants[0] for c in variants),
                                       "relations": [c["relations"] for c in variants],
                                       "transmitted_variant": 0,
                                       "effect": "Second row was not separately dispatched; original records retained."})
            family.update(c["family"] for c in candidates.values())
            scope.update(c["scope"] for c in candidates.values())
        paths = sorted((directory / "generation").glob("*/result.json"))
        assert {p.parent.name for p in paths} == set(candidates), cid
        local_classes, local_raw, local_native = Counter(), Counter(), Counter()
        correct, confirmed, failed_correct = [], [], []
        seen_claims, local_results = set(), Counter()
        known_detected, known_generated = set(), set()
        evidence = []
        for path in paths:
            ident = path.parent.name
            result, manifest = read(path), read(path.parent / "manifest.json")
            request = read(path.parent / "request.json")
            request_count += 1
            request_configs[(request.get("model"), request.get("max_tokens"),
                             request.get("reasoning_effort"), request.get("temperature"))] += 1
            assert manifest["external_model_calls"] == 1
            result_status[result["status"]] += 1
            local_results[result["status"]] += 1
            decisions[str(result.get("raw_decision"))] += 1
            provider_status[manifest["status"]] += 1
            finish_reason[str(manifest.get("finish_reason"))] += 1
            response_models[str(manifest.get("response_model"))] += 1
            if result["status"] == "invalid_response":
                invalid_errors[result["error"]] += 1
            if manifest["status"] != "complete":
                provider_failures.append({"case": cid, "candidate": ident,
                                          "status": manifest["status"],
                                          "finish_reason": manifest.get("finish_reason"),
                                          "http_status": manifest.get("http_status")})
            usage.update({k: v for k, v in (manifest.get("usage") or {}).items()
                          if isinstance(v, (int, float))})
            if result.get("raw_decision") not in {"gap", "selection_problem"}:
                continue
            seen_claims.add(ident)
            assessment = annotated[ident]
            label = assessment["classification"]
            raw_classes[label] += 1
            local_raw[label] += 1
            if result["status"] != "decoded":
                assert assessment["test_validity"] == "rejected_response", (cid, ident)
                continue
            accepted_classes[label] += 1
            local_classes[label] += 1
            native, native_path = native_result(path.parent)
            if result["raw_decision"] == "gap":
                assert native is not None, (cid, ident)
                state = native.get("run_status", "setup_error")
                native_counts[state] += 1
                local_native[state] += 1
            if label in CONFIRMED:
                confirmed.append(ident)
            known_detected.update(assessment["known_gap_indices"])
            success = label in CONFIRMED and assessment["test_validity"] in CORRECT_TEST
            if success:
                assert native and native["run_status"] in {"pass", "fail"}, (cid, ident)
                assert any(t["status"] in {"pass", "fail"} for t in native["tests"])
                correct.append(ident)
                valid_native_counts[native["run_status"]] += 1
                known_generated.update(assessment["generated_known_gap_indices"])
                if assessment["test_validity"] == "valid_failure":
                    assert native["run_status"] == "fail"
                    failed_correct.append(ident)
            evidence.append({"candidate": ident, "classification": label,
                             "test_validity": assessment["test_validity"],
                             "correct_test_packet": success,
                             "native": str(native_path.relative_to(ROOT)) if native_path else None,
                             "reason": assessment["reason"], "test_reason": assessment["test_reason"]})
        assert seen_claims == set(annotated), cid
        assert known_generated <= known_detected <= set(known)
        assert known_detected == set(review["detected_known_gap_indices"]), cid
        assert known_generated == set(review["generated_known_gap_indices"]), cid
        hits_by_class.update(known[i]["class"] for i in known_detected)
        rows.append({"id": cid, "trial": case["trial"], "task": case["task"], "language": case["language"],
                     "known_gap_count": len(known), "known_gap_classes": dict(Counter(g["class"] for g in known.values())),
                     "known_gap_targets": [{"index": i, "class": g["class"], "description": g["relation_shape"]} for i, g in known.items()],
                     "detected_known_gap_indices": sorted(known_detected),
                     "generated_known_gap_indices": sorted(known_generated),
                     "known_gap_misses": sorted(set(known) - known_detected),
                     "any_confirmed_gap": bool(confirmed), "any_correct_test": bool(correct),
                     "correct_test_packets": len(correct), "valid_assertion_failure_packets": len(failed_correct),
                     "raw_candidate_rows": len(prepared["candidates"]) if prepared else 0,
                     "unique_candidate_ids": len(candidates), "model_calls": len(paths),
                     "execution_review_candidates": sum(c.get("review_focus") == "existing_test_execution" for c in candidates.values()),
                     "result_status": dict(local_results), "raw_gap_claim_classes": dict(local_raw),
                     "accepted_gap_claim_classes": dict(local_classes), "native_status": dict(local_native),
                     "analysis_status": "complete" if prepared else read(directory / "extraction.json")["status"],
                     "miss_reason": review["miss_reason"], "accepted_claims": evidence,
                     "review": str(review_path.relative_to(ROOT))})
    any_detection = sum(r["any_confirmed_gap"] for r in rows)
    known_trials = sum(bool(r["detected_known_gap_indices"]) for r in rows)
    summary = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "run": str(RUN.relative_to(ROOT)), "evaluation_only": True,
        "reviewer": "Codex source/trajectory/contract review; no independent human adjudication",
        "sample": {"trials": len(rows), "distinct_tasks": len({r["task"] for r in rows}),
                   "languages": dict(Counter(r["language"] for r in rows)),
                   "positive_only": True, "single_only_trials": sum(not r["known_gap_classes"].get("M") for r in rows),
                   "with_multi_trials": sum(bool(r["known_gap_classes"].get("M")) for r in rows),
                   "known_gap_entries": sum(gaps_by_class.values()), "known_gap_classes": dict(gaps_by_class)},
        "primary_trial_metrics": {"at_least_one_confirmed_gap": any_detection,
                                  "at_least_one_correct_executed_combination_test": sum(r["any_correct_test"] for r in rows),
                                  "positive_trials_without_confirmed_detection": len(rows) - any_detection,
                                  "trials_with_accepted_false_positive_claim": sum(bool(r["accepted_gap_claim_classes"].get("false_positive")) for r in rows),
                                  "task_level_false_positive_rate": None,
                                  "false_positive_rate_reason": "No negative trials; proposal-level errors can coexist with valid detections."},
        "known_target_metrics": {"detected_trials": known_trials,
                                 "trials_without_any_known_target_hit": len(rows) - known_trials,
                                 "correct_test_trials": sum(bool(r["generated_known_gap_indices"]) for r in rows),
                                 "detected_entries": sum(hits_by_class.values()),
                                 "missed_entries": sum(gaps_by_class.values()) - sum(hits_by_class.values()),
                                 "correct_test_entries": sum(len(r["generated_known_gap_indices"]) for r in rows),
                                 "trials_with_any_known_entry_still_missed": sum(bool(r["known_gap_misses"]) for r in rows),
                                 "detected_classes": dict(hits_by_class)},
        "candidate_metrics": {"raw_rows": sum(r["raw_candidate_rows"] for r in rows),
                              "unique_ids": sum(r["unique_candidate_ids"] for r in rows),
                              "single_or_multi_scope": dict(scope), "families": dict(family),
                              "existing_execution_review_candidates": sum(r["execution_review_candidates"] for r in rows),
                              "id_collisions": collisions},
        "model": {"requested": "deepseek-v4-flash", "returned_models": dict(response_models),
                  "provider_advertised_name": "DeepSeek-V4.1-Flash", "calls": request_count,
                  "request_configs": [{"model": k[0], "max_tokens": k[1], "reasoning_effort": k[2],
                                       "temperature": k[3], "calls": v} for k, v in request_configs.items()],
                  "result_status": dict(result_status), "raw_decisions": dict(decisions),
                  "provider_status": dict(provider_status), "finish_reason": dict(finish_reason),
                  "invalid_response_reasons": dict(invalid_errors), "usage_reported_by_provider": dict(usage),
                  "failed_calls": provider_failures, "automatic_retries": 0},
        "claim_metrics": {"raw_gap_proposals": sum(raw_classes.values()), "raw_classes": dict(raw_classes),
                          "accepted_gap_proposals": sum(accepted_classes.values()), "accepted_classes": dict(accepted_classes),
                          "correct_test_packets": sum(r["correct_test_packets"] for r in rows),
                          "correct_test_native_status": dict(valid_native_counts),
                          "valid_assertion_failure_packets": sum(r["valid_assertion_failure_packets"] for r in rows),
                          "trials_with_valid_assertion_failure": sum(bool(r["valid_assertion_failure_packets"]) for r in rows),
                          "unit": "One candidate response, potentially multiple generated tests; semantic duplicates are not deduplicated."},
        "native_execution": {"frozen_packets_attempted": sum(native_counts.values()), "status": dict(native_counts),
                             "network": "disabled during subject test execution",
                             "test_code_or_expected_value_repairs": 0},
        "review_receipts": review_receipts, "cases": rows,
        "limits": ["All trials are positive; no task-level specificity or false-positive rate.",
                   "Additional accepted targets overlap and are not a census of unique gaps.",
                   "Passing alone does not establish a correct combination test.",
                   "Source review is by Codex, not independent human reviewers.",
                   "Historical labels and model inputs are separated; historical labels are not exhaustive.",
                   "No reference implementation, hidden verifier, patch repair or resolution-rate evaluation.",
                   "TypeScript runtime execution does not establish type-level correctness.",
                   "One analysis timeout and one candidate ID collision remain included in the pilot."]}
    assert sum(result_status.values()) == summary["candidate_metrics"]["unique_ids"] == request_count
    assert sum(native_counts.values()) == sum(accepted_classes.values())
    assert len(rows) == 30 and summary["sample"]["distinct_tasks"] == 30
    write(RUN / "summary.json", summary)
    return summary


def link(path, label, destination):
    relative = os.path.relpath(path, destination.parent)
    return f'<a href="{escape(relative, quote=True)}">{escape(str(label))}</a>'


def render(summary, destination):
    s = summary
    p, k, c = s["primary_trial_metrics"], s["known_target_metrics"], s["claim_metrics"]
    accepted = c["accepted_classes"]
    false_positives = accepted["false_positive"]
    unknown = accepted["unresolved"]
    known_total = s["sample"]["known_gap_entries"]
    yes = lambda value: "是" if value else "否"
    metric_rows = [
        ("检出至少一项经审阅确认的组合缺口", f'{p["at_least_one_confirmed_gap"]} / 30 个 trial'),
        ("生成至少一个正确且已执行的组合测试", f'{p["at_least_one_correct_executed_combination_test"]} / 30 个 trial'),
        ("没有检出任何经确认缺口", f'{p["positive_trials_without_confirmed_detection"]} / 30 个 trial'),
        ("至少命中一项历史预标注缺口", f'{k["detected_trials"]} / 30 个 trial'),
        ("为历史预标注缺口生成正确测试", f'{k["correct_test_trials"]} / 30 个 trial'),
        ("没有命中任何历史预标注缺口", f'{k["trials_without_any_known_target_hit"]} / 30 个 trial'),
        ("按历史缺口条目计：检出 / 漏检", f'{k["detected_entries"]} / {k["missed_entries"]} 项，共 {known_total} 项'),
        ("算法接受的建议中，已确认的误报", f'{false_positives} 份，涉及 {p["trials_with_accepted_false_positive_claim"]} 个 trial'),
        ("算法接受的建议中，尚不能定性的建议", f'{unknown} 份'),
    ]
    metrics = "".join(f"<tr><th>{escape(a)}</th><td>{escape(b)}</td></tr>" for a, b in metric_rows)
    rows, details = [], []
    truth = {t["id"]: t for t in read(RUN / "evaluation_truth.json")}
    for case in s["cases"]:
        cid = case["id"]
        row_class = "hit" if case["detected_known_gap_indices"] else ""
        rows.append(f'<tr class="{row_class}"><td><a href="#{cid}">{cid}</a></td>'
                    f'<td>{escape(case["task"])}</td><td>{LANGUAGES[case["language"]]}</td>'
                    f'<td>{case["model_calls"]}</td><td>{yes(case["any_confirmed_gap"])}</td>'
                    f'<td>{yes(case["any_correct_test"])}</td>'
                    f'<td>{len(case["detected_known_gap_indices"])} / {case["known_gap_count"]}</td>'
                    f'<td>{case["accepted_gap_claim_classes"].get("false_positive", 0)}</td>'
                    f'<td>{case["accepted_gap_claim_classes"].get("unresolved", 0)}</td></tr>')
        targets = "；".join(f'{g["index"]}. {g["description"]}（{"单关系" if g["class"] == "S" else "多关系"}）'
                            for g in case["known_gap_targets"])
        accepted_claims = case["accepted_claims"]
        valid = [x for x in accepted_claims if x["correct_test_packet"]]
        valid.sort(key=lambda x: (x["classification"] != "known_gap", x["test_validity"] != "valid_failure", x["candidate"]))
        witness = ""
        if valid:
            example = valid[0]
            generation = RUN / "cases" / cid / "generation" / example["candidate"]
            witness = (f'<p>一项有效补测：{escape(example["reason"])} '
                       f'{link(generation / "assessment.json", "原始测试代码", destination)} · '
                       f'{link(ROOT / example["native"], "执行结果", destination)}。</p>')
        fp_examples = [x for x in accepted_claims if x["classification"] == "false_positive"]
        fp = f'<p>一项误报的依据：{escape(fp_examples[0]["reason"])}</p>' if fp_examples else ""
        classes = case["accepted_gap_claim_classes"]
        overview = "，".join(f'{CLASS_NAMES[name]} {classes.get(name, 0)} 份' for name in CLASS_NAMES)
        details.append(f'<details id="{cid}"><summary>{cid} · {escape(case["trial"])}</summary>'
                       f'<p>历史目标：{escape(targets)}。</p>'
                       f'<p>{escape(case["miss_reason"])}</p><p>已接受的建议：{overview}。'
                       f'含正确补测的建议：{case["correct_test_packets"]} 份。计数没有合并重复语义。</p>'
                       f'{witness}{fp}<p>{link(ROOT / case["review"], "逐项审阅记录", destination)} · '
                       f'{link(RUN / "cases" / cid / "prepared.json", "自动提取材料", destination) if case["analysis_status"] == "complete" else link(RUN / "cases" / cid / "extraction.json", "分析超时记录", destination)}</p></details>')
    by_language = []
    for language in LANGUAGES:
        group = [r for r in s["cases"] if r["language"] == language]
        by_language.append(f'<tr><th>{LANGUAGES[language]}</th><td>{sum(r["any_confirmed_gap"] for r in group)} / 10</td>'
                           f'<td>{sum(r["any_correct_test"] for r in group)} / 10</td>'
                           f'<td>{sum(bool(r["detected_known_gap_indices"]) for r in group)} / 10</td>'
                           f'<td>{sum(r["accepted_gap_claim_classes"].get("false_positive", 0) for r in group)}</td></tr>')
    stages = [
        ("原计划 trial", "30", "每个 trial 对应不同任务。保留分析失败项。"),
        ("完成程序分析", "29", "T01 在 1800 秒后超时。"),
        ("程序产生的候选记录", str(s["candidate_metrics"]["raw_rows"]), "T11 两条记录使用同一 ID。它们对应不同调用位置。"),
        ("实际模型请求", str(s["model"]["calls"]), "每个候选 ID 只发出一次请求。发生 ID 碰撞的第二条记录未单独发出。"),
        ("模型返回完整回答", "983", "另有 18 次输出达到长度限制，4 次请求超出上下文长度。"),
        ("通过输出结构检查", "907", "337 份报告缺口，570 份报告无缺口。没有返回选测问题。"),
        ("原始回答报告缺口", str(c["raw_gap_proposals"]), "其中 8 份没有通过结构检查，未执行。"),
        ("已接受并尝试执行的补测建议", str(c["accepted_gap_proposals"]), "每份可含多个测试。337 不等于测试函数数。"),
        ("执行通过 / 断言失败 / 无可用执行结果", "298 / 33 / 6", "这是运行状态，不是测试正确率。"),
        ("至少含一个正确、已执行补测的建议", str(c["correct_test_packets"]), "同一缺口可能对应多份建议。主结果按 trial 去重。"),
    ]
    stage_rows = "".join(f'<tr><th>{escape(a)}</th><td>{escape(b)}</td><td>{escape(d)}</td></tr>' for a, b, d in stages)
    anchors = '<p class="nav"><a href="#results">结果</a> · <a href="#setup">设置</a> · <a href="#method">算法</a> · <a href="#execution">执行</a> · <a href="#diagnosis">诊断</a> · <a href="#trials">30 条记录</a> · <a href="#evidence">证据</a></p>'
    text = f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>组合缺口检测与测试补强：30 个 trial 的 pilot</title>
<style>
body{{font-family:system-ui,"Noto Sans CJK SC",sans-serif;line-height:1.8;max-width:1160px;margin:32px auto;padding:0 20px;color:#1e293b;background:#fff}}
h1{{font-size:1.8rem;line-height:1.4}} p{{max-width:100ch}} .lead{{font-size:1.25rem;font-weight:700;margin-top:2.4rem;border-top:1px solid #cbd5e1;padding-top:1rem}}
table{{border-collapse:collapse;width:100%;font-size:.94rem;margin:16px 0 28px}} th,td{{text-align:left;vertical-align:top;border:1px solid #cbd5e1;padding:9px 12px}} th{{background:#f1f5f9}} caption{{text-align:left;font-weight:700;margin-bottom:8px}}
a{{color:#1255a5;text-underline-offset:3px}} .scroll{{overflow-x:auto}} .hit td{{background:#f0fdf4}} details{{border:1px solid #cbd5e1;border-radius:6px;padding:12px 16px;margin:14px 0}} summary{{cursor:pointer;font-weight:650;overflow-wrap:anywhere}} code{{background:#f1f5f9;padding:1px 4px}} .note{{background:#eff6ff;border-left:4px solid #2563eb;padding:12px 16px}} small{{color:#475569}} @media print{{details{{break-inside:avoid}} .nav{{display:none}}}}
</style>
<h1>组合缺口检测与测试补强：30 个 trial 的 pilot</h1>
<p class="note"><strong>当前评估已更换标签：</strong>原 41 个正标签中，7 项保留，6 项撤销，28 项待定。新的主标签要求补测能够暴露原补丁错误，并关联原验收失败。算法命中 T24-G1，漏掉其余 6 项保留目标。请使用<a href="augmentation_pilot30_relabel_20261008.html">最新逐项重标注报告</a>。下文仅保留原覆盖口径的历史结果。</p>
<p class="note"><strong>2026-10-08 更正：</strong>下文的 20/30 和 251 份测试来自初步 AI 审阅。许多同类建议共用批量标签，未经过独立人类逐条核验。这些数字不表示错误检出率或 resolution rate。历史命中也不保证原补丁存在错误。请以<a href="augmentation_pilot30_gold_20261008.html">原补丁与 gold 对照复核报告</a>中的证据边界为准。原始实验与标签文件保持不变。</p>
<p><small>2026-10-07 · 固定样本 · 请求模型 DeepSeek-v4-flash · 源码与实验数据按授权发送到 .env 配置的 provider</small></p>
{anchors}
<p id="results" class="lead">算法在 20 个 trial 中找到真实缺口，并生成正确补测。但它只命中 3 个 trial 的历史预标注目标。</p>
<p>一个 trial 是 agent 完成一次任务的开发记录。记录包含代码阅读、补丁修改和验证过程。本实验选择 30 个不同任务的 trial。每个 trial 在历史审阅中都至少有一项已确认的组合缺口。</p>
<p>组合缺口指验证没有共同检查一组相关条件及其结果。例如，测试分别检查缓存导入和原有缓存，却没有检查导入后是否仍保留原文件。缺口也可能出现在断言中。输入包含组合，不代表测试观察了组合结果。</p>
<p>本次主指标判断每个 trial 是否至少找到一项真实缺口。它允许发现历史标签之外的缺口。另一个指标只判断是否命中选样前的具体目标。两者回答不同问题，必须分别报告。</p>
<table><caption>主要结果</caption><tbody>{metrics}</tbody></table>
<p>历史标签共含 29 项单关系缺口和 12 项多关系缺口。另有 3 项未确认的历史候选，不计入这 41 项。算法命中 3 / 29 项单关系缺口，命中 0 / 12 项多关系缺口。29 个 trial 仍有至少一项历史缺口未检出。</p>
<p>误报按“算法接受的一份缺口建议”计数。{false_positives} 份误报涉及 9 个 trial。正确建议与误报可以出现在同一个 trial。原始回答中还有 1 份误报被结构检查拦下，因此未过滤的误报数为 35。不同候选可能重复报告同一问题。这些数值不代表 {false_positives} 个不同缺口。</p>
<p class="note">本实验只有正例。因此不能估计任务级误报率或特异度，也不能证明零误报。{unknown} 份已接受建议仍待定。它们没有被算作正确检出，也没有被直接算作误报。</p>
<table><caption>按语言计数</caption><thead><tr><th>语言</th><th>至少检出一项真实缺口</th><th>至少一个正确补测</th><th>命中历史目标</th><th>已接受的误报建议</th></tr></thead><tbody>{''.join(by_language)}</tbody></table>
<p id="setup" class="lead">样本、模型和判定标准在调用前固定。</p>
<p>候选池来自此前审阅的 211 条失败记录。其中 160 条记录同时满足两个条件：存在已确认缺口；项目使用当前程序分析支持的 Python、Go 或 TypeScript。每种语言选择 10 个不同任务。每组含 4 个带多关系缺口的 trial，另含 6 个只有单关系缺口的 trial。</p>
<p>程序对种子 <code>20261007-pilot30-v1:</code> 与 trial 名称拼接后的 SHA256 值排序。它在每组按该顺序选样。全组共 18 个只有单关系缺口的 trial，12 个带多关系缺口的 trial。实验未按模型结果换样。分析失败的 T01 仍计入分母。</p>
<p>模型收到任务需求、提交补丁、相关源代码、自动提取的测试和开发步骤。模型没有收到人工缺口标签、参考实现、隐藏验收测试或任务成败标签。历史标签仅用于选样和后续评估。程序没有手动指定 41 项缺口作为生成目标。</p>
<p>所有 1005 次请求使用 <code>deepseek-v4-flash</code>、temperature 0、thinking enabled、high effort，以及 32768 个最大输出 token。每个候选只调用一次。实验没有让模型根据失败结果修复测试，也没有修改预期值。</p>
<p>provider 返回的模型标识是 <code>deepseek-flash</code>。模型目录将它标为 <strong>DeepSeek-V4.1-Flash</strong>。官方更新说明也记录了旧名称的重定向。因此，本实验只能说明该名称在本 provider 上实际服务的版本，不能声称测试了原始 V4.0 权重。参见 <a href="https://api-docs.deepseek.com/updates/">DeepSeek 官方更新说明</a>和{link(RUN / 'provider_models.json', 'provider 模型记录', destination)}。</p>
<p>正确检出必须有公开需求或 API 语义支持。审阅还必须确认原验证没有覆盖所报告的组合。历史标签未收录某个建议，不足以判定它误报。反过来，原测试没有提交到代码库，也不足以证明 agent 未运行过该测试。</p>
<p>正确补测必须实际执行。它还必须保留必要的对象、键、状态和顺序，并用有依据的断言观察组合结果。有效断言在补丁上失败，也算成功生成。语法错误、错误 API、无依据的预期值和环境失败均不算成功。</p>
<p>语义审阅由本次 Codex 助手完成。审阅使用公开需求、原代码、完整 trajectory 和执行日志。它没有调用第二个 DeepSeek 评审器，也没有获得独立人类复核。该结果是可追溯的 pilot 评估，不是人类一致性验证后的金标准。</p>
<p id="method" class="lead">程序分析先找可能未验证的联系，模型再判断该联系是否构成缺口。</p>
<p>程序解析补丁涉及的函数及其测试。它收集调用、结果传递、字段读写、共享状态和条件分支。它用这些联系寻找可能需要共同验证的两端。例如，一个操作写入某个键，另一个操作随后读取同一键。</p>
<p>程序也连接两条相关关系。中间处理必须读取结构、修改状态或影响分支。程序要求共享对象或值的线索，避免只凭相同变量名组合测试。当前实现只搜索短的两关系组合，没有完整建模任意长度流程、并发交错或隐式依赖图。</p>
<p>程序检查原测试是否有相关联合调用和结果观察。若找到此类结构，它保留候选以核对执行证据。本次共有 50 个这样的候选。因此，本次“程序筛选”主要改变提交给模型的问题，没有将所有已有结构的候选从模型调用中删除。</p>
<p>模型根据每个候选及其材料输出一种判断：存在缺口、没有缺口、属于选测问题，或证据不足。对存在缺口的候选，模型直接生成测试。它无需另写一套规则。本次没有模型回答被接受为选测问题。</p>
<p>程序共形成 530 个单关系候选和 475 个多关系候选 ID。这个分类描述程序搜索区域。它不等同于历史缺口分类。475 个多关系候选没有带来任何一项历史多关系目标命中。</p>
<p id="execution" class="lead">执行保留模型原始代码，并单独记录环境修复。</p>
<table><caption>执行过程与计数单位</caption><thead><tr><th>步骤</th><th>数量</th><th>说明</th></tr></thead><tbody>{stage_rows}</tbody></table>
<p>所有有效输出都进入执行，没有只选择容易运行的补测。执行使用原任务镜像和该 trial 的提交补丁。每次运行使用新容器，并禁用网络。测试结果来自原项目的测试框架。TypeScript 的运行结果不证明静态类型正确。</p>
<p>环境修复只处理运行条件。T03 安装了缺少的 pytest。T19 增加项目要求的 analyze 构建标签。T26 使用项目已有的 Mocha、esbuild 和 Node 测试支持。T27 先构建本地 core 包。T30 使用 AVA。原始失败日志和修复后日志均保留。</p>
<p>最后仍有 6 份 T26 测试没有可用执行结果。其中 4 份使用项目未安装的 Vitest。另 2 份依赖当前环境没有启动的数据库服务。前者是模型未适配项目框架，后者是环境限制。两类都没有计作成功。</p>
<p>337 份已接受建议中，{accepted['known_gap'] + accepted['additional_gap']} 份的缺口判断得到审阅支持，{false_positives} 份是误报，{unknown} 份待定。其中 {c['correct_test_packets']} 份至少含一个正确且已执行的补测。正确建议中存在重复目标，因此这个数量不能替代 20 / 30 的 trial 结果。</p>
<p>{c['trials_with_valid_assertion_failure']} 个 trial 出现了有公开契约依据的失败断言。它们来自 {c['valid_assertion_failure_packets']} 份建议，包含重复检查。它们不是 {c['valid_assertion_failure_packets']} 个独立 bug。实验也没有证明这些问题就是原 benchmark 失败的原因。</p>
<p>T11 出现一次候选 ID 碰撞。两个不同调用位置共用同一 ID。调度器只发出了第一项请求，并拒绝第二项。本报告保留这项实现缺陷。实验没有通过重跑修饰结果。调用前还修复过一次混合类型字典键导致的分析崩溃，记录见{link(RUN / 'pre_model_amendment.json', '调用前修订', destination)}。</p>
<p>provider 报告的累计输入为 {s['model']['usage_reported_by_provider']['prompt_tokens']:,} token，累计输出为 {s['model']['usage_reported_by_provider']['completion_tokens']:,} token。这里包括重复候选的完整材料，也包括最终未形成有效答案的调用。它们是本次实验的实际用量，不是单个 trial 的需求。</p>
<p class="lead">三个历史目标的命中结果具有不同含义。</p>
<p><strong>T10，缓存导入。</strong>目标缓存先在同一个分析键下保存 a.py。待导入缓存保存 b.py。新测试导入后读取两者，再重载磁盘缓存。两者均保留，测试通过。这确认补强了验证，不说明原补丁有 bug。</p>
<p><strong>T14，Retry-After。</strong>旧服务端夹具在发送状态码后才设置响应头。新测试先设置 Retry-After，再发送 429，并通过真实上传入口观察重试等待。测试通过。它使用真实时间阈值，未注入可控时钟；因此存在时间噪声风险，也没有独立断言等待上限。</p>
<p><strong>T24，默认解析模式。</strong>旧测试显式指定 put。新测试省略 mode，并提供触发条件但缺少必填字段的输入。公开默认行为要求拒绝该输入，实际补丁却接受了它。有效断言失败，说明该补测揭示了缺陷。</p>
<p id="diagnosis" class="lead">主要不足是目标表达与证据连接，不能只归因于模型能力。</p>
<p><strong>程序没有可靠连接测试编写与执行反馈。</strong>例如，T26 自动恢复的历史测试源文件为 0。模型可见临时脚本的部分编写步骤，却缺少后续修正和成功执行步骤。相关脚本使用 JavaScript，而当前恢复只接受 Python、Go 和 TypeScript 路径。模型因此多次把已经执行的 SQL 检查报告为缺口。</p>
<p><strong>局部程序联系没有表达决定性条件。</strong>例如，T22 只有两个“检查返回对象”的候选。它们没有表达异步递归入口包住同步 schema，并处理非空递归子项的组合。T20 没有连接配置约束与 Go 运行时的含义。增加相同形式的局部候选，不能自动覆盖这些目标。</p>
<p><strong>多关系目标常依赖同一状态及特定顺序。</strong>遗漏包括旧执行结束前重用同一键、没有初始化器的中间依赖、以及两次查询之间的多次真假变化。当前两关系连接没有充分表达这些执行条件。这与 0 / 12 的历史多关系命中结果一致。</p>
<p><strong>模型有时在生成测试时丢失了它已识别的条件。</strong>T29 有一份建议正确指出已缓存 Or 查询的更新问题，却在每次查询时创建新 predicate。测试通过，但没有检查缓存查询。因此该建议算正确判断，不算正确补测。其他保留同一 predicate 的生成测试则出现了有效断言失败。</p>
<p>这轮结果支持优先改进两点：连接测试版本与执行反馈；在候选中保留具体的对象、状态变化顺序和应观察的结果。它不支持仅扩大候选数量。由于没有进行手动候选注入或其他对照，本实验不能把 38 项历史漏检严格分配给程序分析阶段和模型阶段。</p>
<p id="trials" class="lead">30 个 trial 的结果均保留在下表。</p>
<p>“检出”和“补测”允许经审阅确认的其他目标。“历史命中”只计算选样前的 41 项目标。误报和待定按已接受建议计数。展开某条记录可查看目标、具体遗漏和一项有效补测。</p>
<div class="scroll"><table><thead><tr><th>ID</th><th>任务</th><th>语言</th><th>模型调用</th><th>检出</th><th>补测</th><th>历史命中</th><th>误报建议</th><th>待定建议</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{''.join(details)}
<p id="evidence" class="lead">可复核材料</p>
<p>{link(RUN / 'summary.json', '全部统计与逐条结果 JSON', destination)} · {link(RUN / 'protocol.json', '固定实验方案', destination)} · {link(RUN / 'cases.json', '30 条样本', destination)} · {link(RUN / 'evaluation_truth.json', '隔离保存的历史标签', destination)} · {link(RUN / 'evaluation/input_evidence_audit.json', '输入证据连接检查', destination)}。</p>
<p>{link(ROOT / 'scripts/run_augmentation_pilot30.py', '抽样与材料准备脚本', destination)} · {link(ROOT / 'scripts/run_augmentation_pilot30_model.py', '模型调用脚本', destination)} · {link(ROOT / 'scripts/execute_augmentation_pilot30.py', '冻结测试执行脚本', destination)} · {link(ROOT / 'scripts/summarize_augmentation_pilot30.py', '本报告统计脚本', destination)}。</p>
<p>本实验没有修复任务补丁，也没有测量 resolution rate。没有独立负例或基线对照。额外目标及其预期值仍需独立复核。这些限制不改变本轮的直接结果：20 个 trial 获得有效补测；27 个 trial 未命中任何历史目标；原型尚未达到零误报。</p>
</html>'''
    destination.write_text(text)


def input_audit():
    rows = []
    for cid, ident, expected_steps in [
        ("T26", "candidate_ace83f060b8a913bfefe", [71, 74, 80, 81]),
        ("T26", "candidate_66c4e772dd1966d1b75e", [71, 74, 80, 81]),
        ("T03", "candidate_e100ea8b25599caef7c0", [128, 131]),
    ]:
        path = RUN / "cases" / cid / "generation" / ident / "request.json"
        payload = json.loads(read(path)["messages"][-1]["content"])
        history = payload["analysis_candidate"]["trajectory"]
        step_ids = [h["step"].get("step_id") for h in history]
        rows.append({"case": cid, "candidate": ident, "request": receipt(path),
                     "included_step_ids": step_ids, "related_original_step_ids": expected_steps,
                     "missing_related_step_ids": [i for i in expected_steps if i not in step_ids],
                     "recovered_history_sources": read(RUN / "cases" / cid / "prepared.json")["counts"]["historical_test_sources"]})
    write(RUN / "evaluation/input_evidence_audit.json", {"evaluation_only": True, "cases": rows,
          "conclusion": "Name/path retrieval can include script creation while omitting later corrected execution feedback. Source presence and execution must be linked explicitly."})


if __name__ == "__main__":
    input_audit()
    summary = summarize()
    destinations = [ROOT / "docs/archive/20261007_behavioral_gap_pilot_v01_n30.html", RUN / "report.html"]
    for destination in destinations:
        render(summary, destination)
    print(json.dumps({"summary": str(RUN / "summary.json"),
                      "report": str(destinations[0]),
                      "primary": summary["primary_trial_metrics"],
                      "known_targets": summary["known_target_metrics"],
                      "claims": summary["claim_metrics"]}, ensure_ascii=False))
