"""Export explicit public subject files from an already validated checkpoint."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_rerun.reserved import load_cases
from tramask_rerun.runtime import export_checkpoint_files
from tramask_rerun.study import RUN, now, write_new

if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--path", action="append", required=True)
    args = parser.parse_args()
    if not args.output.replace("_", "").isalnum():
        raise ValueError("Output must be a new simple case-local directory")
    case = next(c for c in load_cases() if c["id"] == args.case)
    out = RUN / "runs" / case["id"] / args.output
    if out.exists():
        raise FileExistsError("Existing export retained")
    write_new(out / "plan.json", {"case_id": case["id"], "created_at": now(),
        "checkpoint": case["checkpoint"], "paths": sorted(set(args.path)),
        "scope": "Read-only exact file export; no subject execution or state modification."})
    result = export_checkpoint_files(case["checkpoint"], out / "export", sorted(set(args.path)), resources=case["resources"])
    print(json.dumps({"case_id": case["id"], "status": result["status"],
        "files": [{k: f.get(k) for k in ("path", "status", "bytes", "sha256")} for f in result["files"]]}))
