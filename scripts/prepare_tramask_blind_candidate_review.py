"""Blind treatment identity and model rationales for candidate oracle review."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.study import RUN, now, write_new


if __name__ == "__main__":
    root = RUN / "neutral_candidate_review_v01"
    if root.exists():
        raise FileExistsError(root)
    rows, mappings = [], []
    for summary_path in sorted((RUN / "runs").glob("H*/track_b/M[12]/repeat_*/candidate_execution/rank_*/summary.json")):
        execution = summary_path.parent
        cell = execution.parent.parent
        case_id = cell.parent.parent.parent.name
        plan = read(execution / "plan.json")
        stage = plan["staged"]
        pair_id = "edit_" + hashlib.sha256(str(execution.relative_to(RUN)).encode()).hexdigest()[:12]
        out = root / "packets" / pair_id
        out.mkdir(parents=True)
        issue = out / "issue.md"
        issue.write_bytes((RUN / "inputs" / case_id / "instruction.md").read_bytes())
        comparison_dir = execution / "evaluator_comparator_v01"
        comparison = read(comparison_dir / "plan.json") if (comparison_dir / "summary.json").exists() else None
        p_files = stage["arms"]["p_original"]["full_text"]
        augmented = stage["arms"]["p_candidate"]["full_text"]
        q_files = comparison["staged"]["arms"]["q_original"]["full_text"] if comparison else None
        code = []
        for index, (path, text) in enumerate(sorted(p_files.items())):
            p = out / "code" / f"file_{index:03d}_P_original.txt"
            p.parent.mkdir(exist_ok=True)
            p.write_text(text)
            item = {"subject_path": path, "P_original_test": receipt(p)}
            for name, mapping in [("P_augmented_test", augmented), ("Q_original_test", q_files)]:
                if mapping is None:
                    item[name] = None
                elif mapping[path] == text:
                    item[name] = item["P_original_test"]
                else:
                    dest = p.with_name(f"file_{index:03d}_{name}.txt")
                    dest.write_text(mapping[path])
                    item[name] = receipt(dest)
            code.append(item)
        executions = []
        files = list(execution.glob("repeat_*/*/result.json"))
        if comparison:
            files += list(comparison_dir.glob("repeat_*/*/result.json"))
        for index, path in enumerate(sorted(files)):
            result = read(path)
            e = result.get("execution") or {}
            arm = path.parent.name
            row = {"repeat": path.parent.parent.name, "version": "Q" if arm.startswith("q_") else "P",
                "test_version": "augmented" if arm.endswith("_candidate") else "original",
                "command": e.get("command"), "working_directory": e.get("working_directory"),
                "returncode": e.get("returncode"), "timed_out": e.get("timed_out"),
                "stdout": e.get("stdout", ""), "stderr": e.get("stderr", ""),
                "note": "Raw output, no normalization; shell status is not an assertion verdict."}
            p = out / "executions" / f"execution_{index:02d}.json"
            write_new(p, row)
            executions.append(receipt(p))
        packet = {"pair_id": pair_id, "created_at": now(), "issue": receipt(issue),
            "target": read(cell / "stage_01/planning.json")["target"],
            "original_command": stage["arms"]["p_original"]["command"],
            "test_edits": stage["candidate"]["edits"],
            "Q_edits": read(comparison_dir / "fixed_evaluator_Q.json")["edits"] if comparison else None,
            "code": code, "executions": executions,
            "scope": "Review exact edit and all retained assertions, distinguishing the whole augmented validation from only its newly added component. No method name, generator rationale, method comparison, prior review or automatic classification supplied. Q is an evaluator comparator and is not assumed incorrect; P is not assumed correct."}
        write_new(out / "packet.json", packet)
        rows.append({"pair_id": pair_id, "packet": receipt(out / "packet.json")})
        mappings.append({"pair_id": pair_id, "case_id": case_id, "cell": str(cell),
            "candidate_execution": receipt(summary_path),
            "comparator_execution": receipt(comparison_dir / "summary.json") if comparison else None})
    write_new(root / "index.json", {"created_at": now(), "pairs": rows})
    write_new(RUN / "neutral_candidate_review_mapping_v01.json", mappings)
    write_new(root / "review_protocol.json", {"created_at": now(), "index": receipt(root / "index.json"),
        "reviewers": "Two independent Codex semantic reviewers; no method identity, prior label or other review access.",
        "read_scope": "Only this protocol/index and referenced neutral packet files. No provider, Docker, web, delegation, outside run artifacts or private mapping.",
        "output_top_level_exact_keys": ["reviewer_id", "pair_id", "pair_receipt", "judgments"],
        "judgments": {
            "counterfactual_relevance": "pass/fail/unresolved with code/issue/execution receipts. Relevant, isolated, executable comparison; absent Q remains unresolved and does not automatically disqualify a direct augmentation.",
            "context_legality": "Strict context-only E7: only setup/fixture change preserving operation/input/semantics/original observations and assertions. Added assertions or new test stimuli are general augmentation, not strict context-only. State whether legal as general augmentation separately.",
            "oracle_validity": "Judge the whole augmented validation against independent issue contracts, including retained existing assertions. Also separately record added_component_status=pass/fail/unresolved with its exact scope. Do not infer oracle validity from agreeing with P; do not attribute an old assertion failure to the new edit. State whether evidence independently establishes a newly exposed real P defect, with scope and limits."},
        "each_judgment": "status pass/fail/unresolved, reason with exact code/issue locations, evidence receipts (required for pass/fail), scope. Additional diagnostic fields within judgments allowed.",
        "cost": "Actual start/end per pair and session, tokens null if unavailable; separate ledger and completion_manifest. No masking vote. Preserve initial answers for possible third adjudication.",
        "unit": "Eight physical generated candidates. Dependence across repeated similar edits must be disclosed; no claim of eight independent issues."})
    print(json.dumps({"pairs": len(rows), "index": receipt(root / "index.json")}))
