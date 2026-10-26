"""Read-only scientific qualification of the eight frozen target executions.

Writes new audit artifacts, never repairs a model proposal or reruns a subject.
Reporter prefixes are decoded only in a separately labelled diagnostic channel.
They cannot supply absent events or invocation identities.
"""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.evidence import compare_events, validate_receipt
from tramask_rerun.study import RUN, now, write_new


NOTES = {
    ("HF005", "M4", 1): "Jest indentation hides literal events from the strict parser. Raw decoding recovers both channels, but repeated effect anchors have no test/input/call identities. The original basic test already fails on Q; the existing aggregate failure on P remains. No aligned masking feedback is established.",
    ("HF010", "M3", 1): "The comparison only assigns the existing blend_mask to a throwaway name. Neither version calls the added helper; no runtime effect or observation events are emitted.",
    ("HF010", "M3", 2): "Actual blend effect prints exist, but no original-observation channel is emitted. Q already fails test_composite_blend_ranges. The proposed PIPESTATUS command also produces /bin/sh Bad substitution.",
    ("HF010", "M4", 1): "Actual mask-range effect prints exist, but no original-observation channel is emitted. Q already fails test_composite_blend_ranges. The proposed PIPESTATUS command also produces /bin/sh Bad substitution.",
    ("HF012", "M4", 2): "Pytest progress prefixes wrap observation events on P; the proposed effect helper is not invoked. Q already fails six original tests. No paired effect channel exists, and PIPESTATUS causes /bin/sh Bad substitution.",
    ("HS003", "M3", 1): "All selected tests execute uncached in both versions, but the proposed helper is not invoked and neither required channel emits an event.",
    ("HS004", "M4", 1): "The original public logs are retained, but P emits no effect event; Q emits one effect only. Repeated observation anchors omit semantic identities. The no-entries controller setup error already occurs in the original test and is not an added defect. PIPESTATUS also fails under /bin/sh.",
    ("HS004", "M4", 2): "The added helper is not invoked. Neither channel emits an event. Existing no-entries setup error persists, and the proposed PIPESTATUS command fails under /bin/sh.",
}


def literal_events(execution):
    """Decode only whole literal event lines, never source-code excerpts."""
    events, locations = [], []
    for channel in ("stdout", "stderr"):
        for line_no, line in enumerate(execution.get(channel, "").splitlines(), 1):
            match = re.fullmatch(r"\s*[.FEsxX]*TRAMASK_EVENT\s+(\{.*\})\s*", line)
            if not match:
                continue
            try:
                event = json.loads(match[1])
                if event.get("channel") not in {"effect", "observation"}:
                    continue
                compare_events([event], [])  # shared semantic event validation
            except (ValueError, TypeError):
                continue
            events.append(event)
            locations.append({"stream": channel, "line": line_no})
    return events, locations


if __name__ == "__main__":
    rows = []
    for (cid, method, physical_repeat), note in NOTES.items():
        cell = RUN / "runs" / cid / "track_b" / method / f"repeat_{physical_repeat:02d}"
        directory = cell / "target_execution"
        summary = read(directory / "summary.json")
        assert summary["subject_command_executions"] == 12
        audits, repeats = [], {}
        for row in summary["runs"]:
            validate_receipt(row["result"])
            validate_receipt(row["diagnosis"])
            raw, diag = read(row["result"]["path"]), read(row["diagnosis"]["path"])
            execution = raw.get("execution") or {}
            events, locations = literal_events(execution)
            audits.append({"repeat": row["repeat"], "arm": row["arm"], "result": row["result"],
                "strict_diagnosis": row["diagnosis"], "strict_effects": len(diag["effects"]),
                "strict_observations": len(diag["observations"]), "literal_events": events,
                "literal_event_locations": locations, "returncode": execution.get("returncode"),
                "timed_out": execution.get("timed_out"),
                "bad_substitution_observed": "Bad substitution" in execution.get("stderr", "")})
            repeats.setdefault(row["repeat"], {})[row["arm"]] = events
        comparisons = [{"repeat": n, "comparison": compare_events(arms["p_instrumented"], arms["q_instrumented"])}
            for n, arms in sorted(repeats.items())]
        all_both = all(any(e["channel"] == channel for e in arms[arm])
            for arms in repeats.values() for arm in ("p_instrumented", "q_instrumented")
            for channel in ("effect", "observation"))
        aligned = all(c["comparison"]["channels"][channel]["status"] == "aligned"
            for c in comparisons for channel in ("effect", "observation"))
        assert not aligned  # any changed evidence demands renewed manual audit
        audit_path = directory / "technical_audit_v01.json"
        write_new(audit_path, {"created_at": now(), "summary": receipt(directory / "summary.json"),
            "planning": receipt(cell / "stage_01/planning.json"), "case_id": cid, "method": method,
            "physical_repeat": physical_repeat, "subject_command_executions": 12,
            "raw_reporter_prefix_recovery": "Separate diagnostic only: whitespace/Jest and pytest progress prefixes; no value, missing channel or identity invented.",
            "arms": audits, "comparisons": comparisons, "actual_both_channels_every_repeat": all_both,
            "complete_semantic_alignment": aligned, "reason": note,
            "method_output_repaired": False, "new_subject_executions": 0, "new_provider_calls": 0})
        qualification = {"created_at": now(), "qualified_for_stage2": False,
            "status": "measurement_not_qualified_after_actual_execution_audit",
            "planning": receipt(cell / "stage_01/planning.json"), "technical_audit": receipt(audit_path),
            "actual_both_channels_every_instrumented_repeat": all_both,
            "semantic_identity_qualified": False if all_both else None,
            "noninterference_qualified": None, "reason": note,
            "method_output_preserved_without_repairs": True,
            "does_not_establish_absence_of_masking": True}
        write_new(directory / "qualification.json", qualification)
        rows.append({"case_id": cid, "method": method, "physical_repeat": physical_repeat,
            "qualification": receipt(directory / "qualification.json"), "actual_runs": 12,
            "qualified_for_stage2": False, "reason": note})
    write_new(RUN / "track_b_target_execution_audit_v01.json", {"created_at": now(),
        "registered_target_plans": 8, "actual_subject_commands": 96, "qualified_for_stage2": 0,
        "denominator_policy": "Retain all eight cells; these are observed method measurement failures, separate from budget-missing generation.", "cells": rows})
    print(json.dumps({"plans": len(rows), "actual_commands": 96, "qualified": 0}))
