"""Execution evidence for a candidate; never a semantic bug verdict."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

from .program import evaluate_condition


def probe_environment(candidate, repository, directory):
    probes = []
    seen = set()
    for operation in candidate.get("behavior", {}).get("operations", []):
        location = operation["span"]
        if not location["path"].endswith(".py"):
            continue
        key = (operation["id"], location["line"])
        if key in seen:
            continue
        seen.add(key)
        probes.append({"id": operation["id"], "path": location["path"], "line": location["line"],
                       "reads": [p for p in operation.get("reads", []) if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", p)]})
    for dimension in candidate.get("behavior", {}).get("conditions", []):
        location = dimension.get("span", {})
        if not location.get("path", "").endswith(".py"):
            continue
        accesses = re.findall(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", dimension.get("expression", ""))
        probes.append({"id": dimension["id"], "path": location["path"], "line": location["line"], "reads": accesses})
    if not probes:
        return None, {"status": "activation_unavailable", "reason": "Python probes only; other runtimes retain command logs."}
    root = directory / "probes"
    root.mkdir()
    shutil.copyfile(Path(__file__).with_name("trace_runtime.py"), root / "sitecustomize.py")
    configuration = {"repository": str(repository), "probes": probes, "output": str(directory / "trace.jsonl"), "max_events": 2000}
    (root / "config.json").write_text(json.dumps(configuration))
    env = {**os.environ, "AUGMENTATION_TRACE_CONFIG": str(root / "config.json"),
           "PYTHONPATH": str(root) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")}
    return env, {"status": "configured", "probes": probes}


def collect_feedback(candidate, directory, setup):
    trace = directory / "trace.jsonl"
    if not trace.exists():
        return {**setup, "status": "activation_unavailable", "reason": setup.get("reason", "No Python trace receipt was produced.")}
    records, malformed = [], 0
    for line in trace.read_text().splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            malformed += 1
    events = [r for r in records if r.get("event") == "probe"]
    dimensions = {d["id"]: d for d in candidate.get("behavior", {}).get("conditions", [])}
    for record in events:
        dimension = dimensions.get(record["probe_id"])
        if not dimension:
            continue
        if dimension["kind"] == "predicate":
            values = {}
            for access, value in record["values"].items():
                if not value.get("known"):
                    continue
                parts = access.split(".")
                target = values
                for part in parts[:-1]:
                    if not isinstance(target.get(part, {}), dict):
                        break
                    target = target.setdefault(part, {})
                else:
                    target[parts[-1]] = value["value"]
            record["condition_result"] = evaluate_condition(dimension["expression"], values)
        elif dimension["kind"] == "presence":
            actual = record["values"].get(dimension.get("access"), {})
            record["condition_result"] = {"known": True, "value": actual["present"]} if "present" in actual else {"known": False}
    started = {r["pid"] for r in records if r.get("event") == "trace_started"}
    finished = {r["pid"] for r in records if r.get("event") == "trace_finished"}
    observed = {r["probe_id"] for r in events}
    return {"status": "observed" if events else "no_selected_probe_observed", "events": events[:160],
            "trace_file": str(trace), "total_events": len(events), "event_view_truncated": len(events) > 160,
            "processes_finished": sorted(started) == sorted(finished), "malformed_records": malformed,
            "collection_truncated": any(r.get("truncated") for r in records),
            "unobserved_probes": [p["id"] for p in setup.get("probes", []) if p["id"] not in observed],
            "meaning": "Events retain invocation/entry identity. An unobserved operation can be blocked by a defect; absence is not automatically failed activation."}
