"""Offline evidence and explicit semantic judgments for the evolution pilot.

The online runner never imports this module or reads the evaluation directory.
Reference executions require a separately reviewed portability allowlist.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from scripts.run_validation_evolution_pilot import RUN, ORIGINAL, ARMS, REPEATS, read, check, method
from augmentation.pipeline import write_json
from combination_testing.runner import run_artifact, freeze_artifact, load_artifact, compare_pair

EVAL = RUN/"evaluation"


def inventory():
    tasks, targets = [], []
    for path in sorted(RUN.glob("runs/*/*/*/result.json")):
        row = read(path)
        key = f"{row['case']}/{row['arm']}/{row['repeat']}"
        directory = path.parent
        prefix = RUN/row["shared_prefix"] if row.get("shared_prefix") else directory
        task = {"key": key, **row, "path": str(path.relative_to(RUN)),
                "investigation": read(prefix/"stage1/parsed.json"),
                "queries": read(prefix/"retrieved.json"),
                "hypotheses": read(prefix/"stage2/parsed.json"),
                "draft": read(directory/"stage3/parsed.json")}
        tasks.append(task)
        ranks = {h["id"]: i for i, h in enumerate(task["hypotheses"].get("hypotheses", []), 1)}
        for target in row["final"].get("targets", []):
            rank = ranks[target["id"]]
            out = directory/"final_execution"/target["id"]
            targets.append({"key": key+"/"+target["id"], "task_key": key, "case": row["case"], "arm": row["arm"],
                            "repeat": row["repeat"], "rank": rank, "target": target,
                            "execution_path": str(out.relative_to(RUN)), "feedback": read(out/"feedback.json"),
                            "draft": next((r for r in task["draft"].get("targets", []) if r["id"] == target["id"]), None),
                            "hypothesis": next((r for r in task["hypotheses"].get("hypotheses", []) if r["id"] == target["id"]), None)})
    write_json(EVAL/"inventory.json", {"tasks": tasks, "targets": targets})
    return tasks, targets


def prepare_sources():
    receipts = []
    for case in read(RUN/"cases.json"):
        out = EVAL/"gold_sources"/case["id"]
        record_path = EVAL/"gold_source_receipts"/(case["id"]+".json")
        if record_path.exists():
            receipts.append(read(record_path)); continue
        if out.exists():
            raise RuntimeError("incomplete_gold_source_copy:"+case["id"])
        shutil.copytree(case["repository"], out, symlinks=True, ignore=shutil.ignore_patterns(".git", "node_modules", "vendor", ".venv", "__pycache__", ".env", ".env.*"))
        patch = ORIGINAL/"gold_comparison_v1/cases"/case["id"]/"gold.patch"
        # git apply otherwise discovers the research workspace's parent .git
        # and can silently skip subject-relative paths from this subdirectory.
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(out.parent.resolve())}
        env.pop("GIT_DIR", None); env.pop("GIT_WORK_TREE", None)
        discovery = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=out, env=env, capture_output=True)
        if discovery.returncode == 0:
            raise RuntimeError("unexpected_parent_repository_discovery")
        records = []
        for args in (["git", "apply", "--reverse", str(case["candidate_patch"])], ["git", "apply", str(patch)]):
            done = subprocess.run(args, cwd=out, env=env, capture_output=True, text=True)
            records.append({"command": args, "returncode": done.returncode, "stderr": done.stderr[:3000]})
            if done.returncode:
                write_json(record_path, {"case": case["id"], "complete": False, "steps": records})
                raise RuntimeError("gold_source_materialization_failed:"+case["id"])
        changed_files = [str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() and not p.is_symlink()
                         and (Path(case["repository"])/p.relative_to(out)).is_file()
                         and p.read_bytes() != (Path(case["repository"])/p.relative_to(out)).read_bytes()]
        if not changed_files:
            raise RuntimeError("reference_copy_has_no_changes")
        result = {"case": case["id"], "complete": True, "steps": records, "changed_files": changed_files,
                  "parent_git_discovery_disabled": True,
                  "candidate_patch_sha256": method.previous.digest(case["candidate_patch"]),
                  "gold_patch_sha256": method.previous.digest(patch)}
        write_json(record_path, result); receipts.append(result)
    print(json.dumps({"gold_source_copies": len(receipts), "complete": all(r["complete"] for r in receipts)}), flush=True)


def gold_one(row):
    case = next(c for c in read(RUN/"cases.json") if c["id"] == row["case"])
    directory = RUN/row["execution_path"]
    if not (directory/"artifact/manifest.json").exists():
        return {"key": row["key"], "status": "no_executable_artifact"}
    # Historical environment knowledge only, evaluator side. Retain all test
    # bytes and apply the public diff build tag to BOTH implementations.
    if row["case"] == "T11":
        source = directory/"artifact"
        manifest = load_artifact(source)
        directory = directory/"aligned_diff_tag"
        if not (directory/"artifact/manifest.json").exists():
            files = {r["target"]: (source/r["source"]).read_text() for r in manifest["files"]}
            freeze_artifact(directory/"artifact", row["case"], files,
                            manifest["command"].replace("go test ", "go test -tags diff ", 1),
                            manifest["report"]["format"], manifest["report"]["path"], timeout=300,
                            metadata={"evaluator_only_alignment": "Same test bytes and diff build tag on both versions."})
    if (directory/"comparison.json").exists():
        return read(directory/"comparison.json")
    a = read(directory/"candidate/result.json") if (directory/"candidate/result.json").exists() else run_artifact(directory/"artifact", "candidate", directory/"candidate", registry=[case])
    b = read(directory/"gold/result.json") if (directory/"gold/result.json").exists() else run_artifact(directory/"artifact", "reference", directory/"gold",
                  reference_patch=ORIGINAL/"gold_comparison_v1/cases"/row["case"]/"gold.patch", registry=[case])
    pair = compare_pair(a, b)
    pair.update(key=row["key"], evaluation_only=True)
    write_json(directory/"comparison.json", pair)
    return pair


def gold(workers):
    _, rows = inventory()
    approvals = read(EVAL/"portability.json")["approved_keys"]
    selected = [r for r in rows if r["key"] in approvals]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(gold_one, r): r["key"] for r in selected}
        for future in as_completed(futures):
            r = future.result()
            print(json.dumps({k:r[k] for k in ["key", "counts", "status"] if k in r}), flush=True)


def summary():
    protocol = check()
    tasks, targets = inventory()
    labels = read(EVAL/"review.json") if (EVAL/"review.json").exists() else {"targets": {}, "tasks": {}}
    criteria = read(EVAL/"criteria.json")
    fixed = {t["id"] for t in criteria["fixed_targets"]}
    scored = [{**r, "review": labels.get("targets", {}).get(r["key"], {})} for r in targets]
    aggregates = []
    for arm in ARMS:
        for repeat in REPEATS:
            selected_tasks = [r for r in tasks if r["arm"] == arm and r["repeat"] == repeat]
            selected = [r for r in scored if r["arm"] == arm and r["repeat"] == repeat]
            for cutoff in [1, 3]:
                rows = [r for r in selected if r["rank"] <= cutoff]
                hits = {h for r in rows for h in r["review"].get("fixed_hits", [])}
                detection = [r for r in rows if r["review"].get("detection") == "repair_relevant_gap"]
                generation = [r for r in rows if r["review"].get("generation") == "correct_repair_relevant_test"]
                rejected = [r for r in rows if r["review"].get("false_positive") is True]
                unresolved = [r for r in rows if r["review"].get("detection") == "unresolved"]
                aggregates.append({"arm": arm, "repeat": repeat, "target_prefix": cutoff,
                                   "completed_tasks": len(selected_tasks), "reported_targets": len(rows),
                                   "correct_detection_tasks": sorted({r["case"] for r in detection}),
                                   "correct_generation_tasks": sorted({r["case"] for r in generation}),
                                   "correct_detection_targets": [r["key"] for r in detection],
                                   "correct_generation_targets": [r["key"] for r in generation],
                                   "false_positive_tasks": sorted({r["case"] for r in rejected}),
                                   "false_positive_targets": [r["key"] for r in rejected],
                                   "unresolved_positive_targets": [r["key"] for r in unresolved],
                                   "unresolved_positive_tasks": sorted({r["case"] for r in unresolved}),
                                   "generation_dynamic_targets": [r["key"] for r in generation if r["review"].get("generation_evidence") == "dynamic_pair"],
                                   "generation_static_targets": [r["key"] for r in generation if r["review"].get("generation_evidence") == "static_semantics"],
                                   "fixed_hits": sorted(hits), "fixed_misses": sorted(fixed-hits),
                                   "technical_unknown_tasks": [r["case"] for r in selected_tasks if r["technical_unknown"]]})
    logs = [read(p) for p in RUN.glob("runs/**/manifest.json") if "model" in read(p)]
    counts = Counter(r["status"] for r in logs)
    final = {"created_at": datetime.now(timezone.utc).isoformat(), "planned": protocol["planned_final_outputs"],
             "completed": len(tasks), "target_count": len(targets),
             "unreviewed_targets": [r["key"] for r in scored if not r["review"]],
             "unreviewed_empty_outputs": [r["key"] for r in tasks if not r["final"].get("targets") and r["key"] not in labels.get("tasks", {})],
             "aggregates": aggregates, "provider_status": dict(counts),
             "physical_calls": sum(r.get("external_model_calls", 0) for r in logs),
             "inherited_physical_calls": sum(r.get("reused_external_model_calls", 0) for r in logs),
             "new_provider_tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in logs if not r.get("reused_from")),
             "inherited_provider_tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in logs if r.get("reused_from")),
             "new_prompt_cache_hit_tokens": sum((r.get("usage") or {}).get("prompt_cache_hit_tokens", 0) for r in logs if not r.get("reused_from")),
             "new_prompt_cache_miss_tokens": sum((r.get("usage") or {}).get("prompt_cache_miss_tokens", 0) for r in logs if not r.get("reused_from")),
             "provider_tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in logs),
             "response_models": sorted({str(r.get("response_model")) for r in logs if r.get("response_model")})}
    write_json(EVAL/"summary.json", final)
    print(json.dumps({k:v for k,v in final.items() if k not in {"aggregates", "unreviewed_targets", "unreviewed_empty_outputs"}}), flush=True)
    return final


def audit():
    check()
    requests, paired = [], []
    for path in sorted(RUN.glob("runs/*/*/*/stage*/*/request.json")):
        cid, arm, repeat, stage = path.relative_to(RUN/"runs").parts[:4]
        payload = read(path)
        body = json.loads(payload["messages"][1]["content"])
        expected = read(RUN/"inputs"/cid/"base.json")
        if arm != "A_final": expected["validation_evolution"] = read(RUN/"inputs"/cid/"evolution.json")
        if arm in {"C_history", "D_probe", "E_observations"}: expected["development_history"] = read(RUN/"inputs"/cid/"history.json")
        requests.append({"request": str(path.relative_to(RUN)), "matches_public_material": body.get("public_evidence") == expected,
                         "only_declared_fields": set(body) <= {"public_evidence", "investigation", "retrieved_evidence", "ranked_hypotheses_and_probes", "diagnostic_observations", "draft", "original_patch_execution"},
                         "history_event_access": arm in {"C_history", "D_probe", "E_observations"}})
    for case in read(RUN/"cases.json"):
        for repeat in REPEATS:
            paths = [RUN/"runs"/case["id"]/arm/f"repeat{repeat}"/"stage3/primary/request.json" for arm in ["C_history", "D_probe"]]
            if not all(p.exists() for p in paths): continue
            p = [read(x) for x in paths]
            bodies = [json.loads(x["messages"][1]["content"]) for x in p]
            for b in bodies: b.pop("diagnostic_observations")
            paired.append({"case": case["id"], "repeat": repeat, "only_observation_differs": bodies[0] == bodies[1] and p[0]["messages"][0] == p[1]["messages"][0]})
    mismatches, source_count = [], 0
    for case in read(RUN/"cases.json"):
        for path, digest in read(RUN/"inputs"/case["id"]/"source_receipts.json").items():
            source_count += 1
            if method.previous.digest(Path(case["repository"])/path) != digest:
                mismatches.append([case["id"], path])
    result = {"requests": requests, "paired_observation_comparisons": paired,
              "original_sources_checked": source_count, "source_mismatches": mismatches}
    write_json(EVAL/"audit.json", result)
    print(json.dumps({"requests": len(requests), "material_mismatches": sum(not r["matches_public_material"] for r in requests),
                      "pairs": len(paired), "pair_mismatches": sum(not r["only_observation_differs"] for r in paired),
                      "original_sources": source_count, "source_mismatches": len(mismatches)}), flush=True)


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("action", choices=["inventory", "sources", "gold", "summary", "audit"])
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    if a.action == "inventory":
        tasks, targets = inventory(); print(json.dumps({"tasks": len(tasks), "targets": len(targets)}))
    elif a.action == "sources": prepare_sources()
    elif a.action == "gold": gold(a.workers)
    elif a.action == "summary": summary()
    elif a.action == "audit": audit()


if __name__ == "__main__":
    main()
