"""Index the investigator-reviewed cells; assertions reject zero-test receipts."""
import hashlib
import json
from pathlib import Path
import re

RUN = Path(__file__).resolve().parents[1]
CONFIGS = {
    "S036": ("baseline", ["candidate_001"], "baseline", "verifier_tagged"),
    "S037": ("baseline_candidate_001", ["candidate_001"], "baseline_candidate_001", "verifier"),
    "S038": ("baseline_candidate_002", ["candidate_002"], "baseline", "verifier"),
    "S063": ("baseline", ["candidate_001"], "baseline", "verifier"),
    "S045": ("baseline_candidate_001", ["candidate_001", "candidate_002", "candidate_003"], "baseline_candidate_001", "verifier"),
    "S003": ("baseline_exploratory_localized_001", ["exploratory_localized_001"], "baseline_exploratory_localized_001", "verifier"),
}


def cell(sid, folder, label, repeat, reviewed_verdict, script=False):
    root = RUN / "cases" / sid
    path = root / folder / label / f"repeat_{repeat:02d}" / "result.json"
    result = json.loads(path.read_text())
    target = next(step for step in result["steps"] if step["label"] == "target")
    execution = target["execution"]
    stdout, stderr = [Path(target["directory"]) / name for name in ["stdout.bin", "stderr.bin"]]
    text = stdout.read_text(errors="replace") + stderr.read_text(errors="replace")
    assert result["status"] == "completed"
    assert execution["returncode"] == (0 if reviewed_verdict == "PASS" else 1)
    if script:
        assert ("ids 65535 65535" in text and "b'x'" in text) if reviewed_verdict == "PASS" else "ValueError" in text
        counts = {"framework_tests": None, "script_units": 1, "explicit_assertions": 0,
                  "implicit_oracle": "Unchanged operations finish without an uncaught exception"}
    else:
        if "go test" in execution["command"]:
            assert len(re.findall(r"^=== RUN\s+[^\n/]+$", text, re.M)) == 1
        else:
            assert re.search(r"(?:Tests:\s+1 (?:passed|failed)|(?:1 passed|1 failed))", text)
        assert "no tests to run" not in text.lower() and not re.search(r"Tests:\s*0 total\b", text)
        counts = {"executed": 1, "passed": int(reviewed_verdict == "PASS"),
                  "failed": int(reviewed_verdict == "FAIL")}
    return {"attempt": str(path.parent.relative_to(root)), "verdict": reviewed_verdict,
            "actual_test_counts": counts, "returncode": execution["returncode"],
            "result": str(path), "result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "raw_stdout": str(stdout), "raw_stderr": str(stderr),
            "command": execution["command"], "command_sha256": execution["command_sha256"],
            "frozen_plan": str(path.parent / "plan.json"),
            "input_receipts": str(path.parent / "input_receipts.json"),
            "checkpoint_binding": str(path.parent / "checkpoint_validation_binding.json")}


for sid, (baseline, candidates, verifier_folder, verifier_label) in CONFIGS.items():
    verifier = [cell(sid, verifier_folder, verifier_label + "_" + impl, repeat,
                     "FAIL" if impl == "delivered" else "PASS")
                for impl in ["delivered", "reference"] for repeat in [1, 2]]
    summaries = []
    for cid in candidates:
        matrix = {}
        for variant in ["original", "edited"]:
            for impl in ["delivered", "reference"]:
                verdict = "FAIL" if (variant, impl) == ("edited", "delivered") else "PASS"
                matrix[variant + "_" + impl] = [cell(sid, baseline if variant == "original" else cid,
                                                     variant + "_" + impl, repeat, verdict,
                                                     script=sid == "S063") for repeat in [1, 2]]
        prepared = RUN / "cases" / sid / ("prepared_" + cid)
        freeze = prepared / "frozen.json"
        if not freeze.exists():
            freeze = prepared / "projection_manifest.json"
        summaries.append({"candidate_id": cid, "freeze": str(freeze), "matrix": matrix,
                          "repair_matrix_met_twice": True,
                          "semantic_factor_count": 2 if sid == "S045" and cid == "candidate_003" else 1})
    result = {"screen_id": sid, "execution_stage_complete": True, "candidates": summaries,
              "specific_official_verifier": verifier, "successful_candidate_ids": candidates,
              "main_original_test_scope_repair": sid != "S003",
              "outcome_pending_independent_review": "Single-factor Context Repair" if sid != "S003" else
                  "Exploratory localized-operation repair only; full original remains Unresolved",
              "strict_behavioral_masking_confirmed": False,
              "implicit_smoke_oracle": sid == "S063",
              "notes": ["Target counts and failure reasons were inspected before indexing; rc alone is not the test verdict."]}
    if sid in ["S037", "S038"]:
        result["identity_controls"] = "factor_control_identity_reset/"
    if sid == "S038":
        result["failed_prior_candidate"] = {"candidate_id": "candidate_001",
            "reason": "Original empty-logic reference test fails twice; baseline/ retains those receipts."}
    if sid == "S045":
        result["selected_minimal_candidate"] = "candidate_002"
        result["factorial_conclusion"] = "Either latency or serial execution suffices; joint003 is a non-minimal successful superset."
    if sid == "S003":
        result["notes"].append("Only the first pre-existing HTTP operation and all its assertions are preserved; the whole original named test's R failure remains excluded from this repair tally.")
    (RUN / "cases" / sid / "matrix_summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(sid, "summary saved")
