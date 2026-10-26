"""Execute explicit saved plans, without assigning scientific test verdicts."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
from context_recovery_pilot1_runtime import execute_plan

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--screen-id", required=True)
parser.add_argument("--phase", choices=["baseline", "edited"], required=True)
parser.add_argument("--plan-directory", default="execution_plans")
parser.add_argument("--output-group")
args = parser.parse_args()
if not re.fullmatch(r"S\d{3}", args.screen_id):
    parser.error("Expected a cohort-local screen ID")
if any(not re.fullmatch(r"[a-zA-Z0-9_]+", x) for x in
       [args.plan_directory, args.output_group or "baseline"]):
    parser.error("Directory labels must be simple names")
case = Path(__file__).resolve().parents[1] / "cases" / args.screen_id
names = (["original_delivered", "original_reference", "verifier_delivered", "verifier_reference"]
         if args.phase == "baseline" else ["edited_delivered", "edited_reference"])
for name in names:
    plan_path = case / args.plan_directory / (name + ".json")
    plan = json.loads(plan_path.read_text())
    for repeat in [1, 2]:
        out = case / (args.output_group or args.phase) / name / f"repeat_{repeat:02d}"
        result = execute_plan(plan, out, base_directory=plan_path.parent)
        print(json.dumps({"case": args.screen_id, "plan": name, "repeat": repeat,
                          "status": result["status"], "target_executed": result["target_executed"],
                          "target_returncode": result.get("execution", {}).get("returncode"),
                          "result": str(out / "result.json")}), flush=True)
        if result["status"] != "completed":
            raise SystemExit(2)
