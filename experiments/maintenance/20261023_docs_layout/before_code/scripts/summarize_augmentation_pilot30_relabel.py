"""Apply the explicit pilot30 historical-label revision and render its report.

This script only reads saved subject evidence. It does not call a model, execute
subjects, alter test bytes, repair patches, or rewrite frozen v1 artifacts.
Review decisions live in historical_relabel_v2/review.json, not in this code.
"""
from collections import Counter
from html import escape
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "experiments/relation_distinction/results/pilot30_20261007_v1"
GOLD = RUN / "gold_comparison_v1"
OUT = RUN / "historical_relabel_v2"
REPORT = ROOT / "docs/augmentation_pilot30_relabel_20261008.html"
DECISION = {"retain": "保留正标签", "remove": "撤销正标签", "pending": "待定，不计入正标签"}
EVIDENCE = {"observed": "已有失败记录", "semantic": "源码语义判断", "not_found": "该目标未暴露错误",
            "oracle_unresolved": "预期尚不明确", "hypothesis": "反例尚不完整"}
RELATION = {"direct": "对应原失败行为", "same_rule": "对应同一错误规则",
            "unproven": "验收联系未确认", "not_applicable": "不适用"}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def receipt(path):
    path = Path(path)
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}


def verify(record):
    path = Path(record["path"])
    if not path.is_absolute():
        path = ROOT / path
    assert digest(path) == record["sha256"], str(path)


def anchor(path, title):
    return f'<a href="{escape(os.path.relpath(path, REPORT.parent), quote=True)}">{escape(title)}</a>'


def table(headers, rows):
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def summarize():
    review = read(OUT / "review.json")
    old_truth = read(RUN / "evaluation_truth.json")
    previous = read(RUN / "summary.json")
    protocol = read(GOLD / "protocol.json")
    gold_summary = read(GOLD / "summary.json")
    verify(protocol["previous_summary"])
    for old_review in protocol["previous_reviews"]:
        verify(old_review)
    # Verify the original census receipt before accepting its derived targets.
    verify(read(RUN / "protocol.json")["census"])
    previous_cases = {c["id"]: c for c in previous["cases"]}
    gold_cases = {c["case"]: c for c in protocol["cases"]}
    old_targets = {f'{c["id"]}-G{g["source_gap_index_1based"]}': (c, g)
                   for c in old_truth for g in c["gaps"] if g["class"] in {"S", "M"}}
    reviewed = {r["id"]: r for r in review["targets"]}
    assert len(reviewed) == len(review["targets"]) == len(old_targets) == 41
    assert reviewed.keys() == old_targets.keys()
    assert len(old_truth) == len(previous_cases) == len(gold_cases) == 30

    # Keep the three originally excluded candidates outside the revised 41.
    originally_excluded = [{"case": c["id"], "trial": c["trial"], "original_gap": g}
                           for c in old_truth for g in c["gaps"] if g["class"] == "X"]
    assert len(originally_excluded) == 3
    for case in old_truth:
        for rec in [case["primary_receipt"], case["cross_review_receipt"], *case["original_source_receipts"].values()]:
            verify(rec)
        for key in ["gold", "gold_original", "candidate_patch"]:
            verify(gold_cases[case["id"]][key])

    records = []
    for target_id, judgment in reviewed.items():
        case, gap = old_targets[target_id]
        cid = case["id"]
        index = gap["source_gap_index_1based"]
        decision = judgment["decision"]
        assert decision in DECISION
        assert judgment["fault_evidence"] in EVIDENCE
        assert judgment["failure_link"] in RELATION
        if decision == "retain":
            assert judgment["fault_evidence"] in {"observed", "semantic"}
            assert judgment["failure_link"] in {"direct", "same_rule"}
            assert judgment.get("benchmark_evidence") and judgment.get("gold_comparison")
        if decision == "remove":
            assert judgment["fault_evidence"] == "not_found"
        source_receipts = [receipt(RUN / "cases" / cid / "repository" / path) for path in judgment["source_files"]]
        prior_hits = [c["candidate"] for c in read(RUN / "evaluation/reviews" / f"{cid}.json")["claims"]
                      if index in c["known_gap_indices"]]
        generated_witnesses = []
        for witness in gold_summary["witnesses"]:
            if (witness["case"] != cid or witness["candidate"] not in judgment.get("generated_candidates", [])
                    or decision != "retain"):
                continue
            pair_path = ROOT / witness["comparison"]
            pair = read(pair_path)
            verify(pair["gold_result"])
            for matched in witness["matched_tests"]:
                matches = [t for t in pair["tests"] if t["id"] == matched["id"]]
                assert len(matches) == 1 and matches[0]["classification"] == "differential_witness"
                assert matches[0]["candidate"] == "fail" and matches[0]["reference"] == "pass"
            generated_witnesses.append({"candidate": witness["candidate"], "tests": witness["matched_tests"],
                                        "comparison": receipt(pair_path),
                                        "whole_packet_gold_status": witness["whole_packet_gold_status"]})
        benchmark_dir = GOLD / "cases" / cid / "original_benchmark"
        evidence = {
            "original_review": case["primary_receipt"], "original_cross_review": case["cross_review_receipt"],
            "original_sources": case["original_source_receipts"], "candidate_source_files": source_receipts,
            "gold_patch": receipt(GOLD / "cases" / cid / "gold.patch"),
            "benchmark_tests": receipt(GOLD / "cases" / cid / "benchmark_test.patch"),
            "benchmark_result": receipt(benchmark_dir / "ctrf.json"),
        }
        if (benchmark_dir / "test-stdout.txt").exists():
            evidence["benchmark_stdout"] = receipt(benchmark_dir / "test-stdout.txt")
        records.append({**judgment, "case": cid, "trial": case["trial"], "task": case["task"],
                        "source_gap_index_1based": index, "original_gap": gap,
                        "primary_positive": decision == "retain", "historical_match_candidates": prior_hits,
                        "detected": decision == "retain" and bool(prior_hits),
                        "fault_revealing_test_generated": bool(generated_witnesses),
                        "generated_witnesses": generated_witnesses, "evidence": evidence})

    positive = [r for r in records if r["primary_positive"]]
    pending = [r for r in records if r["decision"] == "pending"]
    removed = [r for r in records if r["decision"] == "remove"]
    detected = [r for r in positive if r["detected"]]
    generated = [r for r in positive if r["fault_revealing_test_generated"]]
    revoked_hits = [r for r in records if r["historical_match_candidates"] and not r["primary_positive"]]
    missing = [r for r in positive if not r["detected"]]
    cases = []
    for old_case in old_truth:
        cid = old_case["id"]
        targets = [r for r in records if r["case"] == cid]
        cases.append({"case": cid, "trial": old_case["trial"], "language": previous_cases[cid]["language"],
                      "positive_targets": [r["id"] for r in targets if r["primary_positive"]],
                      "pending_targets": [r["id"] for r in targets if r["decision"] == "pending"],
                      "removed_targets": [r["id"] for r in targets if r["decision"] == "remove"],
                      "detected_targets": [r["id"] for r in targets if r["detected"]],
                      "generated_targets": [r["id"] for r in targets if r["fault_revealing_test_generated"]],
                      "missed_positive_targets": [r["id"] for r in targets if r["primary_positive"] and not r["detected"]],
                      "task_negative": None})
    summary = {
        "version": review["version"], "date": review["date"], "scope_trials": 30, "historical_targets_reviewed": len(records),
        "decisions": dict(Counter(r["decision"] for r in records)),
        "positive_targets": [r["id"] for r in positive], "positive_trials": sorted({r["case"] for r in positive}),
        "positive_evidence": dict(Counter(r["fault_evidence"] for r in positive)),
        "positive_failure_link": dict(Counter(r["failure_link"] for r in positive)),
        "pending_evidence": dict(Counter(r["fault_evidence"] for r in pending)),
        "by_relation_class": {d: dict(Counter(r["original_gap"]["class"] for r in records if r["decision"] == d))
                              for d in DECISION},
        "historical_target_metrics": {
            "detected_targets": [r["id"] for r in detected], "detected_target_count": len(detected),
            "eligible_target_count": len(positive), "target_recall": len(detected) / len(positive),
            "generated_fault_revealing_targets": [r["id"] for r in generated],
            "generated_fault_revealing_target_count": len(generated),
            "false_negative_targets": [r["id"] for r in missing], "false_negative_target_count": len(missing),
            "eligible_trial_count": len({r["case"] for r in positive}),
            "detected_trial_count": len({r["case"] for r in detected}),
            "generated_fault_revealing_trial_count": len({r["case"] for r in generated}),
            "trials_without_a_detected_positive": sorted({r["case"] for r in positive} - {r["case"] for r in detected}),
            "revoked_old_hit_targets": [r["id"] for r in revoked_hits],
            "revoked_old_hit_target_count": len(revoked_hits),
            "full_337_proposal_false_positive_count": None, "task_false_positive_rate": None,
            "unknown_targets_excluded_from_denominator": len(pending),
            "note": "只评价当前保留的历史目标。两项撤销的旧命中不是全部建议的误报统计。未重新独立评审全部 337 份建议。"
        },
        "generated_witness_named_tests": sum(len(w["tests"]) for r in generated for w in r["generated_witnesses"]),
        "generated_witness_proposals": sum(len(r["generated_witnesses"]) for r in generated),
        "originally_excluded_candidates": len(originally_excluded),
        "actual_resolution_rate_after_repair": None, "new_model_calls": 0, "new_subject_executions": 0,
        "new_patch_repairs": 0, "cases": cases,
        "integrity": {"original_41_targets_accounted_for": True, "original_30_review_hashes_verified": True,
                      "original_summary_hash_verified": True, "original_census_hash_verified": True,
                      "original_targets_and_review_records_overwritten": False},
        "limits": [review["evaluation_caveat"], "只修订 30 个 trial。其他 181 条失败记录未按此定义重标。",
                   "待定目标不是负例。撤销某个目标也不表示该任务不存在其他错误。",
                   "T12 是语义判断并关联同一错误规则，其具体碰撞输入没有运行。",
                   "七项正标签来自七个任务，可能仍有未覆盖的其他失败。修复本项不保证整个任务通过。",
                   "正标签中的观测证据沿用原验收或已完成对照，不表示算法已生成对应补测。"]
    }
    assert set(r["id"] for r in detected) == {"T24-G1"}
    assert set(r["id"] for r in generated) == {"T24-G1"}
    assert len(positive) + len(pending) + len(removed) == 41
    labels = {"version": review["version"], "date": review["date"], "reviewer": review["reviewer"],
              "scope": review["scope"], "positive_definition": review["positive_definition"],
              "original_truth": receipt(RUN / "evaluation_truth.json"), "review_input": receipt(OUT / "review.json"),
              "targets": records, "originally_excluded_candidates": originally_excluded}
    write(OUT / "labels.json", labels)
    write(OUT / "summary.json", summary)
    return review, labels, summary


def render(review, labels, summary):
    records = labels["targets"]
    metrics = summary["historical_target_metrics"]
    p = ['''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>30 个 trial：按错误检出与修复相关性修订历史缺口</title>
<style>
body{max-width:1160px;margin:38px auto;padding:0 22px;font:16px/1.75 system-ui,sans-serif;color:#172b42;background:#fff}h1{font-size:1.8rem;line-height:1.4}a{color:#145aa2;overflow-wrap:anywhere}.note{background:#eff6ff;border-left:4px solid #2965a5;padding:14px 18px}.lead{font-size:1.15rem;font-weight:700;margin-top:32px;border-top:1px solid #cfdae6;padding-top:16px}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;margin:18px 0;font-size:.94rem}th,td{padding:10px 12px;border:1px solid #d2dbe5;text-align:left;vertical-align:top}th{background:#f1f5f9}td:first-child{white-space:nowrap}small{color:#506174}details{border:1px solid #d2dbe5;border-radius:5px;padding:12px 16px;margin:12px 0}summary{font-weight:650;cursor:pointer;overflow-wrap:anywhere}.retain{border-left:5px solid #207c55}.remove{border-left:5px solid #a35229}.pending{border-left:5px solid #8a761b}code{font-size:.92em}li{margin:7px 0}@media print{body{max-width:none}details{break-inside:avoid}}
</style></head><body>
<h1>30 个 trial：按错误检出与修复相关性修订历史缺口</h1>
<p><small>2026-10-08 · 当前标签版本：pilot30-fault-revealing-v2 · 仅修订标签和统计</small></p>
<p class="note">本次逐项修订 41 个历史正标签。保留 7 项，撤销 6 项，另有 28 项待定。当前算法只命中保留标签中的 T24-G1，并为它生成能够暴露原错误的测试。其余 6 项漏检。该结果不是 resolution rate。</p>
<p>本报告只覆盖当前 30 个 trial。一个 trial 是 agent 完成一次任务的记录。一个目标是该记录中遗漏的一项具体组合检查。一个 trial 可以有多个目标。T14-G2 表示第 14 个 trial 的第 2 个历史目标。</p>
<p>本次没有替换样本，也没有增加新目标。原先排除的 3 个候选继续排除。全部 211 条失败记录中的其他 181 条不在本次范围内。</p>
<p class="lead">正标签现在表示什么</p>
<p>原标签回答“验证漏了什么”。新主标签回答“哪项遗漏可以暴露与原任务失败有关的补丁错误”。它需要同时满足以下条件。</p>
<ol><li>原验证没有有效检查这组相关条件及其共同结果。</li><li>公开要求支持输入和预期。该检查能暴露原补丁错误。</li><li>该错误对应原 benchmark 的失败行为，或与其使用同一错误规则。</li></ol>
<p>第三项用于对齐本次的修复率目标。它比单纯发现原补丁的其他边界错误更严格。源码支持错误，但尚未建立验收联系的目标，仍列为待定。这不表示目标无用。</p>
<p>Agent 未运行已有联合测试的情况应归为选测问题。本次保留的七项沿用原逐项记录中的遗漏检查，没有把已知未运行测试改写成新生成需求。</p>
<p>源码语义判断可以支持正标签，但必须说明触发条件和错误路径。T12 使用这一证据。它没有运行新的碰撞输入。其余六项保留目标都有原验收失败记录。T24 还具有已完成的原补丁与 gold 差分测试。</p>
<p>Gold 是 benchmark 提供的参考补丁。Gold 通过不能单独证明预期正确。Gold 编译失败或缺少私有接口，也不能单独证明原补丁错误。公开要求、原行为和失败关联必须共同支持判断。</p>
<p class="lead">材料与实验设置</p>
<p>原 pilot 从已有失败记录中选择 30 个不同任务。Python、Go、TypeScript 各 10 个。原标签共有 29 项单关系目标和 12 项多关系目标。这些是选样时的数量，不是修订后的错误数量。</p>
<p>原算法通过程序分析收集关系、测试和相关开发步骤，再让模型判断缺口并生成测试。它请求 DeepSeek-v4-flash。保存的 provider 记录返回 deepseek-flash，目录名称为 DeepSeek-V4.1-Flash。原实验完成 1005 次模型调用，接受 337 份建议。一份建议可以含多个测试。</p>
<p>原模型没有收到 gold、隐藏验收测试或历史缺口标签。本次在生成结束后使用这些评估材料。新标签因此属于回溯重标注，不能写成实验前就固定的独立金标准。</p>
<p>本次逐项复核 41 个历史目标。复核材料包括公开要求、原验证记录、原补丁、gold、原验收日志和已完成的补测对照。依赖原补丁私有接口的测试只做语义判断。本轮没有调用模型、适配测试、运行被测程序或修复补丁。</p>
<p>逐项判断由 Codex 完成。它不是独立人类复核。此前对 337 份建议的批量判断没有在本轮全部重做。新统计沿用目标匹配记录，并核对保留命中 T24 的具体差分测试。</p>
<p class="lead">重标注结果</p>''']
    p.append(table(["处置", "目标数", "含义"], [
        ["保留", str(summary["decisions"]["retain"]), "已支持原补丁错误，并关联原失败。6 项有原验收记录，1 项为同规则语义判断。"],
        ["撤销", str(summary["decisions"]["remove"]), "对应行为已由原补丁正确处理。测试覆盖仍可改进，但不能计为错误检出目标。"],
        ["待定", str(summary["decisions"]["pending"]), "缺少完整反例、明确预期，或与原验收失败的联系。既不计正例，也不计负例。"],
    ]))
    p.append('<p>保留目标包括 5 项单关系和 2 项多关系。算法命中 1/5 项单关系目标，命中 0/2 项多关系目标。这个小集合经过事后筛选，不能用于推断全部 211 条记录的关系分布。</p>')
    p.append('<p>28 项待定有三种原因。21 项得到源码语义支持，但尚未关联原验收失败。3 项的预期仍有解释边界。4 项尚缺完整合法反例。这些不同证据状态都保留在当前标签中，没有合并成“原补丁正确”。</p>')
    p.append(table(["目标", "缺失组合", "证据", "算法结果"], [
        [f'<a href="#{r["id"]}">{r["id"]}</a>', escape(r["target"]),
         escape(EVIDENCE[r["fault_evidence"]] + "；" + RELATION[r["failure_link"]]),
         "检出，并生成错误检出测试" if r["detected"] else "漏检"]
        for r in records if r["primary_positive"]
    ]))
    p.append('<p>这七项分别位于 T12、T13、T15、T17、T24、T26、T28。T15 还有另一个排序失败。T28 的具体内部错误路径还需定位。保留标签只说明补测可以提供相关错误信号，不保证修复一个目标就通过整个任务。</p>')
    p.append('<p class="lead">原来的三个命中如何变化</p>')
    p.append(table(["旧命中", "当前处置", "依据"], [
        ["T10-G1", "撤销", "导入测试在原补丁通过。原实现合并缓存并保存。它不检查导致原验收失败的 warm-cache JSON 输出。"],
        ["T14-G2", "撤销", "真实 Retry-After 补测在原补丁通过。两份实现都将响应头传入等待计算。原失败位于 blob 取消路径。"],
        ["T24-G1", "保留", "默认模式漏做条件检查。生成测试和原验收都暴露该错误。"],
    ]))
    p.append('<p>T24 的 4 份建议包含 7 项已确认差分测试。它们只对应一个历史目标和一个根因。两份建议的检测说明明确指出默认模式。另两份说明强调字段改名等因素，但测试也触发同一默认模式错误。不能重复计为四个缺口。</p>')
    p.append('<p>三份完整建议在原补丁失败、gold 通过。另一份除有效差分测试外，还含一个 gold 失败的测试。因此，报告按具体测试确认错误信号，不声称四份建议整体都正确。</p>')
    p.append('<p class="lead">检测、补测、误报和漏报</p>')
    p.append(table(["指标", "本次结果", "计数范围"], [
        ["正确检测历史目标", f'{metrics["detected_target_count"]}/{metrics["eligible_target_count"]}（14.3%）', "只用七项保留目标作分母。"],
        ["生成可暴露原错误的组合测试", "1 项目标，1 个 trial", "T24-G1。测试必须实际触发原错误；原补丁通过不算成功检错。"],
        ["漏报", str(metrics["false_negative_target_count"]) + " 项，分布于 6 个 trial", "T12、T13、T15、T17、T26、T28。含程序分析或生成未完成的端到端遗漏。"],
        ["撤销的旧正确命中", str(metrics["revoked_old_hit_target_count"]) + " 项", "T10-G1、T14-G2。若解释成错误警报，这两项不成立；它们仍可能是有效覆盖改进。"],
        ["全部建议的错误警报数量", "未重新确定", "本次没有重新独立评审全部 337 份建议，不能沿用旧覆盖口径的 34 项。"],
        ["任务级误报率", "无法估计", "没有独立确认的无错误任务。撤销一个目标不等于整个任务为负例。"],
        ["实测 resolution rate 提升", "未测量", "本轮没有补测驱动修复及完整验收。"],
    ]))
    p.append('<p>28 项待定不进入召回率分母，也不算漏报。没有保留目标的 trial 仍可能含有效组合错误。因此，1/7 是对当前已确认集合的回溯召回率，不能当作全部 30 个 trial 的完整错误检出率。</p>')
    p.append('<p>原来的 20/30、251 份测试和 3/41 只描述旧覆盖口径。它们不再作为当前错误检出指标。T04、T23 等新增差分发现继续保留在 gold 对照报告中，但不加入这次历史目标的分母。</p>')
    p.append('<p class="lead">全部 41 项的逐项处置</p><p>每项保留原目标编号。展开后可读原验证分别检查了什么、需要补什么、原代码如何处理，以及当前处置依据。源码判断没有冒充新运行结果。</p>')
    for r in records:
        p.append(f'<details class="{r["decision"]}" id="{r["id"]}"><summary>{r["id"]} · {DECISION[r["decision"]]} · {escape(r["target"])}</summary>')
        p.append(f'<p><small>{escape(r["trial"])} · 原关系分类：{escape(r["original_gap"]["class_label"])}</small></p>')
        source_gap = r["original_gap"]["source_gap"]
        original_parts = next((source_gap[k] for k in ["original_separate_checks", "existing_parts", "separate_coverage", "original_checks", "existing_checks", "existing_components", "separate_evidence", "original_tests_check_separately", "original_tests"] if k in source_gap), None)
        if original_parts:
            p.append(f'<p><strong>原验证：</strong>{escape(str(original_parts))}</p>')
        else:
            p.append('<p><strong>原验证：</strong>原逐项记录列出了检查范围。下方链接保留全部上下文。</p>')
        for key, title in [("witness", "组合检查及预期"), ("candidate_behavior", "原补丁行为"),
                           ("gold_comparison", "参考补丁对照"), ("benchmark_evidence", "原验收证据"),
                           ("reason", "处置依据"), ("next_evidence", "尚需证据")]:
            if key in r:
                p.append(f'<p><strong>{title}：</strong>{escape(r[key])}</p>')
        p.append(f'<p>证据类型：{EVIDENCE[r["fault_evidence"]]}。验收关联：{RELATION[r["failure_link"]]}。</p>')
        ev = r["evidence"]
        links = [anchor(ROOT / ev["original_review"]["path"], "原逐项审读"),
                 anchor(ROOT / ev["original_cross_review"]["path"], "原交叉审读"),
                 anchor(ROOT / ev["original_sources"]["instruction.md"]["path"], "公开要求"),
                 anchor(ROOT / ev["original_sources"]["model.patch"]["path"], "原补丁"),
                 anchor(ROOT / ev["gold_patch"]["path"], "gold"),
                 anchor(ROOT / ev["benchmark_result"]["path"], "原验收结果"),
                 anchor(ROOT / ev["benchmark_tests"]["path"], "验收测试")]
        if "benchmark_stdout" in ev:
            links.append(anchor(ROOT / ev["benchmark_stdout"]["path"], "原验收输出"))
        p.append('<p>' + ' · '.join(links) + '</p>')
        p.append('<p>相关原代码：' + ' · '.join(anchor(ROOT / rec["path"], Path(rec["path"]).name) for rec in ev["candidate_source_files"]) + '</p>')
        if r["generated_witnesses"]:
            p.append('<p>已完成差分：' + ' · '.join(anchor(ROOT / w["comparison"]["path"], w["candidate"].replace("candidate_", "测试建议 ")) for w in r["generated_witnesses"]) + '</p>')
        p.append('</details>')
    p.append('<p class="lead">当前文件与复核方法</p>')
    p.append('<p>当前评估入口指向 v2 标签和统计。原 41 项标签、30 份审阅和原 summary 保持冻结。报告脚本核对原材料的哈希，并检查所有目标恰好处置一次。它不运行被测项目。</p>')
    p.append('<p>' + ' · '.join([
        anchor(OUT / "labels.json", "当前完整标签"), anchor(OUT / "review.json", "逐项判断原文"),
        anchor(OUT / "summary.json", "当前统计"), anchor(RUN / "active_evaluation.json", "当前评估入口"),
        anchor(RUN / "evaluation_truth.json", "冻结的旧标签"), anchor(ROOT / "scripts/summarize_augmentation_pilot30_relabel.py", "报告生成脚本"),
        anchor(ROOT / "docs/augmentation_pilot30_gold_20261008.html", "此前 gold 对照报告"),
    ]) + '</p></body></html>')
    REPORT.write_text("\n".join(p) + "\n")


def main():
    review, labels, summary = summarize()
    render(review, labels, summary)
    write(RUN / "active_evaluation.json", {
        "version": review["version"], "scope": "Current 30-trial historical targets only; fault-revealing and linked to original failure",
        "labels": receipt(OUT / "labels.json"), "review": receipt(OUT / "review.json"),
        "summary": receipt(OUT / "summary.json"), "report": receipt(REPORT),
        "archived_validation_only_truth": receipt(RUN / "evaluation_truth.json"),
        "archived_validation_only_summary": receipt(RUN / "summary.json"),
        "rebuild_command": ".venv/bin/python scripts/summarize_augmentation_pilot30_relabel.py",
        "generation_use": "Evaluation only. Do not include the labels, gold, or benchmark evidence in model generation inputs."
    })
    print(json.dumps({"decisions": summary["decisions"], "metrics": summary["historical_target_metrics"],
                      "report": str(REPORT)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
