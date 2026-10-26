"""Publish neutral, byte-bound reference pairs for two independent Codex reviews.

No generation rationale, method outputs, old labels, technical judgments,
automatic checklist results or other reviewers' answers enter these packets.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.reserved import load_cases
from tramask_rerun.study import RUN, now, write_new
from tramask_rerun.workflow_primary_v02 import public_packet
from tramask_rerun.variants import _apply


def publish(case, root):
    cid = case["id"]
    pair_id = "pair_" + hashlib.sha256(("neutral-reference-v1:" + cid).encode()).hexdigest()[:12]
    out = root / "packets" / pair_id
    if out.exists():
        raise FileExistsError(out)
    source = RUN / "runs" / cid
    public = public_packet(case)
    binding_path = source / "reserved_fixed_reference.json"
    fixed = Path(read(binding_path)["fixed_counterfactual"]["path"]) if binding_path.exists() else source / "unavailable_counterfactual.json"
    hypothesis = read(fixed) if fixed.exists() else {}
    proposed = hypothesis.get("status") == "proposed" and bool(hypothesis.get("alternative", {}).get("edits"))
    files = {**public["final_sources"], **public["selected_test"]["files"]}
    q_files = _apply(files, hypothesis["alternative"]["edits"]) if proposed else None
    out.mkdir(parents=True)
    (out / "issue.md").write_text(public["issue"])
    file_rows = []
    for index, (path, content) in enumerate(sorted(files.items())):
        p = out / "code" / f"file_{index:03d}_P.txt"
        p.parent.mkdir(exist_ok=True)
        p.write_text(content)
        row = {"subject_path": path, "is_original_test_or_fixture": path in public["selected_test"]["files"], "P": receipt(p)}
        if q_files is not None and q_files[path] != content:
            q = p.with_name(f"file_{index:03d}_Q.txt")
            q.write_text(q_files[path])
            row["Q"] = receipt(q)
        else:
            row["Q"] = row["P"] if proposed else None
        file_rows.append(row)
    paths = list((source / "original_pair_controls_v02").glob("repeat_*/*/result.json"))
    if not paths:
        paths = list((source / "measurement_execution_v01/execution").glob("repeat_*/*_original/result.json"))
    if not paths:
        for baseline in ("runner_qualification_v01", "baseline_capsule", "baseline"):
            paths = list((source / baseline).glob("repeat_*/result.json"))
            if paths:
                break
    paths += list((source / "full_capture_controls_v01").glob("*_original/result.json"))
    observations = []
    provenance = []
    for index, path in enumerate(sorted(paths)):
        d = read(path)
        e = d.get("execution") or {}
        row = {"id": f"execution_{index:02d}", "variant": "Q" if path.parent.name.startswith("q_") else "P",
               "command": e.get("command"), "working_directory": e.get("working_directory"),
               "status": d.get("status"), "returncode": e.get("returncode"), "timed_out": e.get("timed_out"),
               "capture_only_supplement": "full_capture_controls_v01" in path.parts,
               "builds": [{k: b.get(k) for k in ("command", "returncode", "stdout", "stderr", "timed_out")} for b in d.get("builds", [])],
               "stdout": e.get("stdout", ""), "stderr": e.get("stderr", ""),
               "note": "Raw runner output. Shell status alone does not establish assertion outcomes. No normalization."}
        for channel in ("stdout", "stderr"):
            bound = e.get("raw_" + channel)
            if isinstance(bound, dict) and Path(bound["path"]).exists():
                raw = Path(bound["path"])
                target = out / "executions" / f"{index:02d}_{channel}.bin"
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(raw, target)
                row["raw_" + channel] = receipt(target)
        captures = []
        for item in d.get("observations", []):
            # The result contains actual sidecar bytes/content only, not interpretations.
            capture = {k: v for k, v in item.items() if k in {"path", "status", "content", "content_base64", "sha256", "bytes"}}
            captures.append(capture)
        row["sidecar_observations"] = captures
        f = out / "executions" / f"execution_{index:02d}.json"
        write_new(f, row)
        observations.append(receipt(f))
        provenance.append({"published": receipt(f), "source": receipt(path)})
    packet = {"pair_id": pair_id, "created_at": now(), "issue": receipt(out / "issue.md"),
              "original_command": public["selected_test"]["command"],
              "working_directory": public["selected_test"]["working_directory"],
              "target": hypothesis.get("target") if proposed else public["selected_test"].get("target"),
              "counterfactual_available": proposed,
              "Q_edits": hypothesis["alternative"]["edits"] if proposed else [],
              "code": file_rows, "executions": observations, "context_edit": None,
              "scope": "Reference pair semantic review. No context witness is supplied yet. Judge target relevance/isolation/executability and the original observation's oracle against the issue; no masking vote. Missing material remains unresolved."}
    write_new(out / "packet.json", packet)
    return {"pair_id": pair_id, "packet": receipt(out / "packet.json")}, {
        "case_id": cid, "pair_id": pair_id, "fixed_input": receipt(fixed) if proposed else None,
        "source_packet": receipt(source / "target_generation/public_input.json") if (source / "target_generation/public_input.json").exists() else None,
        "execution_provenance": provenance}


if __name__ == "__main__":
    root = RUN / "neutral_reserved_review_v01"
    if root.exists():
        raise FileExistsError(root)
    rows, private = [], []
    for case in load_cases():
        if case.get("partition") != "reserved":
            continue
        row, origin = publish(case, root)
        rows.append(row)
        private.append(origin)
    rows.sort(key=lambda x: x["pair_id"])
    write_new(root / "index.json", {"created_at": now(), "pairs": rows, "review_count": len(rows)})
    write_new(RUN / "neutral_reserved_review_mapping_v01.json", private)
    print(json.dumps({"pairs": len(rows), "index": receipt(root / "index.json")}))
