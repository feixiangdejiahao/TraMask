"""Recover a read-only run index from persisted phase reports after interruption.

This never invokes a test, rewrites a report, or infers an outcome from exit codes.
Missing normalized reports remain explicit omissions in the recovery manifest.
"""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def reconstruct(emitted, executions):
    rows, evidence, missing = [], [], []
    for artifact in read(emitted / "artifacts.json"):
        folder = Path(artifact)
        manifest_path = folder / "manifest.json"
        manifest = read(manifest_path)
        evidence.append({"path": str(manifest_path.resolve()),
                         "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()})
        for phase in manifest["phases"]:
            role = phase["role"]
            phase_output = executions / folder.name / role
            result = phase_output / "normalized.json"
            if not result.exists():
                missing.append({"artifact": artifact, "phase": role, "path": str(result)})
                continue
            # Parse solely to reject incomplete/corrupt files; retain the exact report.
            read(result)
            evidence.append({"path": str(result.resolve()),
                             "sha256": hashlib.sha256(result.read_bytes()).hexdigest()})
            items = manifest["controls"] if role == "control" else manifest["obligations"]
            for item in items:
                rows.append({"case": manifest["case"], "candidate_id": item.get("candidate_id"),
                             "execution_lane": manifest["execution_lane"],
                             "static_parent_id": manifest["static_parent_ids"].get(item.get("candidate_id")),
                             "base_test_id": item["base_test_id"],
                             "role": "control" if item["is_control"] else "generated",
                             "test_ids": [item["id"]], "control_ids": item.get("control_ids", []),
                             "result": str(result.resolve()),
                             "execution_context": {"phase": role, "source_snapshot": phase["files"],
                                                   "control_context": manifest["control_context"],
                                                   "context_file": str((phase_output / "context.json").resolve())},
                             "manifest": str(manifest_path.resolve())})
    return rows, evidence, missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--emitted-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    all_rows, cases = [], []
    for artifacts in sorted(args.emitted_root.glob("*/artifacts.json")):
        case = artifacts.parent.name
        rows, evidence, missing = reconstruct(artifacts.parent, args.runs_root / case)
        all_rows.extend(rows)
        cases.append({"case": case, "rows": len(rows), "missing_reports": missing, "evidence": evidence})
    (args.output / "runs.json").write_text(json.dumps(all_rows, indent=2) + "\n")
    (args.output / "recovery_manifest.json").write_text(json.dumps({
        "source": str(Path(__file__).resolve()),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "basis": "existing manifests and unchanged normalized phase reports; no reruns",
        "cases": cases}, indent=2) + "\n")
    print(json.dumps({"cases": len(cases), "rows": len(all_rows),
                      "missing_reports": sum(len(row["missing_reports"]) for row in cases)}))


if __name__ == "__main__":
    main()
