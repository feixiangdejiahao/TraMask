"""Read authored coverage tables and trace selections; attach primary evidence.

No classification or inferred agent intentions. Recorded excerpts are checked
against their actual ATIF step fields before being embedded in the reader.
"""
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research/deepswe_gap_visuals_20261022"
STATES = {"observed", "gap", "weak", "exposed", "unknown", "not_applicable"}
KINDS = {"plan", "write", "run", "revise", "feedback", "decision"}


def bilingual(value, where):
    assert isinstance(value, dict) and set(value) >= {"zh", "en"}, where
    assert all(isinstance(value[k], str) and value[k].strip() for k in ("zh", "en")), where


def load_visuals(rows):
    files = sorted(STUDY.glob("visuals_*.json"))
    authored = [item for path in files for item in json.loads(path.read_text())]
    assert len(authored) == len(rows) == 211, "Expected one visual record for every trial"
    assert len({r["n"] for r in authored}) == 211
    by_n = {r["n"]: r for r in authored}
    for row in rows:
        item = by_n[row["n"]]
        assert item["trial"] == row["trial"], row["n"]
        table, story = item["gap_table"], item["test_story"]
        bilingual(table["title"], (row["n"], "table title"))
        bilingual(table["note"], (row["n"], "table note"))
        assert table["layout"] in {"matrix", "scenarios", "sequence", "evidence"}
        assert 2 <= len(table["columns"]) <= 8 and 1 <= len(table["rows"]) <= 10
        for label in table["columns"]:
            bilingual(label, (row["n"], "column"))
        states = []
        for scenario in table["rows"]:
            assert len(scenario["cells"]) == len(table["columns"]), row["n"]
            assert isinstance(scenario["steps"], list)
            for cell in scenario["cells"]:
                bilingual(cell, (row["n"], "cell"))
                if "state" in cell:
                    assert cell["state"] in STATES
                    states.append(cell["state"])
        assert states, row["n"]
        if row["decision"] not in {"supported", "plausible"}:
            assert "gap" not in states, (row["n"], "Unconfirmed attribution must not claim a gap")
        for key in ("intro", "takeaway"):
            bilingual(story[key], (row["n"], key))
        assert 1 <= len(story["events"]) <= 8
        steps = [e["step"] for e in story["events"]]
        assert steps == sorted(set(steps)), (row["n"], "Events must follow actual step order")
        for event in story["events"]:
            assert event["kind"] in KINDS
            for key in ("title", "summary", "relation"):
                bilingual(event[key], (row["n"], key))
            assert isinstance(event["quotes"], list)
            for quote in event["quotes"]:
                assert quote["field"] in {"reasoning_content", "message"}
                assert isinstance(quote["text"], str) and quote["text"].strip()
    return by_n


def clip(text, limit):
    if len(text) <= limit:
        return {"text": text, "truncated": False}
    split = int(limit * .7)
    return {"text": text[:split] + "\n\n[…]\n\n" + text[-(limit-split):], "truncated": True}


def commands(step):
    result = []
    for call in step.get("tool_calls", []):
        args = call.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"command": args}
        command = args.get("command", "") if isinstance(args, dict) else ""
        result.append({"tool": call.get("function_name", "tool"),
                       "command": clip(str(command), 4800)})
    return result


def output_text(step):
    output = []
    for part in step.get("observation", {}).get("results", []):
        value = part.get("content", "")
        if not isinstance(value, str):
            continue
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


def enrich_visuals(raw, authored):
    trajectory = json.loads((raw / "trajectory.json").read_text())
    steps = {step["step_id"]: step for step in trajectory["steps"]}
    story = dict(authored["test_story"])

    def enrich(event):
        sid = event["step"]
        assert type(sid) is int and sid in steps, (raw.name, sid)
        source = steps[sid]
        result = dict(event)
        excerpts = []
        for quote in event["quotes"]:
            text = source.get(quote["field"], "")
            offset = text.find(quote["text"])
            assert offset >= 0, (raw.name, sid, quote["field"], "Quote not found in recorded step")
            excerpts.append({**quote, "char_start": offset, "char_end": offset + len(quote["text"]),
                             "before_omitted": offset > 0, "after_omitted": offset + len(quote["text"]) < len(text)})
        result.update({"quotes": excerpts, "timestamp": source.get("timestamp", ""),
                       "actions": commands(source), "output": clip(output_text(source), 2600)})
        return result

    story["events"] = [enrich(event) for event in story["events"]]
    selected = {event["step"] for event in story["events"]}
    references = sorted({sid for r in authored["gap_table"]["rows"] for sid in r["steps"]} - selected)
    story["references"] = []
    for sid in references:
        assert type(sid) is int and sid in steps, (raw.name, sid)
        source = steps[sid]
        quotes = []
        for key in ("reasoning_content", "message"):
            if isinstance(source.get(key), str) and source[key].strip():
                quotes = [{"field": key, "text": source[key][:1800]}]
                break
        story["references"].append(enrich({
            "step": sid, "kind": "reference", "quotes": quotes,
            "title": {"zh": "表格引用的验证记录", "en": "Validation record cited by the table"},
            "summary": {"zh": "此处显示表格所引步骤的记录摘录。", "en": "This is an excerpt of the step cited by the table."},
            "relation": {"zh": "此步骤为表格提供来源定位；它不是额外推断的测试生成动机。",
                         "en": "This step locates evidence for the table; it does not infer an additional test-generation motive."},
        }))
    story["total_steps"] = len(trajectory["steps"])
    story["recorded_events"] = len(story["events"])
    return {"gap_table": authored["gap_table"], "test_story": story}


def visual_summary(records):
    tables = [r["gap_table"] for r in records]
    return {"trials": len(records), "layouts": dict(Counter(t["layout"] for t in tables)),
            "column_counts": dict(Counter(len(t["columns"]) for t in tables)),
            "row_counts": dict(Counter(len(t["rows"]) for t in tables)),
            "authored_events": sum(len(r["test_story"]["events"]) for r in records),
            "authored_quotes": sum(len(e["quotes"]) for r in records for e in r["test_story"]["events"])}
