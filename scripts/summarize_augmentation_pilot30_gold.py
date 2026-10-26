"""Build a post-generation gold comparison report from frozen evidence.

No model calls, subject execution, test edits, or patch repairs occur here.
Semantic judgments are explicit review inputs, not inferred from gold passes.
"""
from collections import Counter
from datetime import datetime, timezone
from html import escape
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "experiments/relation_distinction/results/pilot30_20261007_v1"
OUT = RUN / "gold_comparison_v1"
REPORT = ROOT / "docs/archive/20261008_patch_gold_comparison_n30.html"


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def verify(record):
    path = Path(record["path"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], path


def link(path, label):
    return f'<a href="{escape(os.path.relpath(path, REPORT.parent), quote=True)}">{escape(label)}</a>'


def table(headers, rows):
    head = "".join(f"<th>{escape(x)}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


# Concise reader-facing summaries. Longer review judgments remain in the JSON.
CASE_TEXT = {
    "T01": ("重复 batch 输入使底层调用 3 次，预期为 2 次。", "程序分析超时，没有补测。历史目标是 clear 后执行代次交错，以及异常前输出观察。"),
    "T02": ("TTL 辅助函数不接受原始字典；死亡消息头记录了错误的 exchange。", "新增测试在原补丁上全部通过。没有暴露上述错误。历史的跳转上限目标未命中。"),
    "T03": ("跨行抑制和指定 ID 抑制的统计分类错误。", "历史目标未命中。历史标签要求多个指定 ID 的指令覆盖启用全集后改记全部抑制。Gold 保留非空的指定 ID 集合。该预期仍有解释争议。"),
    "T04": ("非单活消费者队列的状态查询返回字典，benchmark 要求 None。", "新增测试发现第一个取消回调抛错后，后续回调不运行。Gold 通过该测试。这是另一个错误。"),
    "T05": ("快照列表和保存接口返回 HTTP 404。", "新增测试主要检查快照数据。Gold 注册了两个接口。历史的短生命周期任务差分目标未命中。"),
    "T06": ("多层路由配置产生错误的 Sunset 响应头。", "新增路由测试在原补丁上通过。它们没有暴露该覆盖冲突。历史的异常响应头目标未命中。"),
    "T07": ("三种数据后端的 robust 缩放结果不满足断言。", "新增缩放测试在原补丁上通过。历史的常量训练后新值目标未命中。Gold 使用中位数与四分位距。"),
    "T08": ("缺失或非法 multipart 结束标记没有抛错。", "新增测试在原补丁上通过。Gold 显式检查结束标记。历史的引号内分号目标未命中。"),
    "T09": ("别名等于主名称时，抛出的异常类型错误。", "没有有效差分测试。Gold 将名称校验错误纳入 provider 错误。历史的别名供值与缺失字段诊断目标未命中。"),
    "T10": ("warm-cache 在输出 JSON 前退出。", "命中历史缓存合并目标，但补测通过原补丁。Gold 换用了缓存类。语义对照没有证明该目标暴露原补丁错误。"),
    "T11": ("5 项 diff/merge 行为失败；构建失败还造成 15 项基线结果缺失。", "此前完成的环境对齐对照找到一项空白处理差分。它与 benchmark 的空白输入和故障分支不同。历史的父删除与多子新增目标未命中。"),
    "T12": ("导入重命名后，检查器仍接受原包名形式的引用。", "没有补测。原补丁还按 import path 查找，gold 按本地名称查找。历史别名碰撞目标涉及同一解析规则，但输入不同。"),
    "T13": ("返回或克隆闭包后，写闭包与读闭包不再共享同一捕获值。", "直接对应历史目标 1。Gold 保留副本内部的捕获单元共享关系。算法没有生成测试。"),
    "T14": ("blob 取消测试没有观察到要求的上传尝试行为。", "命中历史 Retry-After 目标，但补测通过原补丁。两份实现都连接了响应头与等待。它不检查失败的 blob 路径。"),
    "T15": ("前导零 SemVer 被当作合法版本；等值排序的决胜规则也错误。", "前一项直接对应历史目标。Gold 拒绝前导零版本分量。算法没有生成测试。"),
    "T16": ("新测试构建失败，9 项 VM 结果缺失。", "复制环境的补测通过原补丁，但使用了原补丁专有接口。历史的 TypedBindings 开关切换目标未命中。现有日志没有给出具体编译诊断。"),
    "T17": ("5 项测试把已存在的 undefined 当作缺失值。", "直接对应历史目标。Gold 先检查位置或键是否存在。补测使用普通已存在值，漏掉关键输入。"),
    "T18": ("4 项样式重置测试和 1 项零宽 OSC 保留测试失败。", "ASCII 截断补测通过原补丁，却未通过 gold。这个结果不能证明原补丁有错。历史的带 ANSI 尾串目标未命中。"),
    "T19": ("语法分析报告没有按要求输出多行文本。", "新增语法选项测试通过原补丁。它们没有检查失败的格式要求。历史的否定后缀与前缀冲突目标未命中。"),
    "T20": ("一致性哈希集成测试的配置输出不一致。", "没有补测。当前证据不能把差异归因于历史的小数时长或重复配置目标。"),
    "T21": ("benchmark 把 aspect 当函数调用，原补丁返回对象。", "新增状态测试在两份补丁上通过。Gold 提供可调用的 aspect。这些补测没有检查失败的公开入口。"),
    "T22": ("类型检查失败；测试不能导入要求的 recursive 模块。", "没有补测。Gold 提供对应模块和导出。历史的异步递归与同步容器目标未命中。"),
    "T23": ("初始化子作用域时，错误初始化了父容器的单例服务。", "本次确认一项此前待定的补测。它发现子作用域回滚删除父缓存，gold 通过。两者涉及作用域独立性，但失败场景不同。"),
    "T24": ("默认模式的 Zod parser 没有拒绝缺失的条件必填字段。", "命中历史目标 1。4 份建议中的 7 项具名测试暴露同一根因。2 份建议旧标签为其他缺口。不能按 4 个根因计数。"),
    "T25": ("错误栈模式输出了错误字段；清洗顺序也不正确。", "没有补测。历史的递归 cause 清洗与处理回调顺序，尚未确认为这些失败的原因。"),
    "T26": ("排名函数的显式输出泛型导致 8 处 TS2558 错误，随后 254 项结果缺失。", "直接对应历史目标。Gold 声明输出泛型 O。算法生成运行时 SQL 测试，漏掉类型检查要求。"),
    "T27": ("错误状态、重试等待、加载显示和缓存刷新测试失败。", "补测通过原补丁。一项补测还要求 loadError 为原补丁使用的空字符串，benchmark 要求 undefined。三个历史目标均未命中。"),
    "T28": ("React 挂载及批量恢复后，错误快照被观察为新的成功状态。", "直接对应历史的公开结果目标。算法没有生成测试。两份代码都有核心恢复分支，关键仍是挂载后的联合观察。"),
    "T29": ("createPredicate 的返回值不能按要求直接传给查询。", "补测沿用原补丁的额外工厂调用。其状态组合意图合理，但没有检测最先失败的公开 API。Gold 直接返回谓词对象。"),
    "T30": ("minmax 列和行没有按固定最大值扩展。", "新增 span/gap 测试通过原补丁。Gold 为固定最大值轨道分配剩余空间。历史的嵌套自动宽度目标未命中。"),
}


def summarize():
    protocol = read(OUT / "protocol.json")
    review = read(OUT / "semantic_review.json")
    previous = read(RUN / "summary.json")
    old_cases = {x["id"]: x for x in previous["cases"]}
    truth = {x["id"]: x for x in read(RUN / "evaluation_truth.json")}
    verify(protocol["previous_summary"])
    for rec in protocol["previous_reviews"]:
        verify(rec)
    totals = Counter()
    all_pairs = {}
    rows = []
    source_files = 0
    for case in protocol["cases"]:
        cid = case["case"]
        for record in (case["gold"], case["gold_original"], case["candidate_patch"]):
            verify(record)
        local = Counter()
        for item in case["items"]:
            for record in (item["artifact"], item["assessment"], item["candidate_result"]):
                verify(record)
            artifact = Path(item["artifact"]["path"]).parent
            manifest = read(artifact / "manifest.json")
            for file in manifest["files"]:
                verify({"path": artifact / file["source"], "sha256": file["sha256"]})
                source_files += 1
            pair_path = OUT / "cases" / cid / "tests" / item["candidate"] / "comparison.json"
            pair = read(pair_path)
            verify(pair["gold_result"])
            assert pair["artifact_sha256"] == read(item["candidate_result"]["path"])["artifact_sha256"]
            assert pair["artifact_sha256"] == read(pair["gold_result"]["path"])["artifact_sha256"]
            status = pair["candidate_run_status"] + "/" + pair["reference_run_status"]
            local[status] += 1
            totals[status] += 1
            all_pairs[(cid, item["candidate"])] = pair
        benchmark = read(OUT / "cases" / cid / "original_benchmark/ctrf.json")["results"]
        reward = read(OUT / "cases" / cid / "original_benchmark/reward.json")
        assert reward["reward"] == 0
        rows.append({"case": cid, "trial": case["trial"], "task": case["task"],
                     "previous_any_gap": old_cases[cid]["any_confirmed_gap"],
                     "previous_known_hits": old_cases[cid]["detected_known_gap_indices"],
                     "historical_targets": old_cases[cid]["known_gap_targets"],
                     "paired_packet_status": dict(local), "benchmark_summary": benchmark["summary"],
                     "failure_and_finding_zh": CASE_TEXT[cid]})
    assert len(rows) == 30 and len(all_pairs) == 337
    assert set(CASE_TEXT) == {c["case"] for c in review["cases"]} == set(old_cases)

    def witnesses(field, environment=False):
        records = []
        for judgment in review[field]:
            cid, candidate = judgment["case"], judgment["candidate"]
            path = OUT / "cases" / cid / ("environment_pair" if environment else "tests") / candidate / "comparison.json"
            pair = read(path)
            found = []
            for suffix in judgment["test_suffixes"]:
                match = [t for t in pair["tests"] if t["id"].endswith(suffix)]
                assert len(match) == 1, (cid, candidate, suffix)
                assert match[0]["classification"] == "differential_witness", match
                found.extend(match)
            records.append({**judgment, "comparison": str(path.relative_to(ROOT)),
                            "previous_classification": pair["previous_classification"],
                            "whole_packet_gold_status": pair["reference_run_status"], "matched_tests": found})
        return records

    strict = witnesses("strict_witnesses")
    adjusted = witnesses("prior_environment_witnesses", True)
    observed_pairs = {key for key, p in all_pairs.items() if p["counts"]["differential_witness"]}
    assert observed_pairs == {(x["case"], x["candidate"]) for x in strict}
    assert sum(len(x["matched_tests"]) for x in strict) == 9
    for direct in review["historical_targets_with_direct_failure_overlap"]:
        assert direct["index"] in [g["source_gap_index_1based"] for g in truth[direct["case"]]["gaps"]]
        assert direct["detected"] == (direct["index"] in old_cases[direct["case"]]["detected_known_gap_indices"])
    groups = []
    for cid in ["T02", "T04", "T05", "T06", "T10", "T23", "T26"]:
        claims = read(RUN / "evaluation/reviews" / (cid + ".json"))["claims"]
        repeated = Counter(c["reason"] for c in claims).most_common(1)[0]
        groups.append({"case": cid, "all_raw_gap_claims": len(claims),
                       "largest_identical_reason_group": repeated[1], "reason": repeated[0]})
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(), "evaluation_only": True,
        "model_calls": 0, "new_repairs": 0, "observed_resolution_rate_after_augmentation": None,
        "original_selected_trial_resolution_rate": {"resolved": 0, "trials": 30, "selection": "historical failed positive trials"},
        "previous_any_gap_count_provisional": 20, "previous_known_hit_trials": 3,
        "previous_known_hit_entries": 3, "previous_known_entries": 41,
        "paired_packets": 337, "paired_packet_status": dict(totals),
        "strict_differential_trials": sorted({x["case"] for x in strict}),
        "strict_differential_trials_from_previous_confirmed_labels": sorted({x["case"] for x in strict if x["previous_classification"] in {"known_gap", "additional_gap"}}),
        "strict_differential_packets": len(strict), "strict_differential_named_tests": 9,
        "prior_environment_extra_trials": sorted({x["case"] for x in adjusted}),
        "combined_differential_trials_including_prior_environment_adjustment": sorted({x["case"] for x in strict + adjusted}),
        "generated_witness_directly_overlaps_original_benchmark_failure_trials": ["T24"],
        "witnesses": strict, "prior_environment_witnesses": adjusted,
        "historical_direct_overlap_reviewed_examples": review["historical_targets_with_direct_failure_overlap"],
        "review_provenance_examples": groups, "cases": rows,
        "integrity": {"sealed_summary_and_30_reviews_unchanged": True, "frozen_source_files_checked": source_files,
                      "gold_and_candidate_artifact_hashes_match": True, "subject_execution_in_this_summary_script": False},
        "limits": [review["scope"], review["user_constraint"], review["previous_label_correction"],
                   "Gold failures include interface mismatch, oracle disagreement, and potential gold defects. They are not automatically false positives.",
                   "A differential witness does not establish an actual repaired patch or benchmark resolution.",
                   "The six historical overlap examples are not an exhaustive adjudication of all 41 historical oracles."]}
    write(OUT / "summary.json", output)
    return protocol, review, output


def render(protocol, review, summary):
    p = ["""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>30 个 trial：从组合缺口到修复收益的复核</title>
<style>
body{font-family:system-ui,"Noto Sans CJK SC",sans-serif;max-width:1160px;margin:36px auto;padding:0 22px;color:#172b42;line-height:1.85}
h1{font-size:1.85rem;line-height:1.4}p{max-width:100ch}a{color:#155aa5;text-underline-offset:3px}code{background:#eef2f6;padding:1px 4px;overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;font-size:.94rem;margin:18px 0 30px}td,th{border:1px solid #cbd5e1;padding:10px 12px;text-align:left;vertical-align:top}th{background:#f0f4f8}.scroll{overflow-x:auto}
.lead{font-weight:700;font-size:1.18rem;border-top:1px solid #cbd5e1;padding-top:20px;margin-top:36px}.note{padding:14px 18px;background:#edf5ff;border-left:4px solid #2670b8}small{color:#526174}
details{border:1px solid #d2dbe5;padding:12px 16px;border-radius:5px;margin:12px 0}summary{cursor:pointer;font-weight:650;overflow-wrap:anywhere}li{margin:8px 0}@media print{details{break-inside:avoid}body{max-width:none}}
</style></head><body>
<h1>30 个 trial：从组合缺口到修复收益的复核</h1>
<p class="note"><strong>历史标签已修订：</strong>当前 30 个 trial 的 41 项旧正标签已逐项重判。保留 7 项，撤销 6 项，28 项待定。当前历史命中为 T24-G1，其余 6 项保留目标漏检。请使用<a href="augmentation_pilot30_relabel_20261008.html">最新标签与统计报告</a>。下文保留此前 gold 对照的结果与当时的复核范围。</p>
<p><small>2026-10-08 · 对照原补丁、gold patch、生成测试与原 benchmark 记录 · 本次没有调用模型或修复补丁</small></p>
<p class="note"><strong>20/30 不是发现可修复错误的比例。3/30 也不是可提高 resolution rate 的比例。</strong>前者统计初步审阅认可的任意验证缺口。后者统计命中历史目标的任务。两者都没有要求原补丁在新增测试上失败。</p>
<p>本次找到一项最直接的修复线索：T24 的新增测试暴露了与原 benchmark 相同的默认模式错误。原补丁失败，gold patch 通过。T10 和 T14 虽然命中了历史目标，但其对应测试在原补丁上通过。它们补充了验证，没有暴露该目标上的错误。</p>
<p>另一个需要更正的结论是审阅强度。此前保存了逐条标签，但不少标签来自同类建议的批量判定。没有独立人类逐条核验。此前的 20/30 应标为初步 AI 审阅结果。</p>
<p>本报告采用短句、主动语态和单主题段落。读者无需回看此前讨论。</p>
<p class="lead">这些指标分别回答什么问题</p>
"""]
    p.append(table(["概念", "本报告的含义", "不能据此推出"], [
        ["组合验证缺口", "原验证没有共同检查相关条件及其结果。输入组合存在而断言不足，也属于缺口。", "原补丁一定有 bug。"],
        ["任意真实缺口", "认可的缺口可以来自历史标签，也可以是新发现的目标。这里的旧结果仍需更严格复核。", "这个缺口一定影响 benchmark。"],
        ["历史预标注缺口", "首次分析 trajectory 时标出的具体遗漏。历史标注没有用 gold 来保证该遗漏能区分错误补丁。", "它天然具有修复价值，或标签本身不会有解释争议。"],
        ["有效差分测试", "测试输入和预期符合公开要求；同一具名测试在原补丁上失败，在 gold 上通过。", "agent 能修复错误，或修复后整个任务通过。"],
        ["resolution rate", "在固定任务集合中，修复后的补丁通过完整 benchmark 的任务比例。", "可以用新增测试数量或缺口命中率代替。"],
    ]))
    p.append("<p>历史目标属于任意缺口的范围。它们不是按修复价值划分的两类。相同修复根因还可能得到不同旧标签。T24 的两份建议强调默认模式，另两份强调 map 与字段改名，但四份都暴露默认模式下漏做条件检查的问题。</p>")
    p.append("""<p class="lead">实验设置与证据边界</p>
<p>本次沿用原 pilot 的 30 个 trial。一个 trial 是 agent 完成一次任务的记录。它包含代码阅读、补丁修改、测试选择和执行反馈。30 个 trial 对应 30 个不同任务。Python、Go、TypeScript 各 10 个。18 个 trial 只有单关系历史目标，12 个至少含一个多关系目标。</p>
<p>这些样本都来自历史失败记录，并且已有组合缺口标签。历史目标共 41 项，其中单关系 29 项，多关系 12 项。原 pilot 命中 3 项，均为单关系目标。三个尚未确认的历史候选不进入这 41 项。</p>
<p>原 pilot 请求 DeepSeek-v4-flash。Provider 返回模型标识 deepseek-flash，目录名称为 DeepSeek-V4.1-Flash。算法完成 1005 次调用，并接受 337 份测试建议。一份建议可以包含多个具名测试。337 不是独立缺口或独立 bug 的数量。</p>
<p>本次固定原来的测试和预期值，再读取每个任务的 gold patch。Gold 指 benchmark 提供的参考实现。它只用于事后比较，没有进入原模型输入。本次还读取了全部 30 个 trial 的原 benchmark 结果，并核对相关失败测试和源码。</p>
<p>此前已启动的 337 份 gold 对照均已完成。原补丁结果沿用已保存的运行记录。对照使用相同的测试文件和环境配置。测试执行禁用网络。原补丁、gold 和测试都有哈希记录。报告脚本只读这些证据，不运行被测程序。</p>
<p>按你的补充要求，依赖原补丁私有实现或测试辅助代码的情况采用源码语义判断。后续没有修改接口再执行。T11 有一组此前已启动并完成的环境对齐结果：它补齐 Go 构建标签和原测试辅助文件。该组保留为单独证据，不混入 337 份原样对照。</p>
<p>30 个原 trial 的 benchmark reward 都为 0。这个 0/30 只描述选出的失败样本。本次没有让 agent 根据补测继续修复，也没有评估修复后的完整 benchmark。因此，补测后的 resolution rate 和增量都未测量。</p>""")
    p.append(table(["统计口径", "结果", "正确解释"], [
        ["旧口径：找到任意缺口", "20/30", "初步 AI 审阅的覆盖改进结果，不能当作严格人工金标准。"],
        ["旧口径：命中历史目标", "3/30 个 trial；3/41 项目标", "T10、T14、T24。只统计是否找到指定遗漏。"],
        ["原样对照：至少一项有效差分测试", "3/30：T04、T23、T24", "共 6 份建议、9 项具名测试。T23 从旧待定标签得到本次源码支持。"],
        ["上述结果中，旧标签已认定有效的 trial", "2/30：T04、T24", "避免把本次确认的 T23 倒算成旧审阅已确认。"],
        ["另计此前完成的 T11 环境对齐结果", "新增 1 个 trial、1 项具名测试", "合并已保存证据后为 4 个 trial。此合计包含不同环境处理，单独说明。"],
        ["新增测试直接暴露原 benchmark 同一失败", "目前确认 1 个 trial：T24", "这是直接修复线索。其余案例缺少同一失败的证据，不等于证明它们无用。"],
        ["实测 resolution rate 提升", "未测量", "不能把以上任何比例写成修复率。"],
    ]))
    p.append("<p>以上按具名测试判定。T04、T23 和部分 T24 建议同时含有 gold 失败的其他测试。因此，不能说这 6 份建议全部通过 gold。完整建议在原补丁上失败、在 gold 上通过的只有 3 份，均来自 T24。</p>")
    names = {"pass": "通过", "fail": "失败", "error": "未得到有效测试结果"}
    p.append(table(["原补丁", "Gold", "建议数量"], [[names[a], names[b], str(n)] for (a, b), n in ((k.split("/"), v) for k, v in sorted(summary["paired_packet_status"].items()))]))
    p.append("<p>Gold 失败不自动等于误报。失败可能来自私有接口不同、保留的旧测试无法编译、预期解释不同，或 gold 自身没有满足某个边界要求。反过来，gold 通过也不能替代公开要求对测试预期的支持。</p>")
    p.append("""<p class="lead">三个历史命中目标，与修复有什么关系</p>""")
    p.append(table(["任务", "原验证缺什么", "原补丁与 gold 的比较", "修复判断"], [
        ["T10 · 缓存导入", "原测试向空缓存导入，没有检查已有文件与导入文件合并后仍保留，并可从磁盘重载。", "补测通过原补丁。原实现合并 files 后保存。Gold 使用另一种按内容构造的 key；它保留已有条目，添加新 key 后保存。原测试人为设置的 key1 不能直接对应 gold 的内部键。", "有补测价值。未暴露原补丁的 warm-cache JSON 输出错误。"],
        ["T14 · HTTP 重试", "原测试分别检查头解析与等待计算，没有让真实 Retry-After 响应头穿过上传入口并观察等待。", "补测通过原补丁。两份实现都读取 429/503 响应头，与退避时间取较大值，再应用等待上限。Gold 的私有函数名称不同。", "有补测价值。原 benchmark 失败发生在 blob 取消路径。"],
        ["T24 · 条件必填字段", "原验证使用显式 put 模式，没有验证省略模式时仍执行相同检查。", "入口只给局部 mode 设置默认值，却把原 options 传给检查函数。检查函数读到 undefined，跳过条件检查。Gold 在省略 mode 时仍检查。补测在原补丁失败，在 gold 通过。", "直接暴露原 benchmark 的失败。仍未证明 agent 可修复并通过全部测试。"],
    ]))
    p.append("""<p class="lead">历史目标之外，哪些补测具有错误检出价值</p>
<p>T04 将“取消回调抛异常”与“后续回调仍被调用”组合。公开要求支持这个预期。原补丁在回调循环外处理异常。第一个异常会结束循环。Gold 在每次回调内部处理异常。该测试揭示真实行为差异，但原 benchmark 失败检查的是非单活消费者队列的状态查询。</p>
<p>T23 将“子作用域初始化失败”与“父容器已初始化对象保持不变”组合。原补丁回滚时同时删除子缓存和父缓存。Gold 没有删除父缓存。公开要求中的作用域独立性支持测试预期。本次只确认这个具名测试，不确认同份建议中关于重复释放资源的全部要求。</p>
<p>T11 将内容哈希匹配与忽略空白组合。原补丁先用原始文本计算根节点身份，因而可能在空白规则生效前产生替换。已有对照支持这一差异。但是，benchmark 的空白失败使用另一种匹配模式和非空文本。修复前者不保证修复后者，更不保证同时解决 merge 和构建问题。</p>
<p>T29 的状态组合意图有公开语义依据。例如，已建立的 Or 查询应该随普通实体组件（trait）增删更新。问题出在具体测试沿用了原补丁的接口假设：先调用 createPredicate，再调用它返回的工厂。Gold 和 benchmark 直接使用 createPredicate 返回的谓词对象。此前的内部状态失败不能据此变成可比较的修复收益。</p>
<p>T21 也出现了公开接口遗漏。原补丁返回普通 aspect 对象。Benchmark 要求它可调用。新增状态测试绕开了该调用方式，并在两份实现上通过。测试数量增加没有覆盖最先阻止任务通过的要求。</p>""")
    p.append("<p class=\"lead\">私有接口与辅助代码：本次的语义结论</p>")
    p.append(table(["任务", "不能直接比较的原因", "语义结论"], [
        ["T10", "BanditCache 与 CacheManager 的类名、方法和数据布局不同。", "支持缓存合并这个补测意图。原补丁已有通过结果。内部 key 不等价，不能强制移植断言。"],
        ["T14", "生成文件保留了引用原私有重试函数的旧测试。", "源码支持真实响应头到等待的连接。保留代码的编译问题不是组合缺口误报。"],
        ["T11", "Gold 需要 diff 构建标签；部分生成测试需要原测试辅助函数。", "保留先前完成的对照。只有空白测试得到差分证据；其他双方失败的测试仍需按公开要求判断。"],
        ["T16", "DefineTypedValue 是原补丁新增接口。Gold 使用 DefineTyped，并由 VM 选项决定是否执行约束。", "两份代码都复制约束。要求 Env.Set 无条件执行约束属于实现假设，不能直接当作共同契约。"],
        ["T23", "保留的旧测试使用 initializer 配置字段；gold 只支持任务要求的链式方法。", "8 份建议在所选测试执行前就发生类型错误。不能据此否定组合意图。独立回滚测试另行判断。"],
        ["T29", "返回谓词对象与返回工厂函数是公开 API 差异。", "组合意图可以成立，但生成测试继承了错误接口。没有进行动态适配，不能声称 gold 可通过等价改写。"],
    ]))
    p.append("<p>Gold 也不是所有新增边界测试的绝对裁判。T04 的 gold 取消回调修复有效，但它的 active_consumer_tags 直接返回注册标签，未区分 standby。T11 的 IgnoreAttrs 组合测试在两份实现上都失败。应保留公开要求、源码推理和实际观察三个证据来源。</p>")
    p.append("<p class=\"lead\">算法漏掉了哪些直接关联原失败的历史目标</p>")
    p.append(table(["任务 / 历史目标", "原失败与 gold 对照", "本轮结果"], [
        ["T13 / 目标 1", "写闭包改变捕获值后，读闭包仍返回旧值。Gold 用捕获单元的复用映射保留副本内部共享。", "漏检，没有补测。"],
        ["T15 / 目标 1", "v1.02.3 被错误归入合法 SemVer。Gold 拒绝前导零版本分量。", "漏检，没有补测。"],
        ["T17 / 目标 1", "位置或键存在，但值为 undefined。原补丁仍使用默认值。Gold 先判断存在性。", "漏检，补测没有使用 undefined。"],
        ["T24 / 目标 1", "省略模式时，条件必填检查未生效。Gold 执行该检查。", "命中，并生成有效差分测试。"],
        ["T26 / 目标 1", "排名函数不接受显式输出泛型，导致测试构建失败。Gold 声明该泛型。", "漏检，补测集中在运行时 SQL。"],
        ["T28 / 目标 1", "挂载后的公开结果丢失恢复的错误和计数，变成成功状态。核心恢复代码本身不足以证明此路径正确。", "漏检，没有补测。"],
    ]))
    p.append("<p>这六项是本次核实的直接重合案例，其中五项漏检。这是诊断样本，不是对全部 41 项历史预期的穷尽重标注。T12 的历史碰撞目标还得到相同名称解析规则的源码支持，但其具体输入与原失败不同。</p>")
    p.append("<p>T03 说明历史标注也需要检查预期依据。多个指定测试 ID 的抑制指令，合并后覆盖全部启用 ID。此时是否必须改记为全部抑制，存在解释差异。Gold 保留非空的指定 ID 集合。不能把这个历史目标直接称为已知 bug，也不能只因 gold 不采用该预期就宣布历史缺口不存在。</p>")
    p.append("<p class=\"lead\">此前的“任意真实缺口”怎样判定</p>")
    p.append("<p>此前由 Codex 阅读任务要求、原测试、trajectory 和新增测试，再给出缺口标签。测试是否通过，只用于记录执行情况。此前没有用 gold 对每条建议建立差分证据，也没有独立人类审阅者。</p>")
    p.append("<p>记录中的逐条标签，不等于逐条独立核验。旧审阅辅助脚本支持一次为同一 trial 的全部建议赋值，再修改例外。保存的结果中也有大量相同理由。因此，更准确的描述是“按任务和语义类别进行 AI 审阅”。此前“逐项确认”的表述过强。</p>")
    p.append(table(["任务", "原始 gap 建议数", "共用同一审阅理由的最大组"], [[x["case"], str(x["all_raw_gap_claims"]), str(x["largest_identical_reason_group"])] for x in summary["review_provenance_examples"]]))
    p.append("<p>例如，T10 的 130 份原始 gap 建议中有 83 份共用同一理由。T02 为 30/36，T04 为 34/39。共用理由本身不能证明标签错误，但它不能支持“每条都有独立证据链”的说法。</p>")
    p.append("<p>本次逐个核对了上文差分测试，并审查了列出的接口依赖案例。没有重新独立核验全部 337 份建议。因此，我保留旧统计用于追踪，但撤回把 20/30 和 251 份测试称为严格核验结果的解释。旧误报 34 份、待定 41 份也仍属于原审阅口径。</p>")
    p.append("<p>本次不把 104 份 gold 失败建议计为误报，也不把 140 份 gold 执行错误计为漏报。30 个样本都已有正标签，仍不能据此估计无缺口任务上的误报率。</p>")
    p.append("<p class=\"lead\">对下一步方法探索的影响</p>")
    p.append("<p><strong>把验证增量与错误检出分开。</strong>缺口检测回答“哪些行为没有得到共同验证”。修复相关测试还要回答“原补丁是否在这些行为上违反要求”。先保留这个区别，再评价测试是否帮助 agent 改进补丁。</p>")
    p.append("<p><strong>程序关系要连接到公开要求和最终观察。</strong>T26 缺的是类型调用与链式结果，不是 SQL 字符串。T28 缺的是框架挂载后的公开状态，不是 core 中是否有恢复函数。候选提取需要保留这些跨层关系。</p>")
    p.append("<p><strong>测试不能只继承原补丁的接口和预期。</strong>T29 沿用了错误工厂接口。T27 沿用了空字符串状态。让模型先说明缺失输入与公开可观察结果，再绑定代码入口。此步骤不需要增加不断扩大的变异规则集合。</p>")
    p.append("<p><strong>按修复根因合并重复建议。</strong>T24 的四份建议只有一个主要根因。继续生成相近 map 测试不会按相同比例增加任务修复机会。应检查尚未覆盖的要求，例如分支选择、类型约束或失败恢复。</p>")
    p.append("<p><strong>Gold 只用于评估。</strong>本次借助 gold 找出方法偏差。若用这些发现修改算法，就应把这 30 个 trial 视作开发样本。不能在同一组样本上把后续改进直接解释为未见任务上的效果。</p>")
    p.append("<p>可以报告“有效差分测试的任务数”和“与原 benchmark 失败直接重合的任务数”。实际 resolution rate 则必须等待修复后补丁的完整评估。当前 1/30 只表示已确认的直接重合证据，不是已实现的收益，也不是潜在收益的上限。</p>")
    p.append("<p class=\"lead\">30 个 trial 的完整对照</p><p>“旧任意”沿用原 AI 标签。“历史命中”按目标编号显示。点击任务可查看历史目标、两份补丁与原 benchmark 结果。表中不把缺失测试结果当成独立行为 bug。</p>")
    p.append(table(["Trial", "旧任意 / 历史命中", "原 benchmark 失败", "本次结论"], [
        [f'<a href="#{r["case"]}">{r["case"]}</a>', ("是" if r["previous_any_gap"] else "否") + " / " + (", ".join(map(str, r["previous_known_hits"])) or "无"),
         escape(CASE_TEXT[r["case"]][0]), escape(CASE_TEXT[r["case"]][1])] for r in summary["cases"]]))
    for case, row in zip(protocol["cases"], summary["cases"]):
        cid = case["case"]
        targets = "；".join(f'{g["index"]}. {g["description"]}' for g in row["historical_targets"])
        p.append(f'<details id="{cid}"><summary>{cid} · {escape(case["trial"])}</summary>')
        p.append(f'<p>历史目标：{escape(targets)}。</p><p>{escape(CASE_TEXT[cid][1])}</p>')
        counts = "；".join(f'{names[k.split("/")[0]]} / {names[k.split("/")[1]]}：{v} 份' for k, v in sorted(row["paired_packet_status"].items()))
        p.append(f'<p>原补丁 / gold 的建议级结果：{escape(counts) if counts else "没有被算法接受的测试建议"}。</p>')
        p.append('<p>' + ' · '.join([
            link(Path(case["runtime"]["issue"]), "公开任务要求"), link(Path(case["candidate_patch"]["path"]), "原补丁"),
            link(Path(case["gold"]["path"]), "Gold patch"), link(OUT / "cases" / cid / "original_benchmark/ctrf.json", "原 benchmark 结果"),
            link(OUT / "cases" / cid / "benchmark_test.patch", "Benchmark 测试"), link(RUN / "evaluation/reviews" / (cid + ".json"), "旧 AI 标签")]) + '</p>')
        for witness in summary["witnesses"] + summary["prior_environment_witnesses"]:
            if witness["case"] == cid:
                p.append('<p>' + link(ROOT / witness["comparison"], "具名测试对照：" + witness["candidate"]) + ' · ' + link(RUN / "cases" / cid / "generation" / witness["candidate"] / "assessment.json", "原始生成测试") + '</p>')
        p.append('</details>')
    p.append('<p class="lead">复核材料</p><p>' + ' · '.join([
        link(OUT / "summary.json", "本次统计"), link(OUT / "semantic_review.json", "语义判断及边界"), link(OUT / "protocol.json", "固定输入与哈希"),
        link(OUT / "benchmark_failures.json", "30 个 trial 的原失败结果"), link(RUN / "evaluation_truth.json", "历史目标"),
        link(RUN / "evaluation/review_helpers.py", "旧审阅赋值脚本"), link(ROOT / "scripts/summarize_augmentation_pilot30_gold.py", "本报告生成脚本"),
        link(ROOT / "docs/archive/20261007_behavioral_gap_pilot_v01_n30.html", "原 pilot 报告及更正说明")]) + '</p>')
    p.append('</body></html>\n')
    REPORT.write_text("\n".join(p))


if __name__ == "__main__":
    protocol, review, summary = summarize()
    render(protocol, review, summary)
    print(json.dumps({"report": str(REPORT), "paired_packets": summary["paired_packets"],
                      "strict_differential_trials": summary["strict_differential_trials"],
                      "prior_environment_extra_trials": summary["prior_environment_extra_trials"],
                      "integrity": summary["integrity"]}, ensure_ascii=False))
