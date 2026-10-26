"""Build the portable bilingual reader from current judgments and primary evidence.

Evidence excerpts are selected for display, never used to generate classifications.
All code, text, styles and scripts needed by the reader are embedded in one HTML.
"""
from collections import Counter
from html import escape
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
from deepswe_gap_visuals import STUDY as VISUAL_STUDY, load_visuals, enrich_visuals, visual_summary

ROOT = Path(__file__).resolve().parents[1]
PRESENTATION = ROOT / "research/deepswe_report_presentation_20261022"
RUN = ROOT / "results/failure_analysis/20261021_counterfactual_gap_n211_r01"
OUTPUT = ROOT / "results/failure_analysis/20261022_standalone_report_n211_r01"
ASSETS = ROOT / "scripts/deepswe_report"
DEST = ROOT / "docs/deepswe_failure_manual_20261006.html"
LABELS = {
    "supported": ("直接支持组合缺口", "Combination gap · supported"),
    "plausible": ("有条件支持组合缺口", "Combination gap · conditional"),
    "non_combination": ("单项或接口问题", "Single-feature / API issue"),
    "insufficient": ("证据不足或契约待定", "Insufficient evidence / unclear contract"),
    "already_exposed": ("正确失败反馈已产生", "Correct failure feedback already available"),
    "unrelated": ("未关联当前失败", "No link to the observed failure"),
}
FIELDS = ("evaluation", "combination", "validation", "counterfactual")


def pack_payload(cases, tasks, labels):
    """Keep a tiny eager manifest; compress independently decoded evidence chunks."""
    chunks = {}
    index = {"schema_version": "deepswe-portable-chunks.v2", "encoding": "gzip-base64",
             "labels": labels, "cases": {}, "tasks": {}, "assets": {}}

    def chunk(identifier, raw):
        packed = gzip.compress(raw, compresslevel=9, mtime=0)
        chunks[identifier] = base64.b64encode(packed).decode("ascii")
        return {"chunk": identifier, "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "compressed_bytes": len(packed)}

    def source_asset(text):
        raw = text.encode()
        identifier = "source-" + hashlib.sha256(raw).hexdigest()
        if identifier not in index["assets"]:
            index["assets"][identifier] = chunk(identifier, raw)
        return identifier

    for task, value in tasks.items():
        index["tasks"][task] = {"asset": source_asset(value["test_patch"])}
    search = {}
    for trial, original in cases.items():
        row = dict(original)
        story = row.pop("test_story")
        story_raw = json.dumps(story, ensure_ascii=False, separators=(",", ":")).encode()
        story_descriptor = chunk(f'story-data-{row["n"]:03}', story_raw)
        row["test_story"] = {"intro": story["intro"], "recorded_events": story["recorded_events"],
                             "total_steps": story["total_steps"],
                             "events": [{k: e[k] for k in ("step", "kind", "title")} for e in story["events"]]}
        assets = {"issue": source_asset(row.pop("issue")),
                  "patch": source_asset(row.pop("patch")),
                  "evaluation": index["tasks"][row["task"]]["asset"]}
        row["assets"] = assets
        identifier = f'trial-data-{row["n"]:03}'
        raw = json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()
        metadata = {k: row[k] for k in ("n", "trial", "task", "repository", "language", "decision", "metric", "metrics")}
        index["cases"][trial] = {**metadata, **chunk(identifier, raw), "assets": assets,
                                 "story": story_descriptor}
        # Full-text search remains exhaustive without decoding every trial.
        values = [trial, row["task"], row["repository"], row["language"], row["decision"],
                  *row["overview"].values(), *row["analysis"]["zh"].values(),
                  *row["analysis"]["en"].values(), *labels[row["decision"]].values(),
                  *(f["name"] for f in row["evaluation"]["failure_index"])]
        values.extend(row["gap_table"]["title"].values())
        values.extend(row["gap_table"]["note"].values())
        for column in row["gap_table"]["columns"]:
            values.extend(column[k] for k in ("zh", "en"))
        for scenario in row["gap_table"]["rows"]:
            for cell in scenario["cells"]:
                values.extend(cell[k] for k in ("zh", "en"))
        values.extend(row["test_story"]["intro"].values())
        for event in row["test_story"]["events"]:
            values.extend(event["title"].values())
        search[trial] = " ".join(values).lower()
    raw_search = json.dumps(search, ensure_ascii=False, separators=(",", ":")).encode()
    index["search"] = chunk("search-index", raw_search)
    # Put the first case before bootstrap, the rest after it. The small index
    # and controls can initialize without waiting for all embedded source data.
    ordered = [index["cases"][trial]["chunk"] for trial in cases]
    ordered += [index["cases"][trial]["story"]["chunk"] for trial in cases]
    ordered += list(index["assets"]) + ["search-index"]
    assert len(ordered) == len(set(ordered)) == len(chunks)
    rendered = [f'<script type="application/octet-stream" id="{key}" data-encoding="gzip-base64">{chunks[key]}</script>' for key in ordered]
    return index, rendered


def read(path):
    return json.loads(path.read_text())


def bilingual(zh, en, tag="span", cls=""):
    attr = f' class="{cls}"' if cls else ""
    return (f'<{tag}{attr} data-lang="zh">{escape(zh)}</{tag}>'
            f'<{tag}{attr} data-lang="en">{escape(en)}</{tag}>')


def clipped(text, limit):
    """Keep both ends, and explicitly mark omissions in the reader."""
    if len(text) <= limit:
        return {"text": text, "truncated": False}
    left = int(limit * .7)
    return {"text": text[:left] + "\n\n[…]\n\n" + text[-(limit-left):], "truncated": True}


def excerpt(text, terms, radius=12, max_lines=120, after=None):
    """Return numbered source lines around literal evidence selectors."""
    lines = text.splitlines()
    # Selector order matters: a precise failing test name must take priority
    # over a broad helper identifier that also occurs in imports or other tests.
    matches = []
    for term in terms:
        hits = [i for i,line in enumerate(lines) if term and term.lower() in line.lower()]
        matches.extend(hits[:1 if after is not None else 3])
    chosen = []
    for i in matches[:8]:
        for n in range(max(0,i-radius), min(len(lines),i+(after if after is not None else radius)+1)):
            if n not in chosen:
                chosen.append(n)
    if not chosen:
        chosen.extend(range(min(len(lines), max_lines)))
    indices = chosen[:max_lines]
    result, previous = [], -2
    for i in indices:
        if i != previous + 1:
            result.append("     …")
        result.append(f"{i+1:5}  {lines[i]}")
        previous = i
    return {"text": "\n".join(result), "truncated": len(indices) < len(lines),
            "matched": bool(matches), "line_count": len(lines)}


def diff_files(patch):
    result = []
    for part in re.split(r"(?=^diff --git )", patch, flags=re.M):
        if not part.startswith("diff --git "):
            continue
        header = part.splitlines()[0]
        found = re.search(r" b/(.*)$", header)
        if not found:
            continue
        lines = part.splitlines()
        result.append({"path": found[1], "text": part,
                       "added": sum(x.startswith("+") and not x.startswith("+++") for x in lines),
                       "removed": sum(x.startswith("-") and not x.startswith("---") for x in lines)})
    return result


def observation_text(step):
    output = []
    for item in step.get("observation", {}).get("results", []):
        value = item.get("content", "")
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict) and "output" in decoded:
                value = str(decoded["output"])
                if "returncode" in decoded:
                    value = f'Exit code: {decoded["returncode"]}\n' + value
        except (ValueError, TypeError):
            pass
        output.append(value)
    return "\n".join(output)


def validation_focus(parts, selectors):
    """Locate test source for comparison; lexical selection changes no judgment."""
    def words(value):
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        return set(re.findall(r"[a-z][a-z0-9]{2,}", value.lower()))
    stop = set("the and with from test tests check checks original agent validation that this were was for not only input inputs output outputs value values same expected actual assertion assertions function return should have has are its but after before while into then which code field fields already still there when where also each one been than can does did final includes using result results".split())
    target = words(" ".join([selectors["en"]["combination"], selectors["en"]["validation"], *selectors["evaluation_terms"]])) - stop
    candidates = []
    for part in parts:
        lines = part["text"].splitlines()
        for i,line in enumerate(lines):
            if not re.search(r"(?:\bfunc\s+Test|\bdef\s+test_|\bfn\s+\w+|\b(?:it|test|describe)\s*\(|\bt\.Run\s*\()", line):
                continue
            score = len(words(line) & target)
            score += sum(10 for term in selectors["evaluation_terms"] if term.lower() in line.lower())
            candidates.append((score, -i, part, line))
    if not candidates:
        if not parts:
            return None
        part = parts[0]
        terms = selectors["evaluation_terms"]
    else:
        _, _, part, anchor = max(candidates, key=lambda c: (c[0],c[1]))
        terms = [anchor]
    return {"source": "submitted_patch", "path": part["path"],
            "excerpt": excerpt(part["text"], terms, 4, 105, after=95)}


def validation_evidence(raw, selectors, patch):
    trajectory = read(raw / "trajectory.json")
    steps = {s["step_id"]: s for s in trajectory["steps"]}
    selected = []
    for sid in selectors["validation_steps"]:
        assert sid in steps, (raw.name, sid)
        step = steps[sid]
        commands = []
        for tool in step.get("tool_calls", []):
            args = tool.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"command": args}
            commands.append(str(args.get("command", json.dumps(args, ensure_ascii=False))))
        output = observation_text(step)
        if commands or output:
            selected.append({"step": sid, "commands": clipped("\n".join(commands), 16000),
                             "output": clipped(output, 5500)})
    test_parts = [p for p in diff_files(patch)
                  if re.search(r"(?:test|spec|__tests__)", p["path"], re.I)]
    # These are final submitted test changes, separate from development-step evidence.
    final_tests = [{"path": p["path"], **excerpt(p["text"], selectors["evaluation_terms"], 8, 90)}
                   for p in test_parts[:3]]
    return {"steps": selected, "final_test_excerpts": final_tests,
            "focus": validation_focus(test_parts, selectors),
            "test_files_in_patch": len(test_parts)}


def failure_evidence(ev, terms):
    tests = read(ev / "ctrf.json")["results"]["tests"]
    failed = [t for t in tests if t["status"] not in ("passed", "skipped")]
    def score(test):
        name = test["name"].lower()
        return sum(10 for term in terms if term.lower() in name) + (0 if "missing from report" in test.get("message", "") else 1)
    selected = sorted(enumerate(failed), key=lambda pair: (-score(pair[1]), pair[0]))[:10]
    focus = [{"name": t["name"], "status": t["status"],
              "message": clipped(t.get("message", ""), 4200)} for _, t in selected]
    stdout = (ev / "test-stdout.txt").read_text(errors="replace")
    return {"failure_count": len(failed), "focus": focus,
            "failure_index": [{"name": t["name"], "status": t["status"]} for t in failed],
            "stdout": excerpt(stdout, terms, 5, 95),
            "reported_statuses": dict(Counter(t["status"] for t in tests))}


def load_content(rows):
    paths = sorted(PRESENTATION.glob("content_*.json"))
    content = [r for p in paths for r in read(p)]
    assert len(content) == 211 and len({r["n"] for r in content}) == 211
    by_n = {r["n"]: r for r in content}
    for row in rows:
        item = by_n[row["n"]]
        assert item["trial"] == row["trial"]
        assert set(item["zh"]) == set(item["en"]) == set(FIELDS)
        for lang in ("zh", "en"):
            item[lang]["combination"] = item[lang]["combination"] or ""
            assert item["overview"][lang]
            for key in FIELDS:
                assert bool(item[lang][key]) == bool(row[key]), (row["n"], lang, key)
        assert item["validation_steps"] and item["evaluation_terms"], row["n"]
    return by_n


def render(rows, summary, protocol):
    content = load_content(rows)
    visual_content = load_visuals(rows)
    cases, tasks, cards = {}, {}, []
    for row in rows:
        item = content[row["n"]]
        raw = ROOT / row["raw_evidence_directory"]
        patch = (raw / "model.patch").read_text()
        task = row["task"]
        test_patch = (RUN / "evaluation_tests" / task / "test.patch").read_text()
        tasks.setdefault(task, {"test_patch": test_patch})
        evidence = failure_evidence(RUN / "evaluation" / row["trial"], item["evaluation_terms"])
        test_excerpt = excerpt(test_patch, item["evaluation_terms"], 10, 240, after=105)
        if not test_excerpt["matched"]:
            test_excerpt["text"] = ""
        case = {"n": row["n"], "trial": row["trial"], "task": task,
                "repository": row["repository"], "language": row["language"],
                "decision": row["decision"], "metric": row["metric"],
                "metrics": row["original_metrics"], "overview": item["overview"],
                "analysis": {lang: item[lang] for lang in ("zh", "en")},
                "issue": (raw / "instruction.md").read_text(), "patch": patch,
                "files": [{k: p[k] for k in ("path", "added", "removed")} for p in diff_files(patch)],
                "evaluation": {**evidence, "test_excerpt": test_excerpt},
                "validation": validation_evidence(raw, item, patch),
                **enrich_visuals(raw, visual_content[row["n"]]),
                "evidence_hashes": {Path(r["path"]).name: r["sha256"]
                                    for r in row["source_receipts"]
                                    if Path(r["path"]).name in ("instruction.md", "model.patch", "trajectory.json", "ctrf.json", "reward.json", "test.patch", "test-stdout.txt")}}
        cases[row["trial"]] = case
        m = row["original_metrics"]
        label = bilingual(*LABELS[row["decision"]])
        cards.append(f'''<details class="trial" id="{escape(row['trial'])}" data-status="{row['decision']}" data-positive="{str(row['positive_under_current_definition']).lower()}">
<summary><span class="case-number">{row['n']:03}</span><span class="case-title"><strong>{escape(row['task'])}</strong><span class="case-repo">{escape(row['repository'])} · {escape(row['language'])} · {escape(row['trial'].rsplit('__',1)[-1])}</span></span><span class="case-scores">F2P {m['f2p_passed']}/{m['f2p_total']}<br>P2P {m['p2p_passed']}/{m['p2p_total']}</span><span class="badge {row['decision']}">{label}</span><span class="chevron" aria-hidden="true">⌄</span></summary>
<div class="case-body"></div></details>''')
    stats = "".join(f'<button class="stat" data-filter="{key}"><strong>{summary["decisions"].get(key,0)}</strong>{bilingual(*LABELS[key])}</button>' for key in LABELS)
    options = "".join(f'<option value="{key}" data-zh="{escape(zh,quote=True)}" data-en="{escape(en,quote=True)}">{escape(zh)}</option>' for key, (zh,en) in LABELS.items())
    labels = {k: {"zh": v[0], "en": v[1]} for k,v in LABELS.items()}
    payload, chunks = pack_payload(cases, tasks, labels)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    css = "\n".join((ASSETS / name).read_text() for name in ("viewer.css", "visuals.css"))
    js = "\n".join((ASSETS / name).read_text() for name in ("loader.js", "visuals.js", "viewer.js"))
    html = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="deepswe-portable" content="standalone-bilingual-v1"><meta name="color-scheme" content="light"><title>DeepSWE · 失败 trial 与组合验证缺口</title><style>{css}</style></head>
<body><header class="masthead"><a class="brand" href="#top">DeepSWE <span>FAILURE ATLAS</span></a><button id="language-toggle" data-language-toggle class="language-toggle" type="button" aria-label="Switch to English">English</button></header>
<main id="top"><section class="intro"><p class="eyebrow">211 TRIALS · 90 TASKS · 75 REPOSITORIES</p>{bilingual('失败 trial 与组合验证缺口','Failed trials & combination testing gaps','h1')}
{bilingual('如果 validation 中有一个有效组合测试，它的反馈是否可能帮助 agent 改进 patch，使 evaluation 通过，或提高部分 F2P / P2P？','Could an effective combination test in validation help the agent improve its patch, pass evaluation, or improve some F2P / P2P outcomes?','p','question')}
<p class="intro-note">{bilingual('逐条连接任务、提交补丁、实际失败与有效验证不足。所有阅读材料均内嵌，可离线使用。','Each trial connects the task, submitted patch, observed failures and validation limitations. All reading material is embedded for offline use.')}</p>
<details class="method"><summary>{bilingual('判定方法与证据边界','How to interpret the judgments and evidence')}</summary><div class="method-grid"><div>{bilingual('什么算组合缺口','What counts as a combination gap','h2')}{bilingual('至少两个有独立意义的条件、功能、状态或操作共同作用于同一对象、数据流或生命周期。需要连接实际 evaluation 失败、有效验证的不足，以及补测反馈可能指导的修复。只改善一项 F2P / P2P 也可以成立。','At least two meaningful conditions, features, states or operations interact through the same object, data flow or lifecycle. A gap must connect an observed evaluation failure, a limitation in effective validation and a plausible repair prompted by a better test. Improving one F2P / P2P outcome can be sufficient.','p')}{bilingual('已有组合输入但只有打印、弱断言或错误预期，也可能缺少有效观察。正确失败反馈已经产生却被忽略时，属于反馈处理问题。公开契约不明确时保留条件或证据不足。','An existing combined input can still lack an effective check when it only prints output, uses a weak assertion or expects the wrong result. Ignored correct failure feedback is a feedback-handling issue. Ambiguous public requirements retain a conditional or insufficient-evidence judgment.','p')}</div><div>{bilingual('怎样阅读证据','How to read the evidence','h2')}{bilingual('F2P 是任务新增测试，P2P 是回归测试；分数保留官方记录。失败行可能含 suite 汇总、参数化重复或未报告条目，不能当作独立缺陷数量。TOC 等任务可能存在测试身份映射问题，需结合日志解释。','F2P refers to task tests and P2P to regression tests; scores retain the official records. Failure rows may include suite summaries, parameterized duplicates or missing report entries, so they are not independent defects. Test-identity mapping issues, including in TOC tasks, require reading the logs.','p')}{bilingual('这是使用 evaluation 证据的事后人工归因。完整 issue、提交 patch 和评价测试补丁已内嵌；开发验证与日志展示明确标注的摘录。未运行新的补测或修复实验，可能收益不是实测增益，也未做独立复标。','These are manual, retrospective judgments using evaluation evidence. Complete issues, submitted patches and evaluation test patches are embedded; development validation and logs are explicitly labeled excerpts. No new tests or repair experiments were run. Potential benefits are not measured gains, and judgments were not independently re-labeled.','p')}</div></div></details></section>
<section class="stats" aria-label="Judgment counts">{stats}</section>
<div class="toolbar"><label class="search-label"><span class="sr-only">{bilingual('搜索','Search')}</span><input id="query" type="search" autocomplete="off" placeholder="搜索任务、项目、失败或组合…" data-zh="搜索任务、项目、失败或组合…" data-en="Search tasks, repositories, failures or combinations…"></label><select id="status" aria-label="Judgment"><option value="" data-zh="全部判定" data-en="All judgments">全部判定</option><option value="positive" data-zh="组合缺口（含有条件）" data-en="Combination gaps (including conditional)">组合缺口（含有条件）</option>{options}</select><button id="expand" type="button">{bilingual('展开结果','Expand results')}</button><button id="collapse" type="button">{bilingual('收起','Collapse')}</button><button data-language-toggle type="button" aria-label="Switch to English">English</button></div>
<div class="result-line"><p id="shown" role="status" aria-live="polite"></p><button id="reset" type="button" class="text-button">{bilingual('重置筛选','Reset filters')}</button></div><section id="trials">{''.join(cards)}</section><p id="empty" hidden>{bilingual('没有匹配的 trial。请调整关键词或判定筛选。','No matching trials. Try different keywords or a different judgment.')}</p>
<footer>{bilingual('211 个 trial 均已审查 · 分析日期 2026-10-21 · 双语阅读版 2026-10-22','All 211 trials reviewed · Analysis: 2026-10-21 · Bilingual reader: 2026-10-22')}<br>{bilingual('直接支持与有条件支持表示证据强度；不代表已通过修复实验确认因果。','Supported and conditional judgments describe evidence strength; they do not establish causality through a repair experiment.')}</footer><noscript><p>请启用 JavaScript 以阅读内嵌证据和切换语言。Enable JavaScript to read the embedded evidence and switch languages.</p></noscript></main>
<script id="report-data" type="application/json">{encoded}</script>{chunks[0]}<script>{js}</script>{''.join(chunks[1:])}</body></html>'''
    DEST.write_text(html)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "deepswe-portable-report.v2", "date": "2026-10-22",
                "trials": len(cases), "tasks": len(tasks), "languages": ["zh", "en"],
                "external_runtime_dependencies": 0, "historical_review_content_displayed": False,
                "embedded_complete": ["issue", "submitted_patch", "evaluation_test_patch"],
                "embedded_excerpts": ["validation_commands_and_outputs", "evaluation_failures", "evaluation_stdout"],
                "html": str(DEST.relative_to(ROOT)), "bytes": len(html.encode()),
                "sha256": hashlib.sha256(html.encode()).hexdigest(),
                "loading": {"encoding": "gzip-base64", "initial_json_bytes": len(encoded.encode()),
                            "trial_chunks": len(cases), "story_chunks": len(cases),
                            "deduplicated_source_chunks": len(payload["assets"]),
                            "search_chunks": 1, "decode_trials_on_expand": True,
                            "decode_full_sources_on_request": True},
                "translation_records": [str(p.relative_to(ROOT)) for p in sorted(PRESENTATION.glob("content_*.json"))],
                "visuals": visual_summary(list(visual_content.values()))}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    visual_record = {"date": "2026-10-22", "scope": "authored coverage visualizations and selected recorded test-generation steps",
                     **manifest["visuals"], "decisions_and_original_scores_changed": False,
                     "records": [{"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                 for p in sorted(VISUAL_STUDY.glob("visuals_*.json"))]}
    (VISUAL_STUDY / "summary.json").write_text(json.dumps(visual_record, ensure_ascii=False, indent=2) + "\n")
    return manifest
