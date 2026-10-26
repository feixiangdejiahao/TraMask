"""One supplemental P/Q execution preserving the selected test and its inputs.

Only a terminal tail filter is removed, to retain the actual assertion failure.
The existing three-repeat controls remain the stability evidence.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.runtime import execute_variant
from tramask_rerun.study import RUN, now, write_new

if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--case", choices=["F010", "F032"], required=True)
    args = parser.parse_args()
    root = RUN / "runs" / args.case
    old = root / "original_pair_controls_v01/plan.json"
    plan = read(old)
    command, changed = re.subn(r"\s*\|\s*tail -\d+\s*$", "", plan["effective_command"])
    if changed != 1:
        raise ValueError("Expected exactly one terminal output filter")
    out = root / "full_capture_controls_v01"
    if out.exists():
        raise FileExistsError("Supplemental attempt already exists")
    write_new(out / "plan.json", {"created_at": now(), "case_id": args.case,
        "original_control_plan": receipt(old), "original_command": plan["effective_command"],
        "effective_command": command, "subject_commands": 2,
        "interpretation": "Runner-only full-output capture; unchanged test selection, inputs, source Q, build and environment. Does not replace previous controls or independently establish stability.",
        "implementation": [receipt(Path(__file__)), receipt(ROOT / "src/tramask_rerun/runtime.py")]})
    records = []
    for variant, files in plan["variants"].items():
        dest = out / variant
        result = execute_variant(plan["checkpoint"], dest, command, plan["test_timeout_seconds"],
            files=files, observation_paths=plan["observation_paths"], build_commands=plan["build_commands"],
            env=plan["environment"], workdir=plan["working_directory"], resources=plan["resources"],
            production_paths=plan["production_paths"], generated_runtime=plan["generated_runtime"])
        records.append({"variant": variant, "result": receipt(dest / "result.json")})
    write_new(out / "summary.json", {"case_id": args.case, "created_at": now(), "runs": records,
        "status": "captured_pending_assertion_review", "scientific_label": None})
    print(json.dumps({"case_id": args.case, "runs": len(records), "status": "captured"}))
