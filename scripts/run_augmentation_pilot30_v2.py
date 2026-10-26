"""Run the frozen v2 pilot on the original 30 public trajectories.

Generation reads public requirements, original patches, repositories and
trajectories only. The separate evaluator may read reference patches later.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
OLD = ROOT / "experiments/relation_distinction/results/pilot30_20261007_v1"
RUN = ROOT / "experiments/relation_distinction/results/pilot30_v2_20261008_v1"
from augmentation.agent import _select, run_agent
from augmentation.pipeline import prepare, write_json
from anchor_retrieval.syntax import Source, units
from combination_testing.runner import freeze_artifact, run_artifact
from generic_composition.runner import infer_harness
from scripts.execute_augmentation_pilot30 import ava_harness, mocha_typescript_harness
from scripts.execute_relational_gap_v7 import python_source_environment


def read(path):
    return json.loads(Path(path).read_text())


def receipt(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def implementation():
    paths = sorted((ROOT / "src/augmentation").glob("*.py"))
    paths += [Path(__file__).resolve(), ROOT / "scripts/execute_augmentation_pilot30.py",
              ROOT / "scripts/execute_relational_gap_v7.py", ROOT / "generic_composition/runner.py",
              ROOT / "combination_testing/runner.py", ROOT / "combination_testing/container_runner.py",
              ROOT / "combination_testing/test_reports.py"]
    return {str(p.relative_to(ROOT)): receipt(p)["sha256"] for p in paths}


def initialize():
    RUN.mkdir(parents=True, exist_ok=False)
    cases = read(OLD / "cases.json")
    assert len(cases) == 30 and len({c["id"] for c in cases}) == 30
    write_json(RUN / "cases.json", cases)
    write_json(RUN / "protocol.json", {
        "version": "pilot30-joint-observation-v2.v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "model": "deepseek-v4-flash", "cases": [c["id"] for c in cases],
        "extraction": {"max_regions": 400, "max_depth": 6, "max_order": 3, "analysis_mode": "joint"},
        "agent": {"max_candidates": 8, "max_rounds": 3, "max_executions": 2,
                  "token_budget": 1000000, "max_output_tokens": 32768, "timeout": 300},
        "selection": "Unchanged augmentation.agent._select: first candidate per relation family, then remaining priority order.",
        "final_claim": "Latest generated proposal for a candidate, unless a later finish withdraws it. Earlier attempts are retained but excluded from final success counts.",
        "evaluation": {
            "correct_detection": "A concrete missing joint condition exposes an original-patch error and is satisfied by gold semantics; code validity is assessed separately.",
            "correct_generation": "A final unedited generated test correctly exercises such a combination and has a requirement-supported assertion that rejects the original patch.",
            "false_positive": "A final gap claim disproved by semantic review: unsupported expected behavior, already tested combination, non-combination issue, or no original-patch defect for the proposed target.",
            "false_negative": "A frozen eligible reference target has no matching correct final claim. Budget and technical failures remain misses, with separate reasons.",
            "units": "Report distinct tasks and distinct reference targets separately. Review unlabelled discoveries separately. Unknown cases are not true negatives.",
            "gold_private_helpers": "Use static semantic review when a generated test depends on original-patch-specific private helpers; do not force it to execute on gold.",
            "resolution_rate": "No repair or full benchmark run in this protocol; do not claim resolution-rate improvement.",
        },
        "reference_inputs_in_generation": False, "implementation_sha256": implementation(),
        "execution": "Fresh original benchmark containers, network disabled, exact generated code, standard framework reports; Python local probes when available.",
        "reference_labels": receipt(OLD / "benchmark_reverse_v4/combined_targets.json"),
        "input_receipts": {c["id"]: [receipt(c[k]) for k in ("candidate_patch", "issue", "trajectory")] for c in cases},
    })


def check_protocol():
    protocol = read(RUN / "protocol.json")
    if implementation() != protocol["implementation_sha256"]:
        raise ValueError("Implementation changed after protocol freeze")
    return protocol


def prepare_case(case, protocol):
    output = RUN / "cases" / case["id"]
    done = output / "extraction.json"
    if done.exists():
        summary = read(done)
        if receipt(output / "prepared.json")["sha256"] != summary["prepared"]["sha256"]:
            raise ValueError("Prepared artifact changed")
        return summary
    output.mkdir(parents=True, exist_ok=True)
    for expected in protocol["input_receipts"][case["id"]]:
        if receipt(expected["path"]) != expected:
            raise ValueError("Public input changed")
    started = time.monotonic()
    prepared = prepare(case["repository"], Path(case["candidate_patch"]).read_text(),
                       Path(case["issue"]).read_text(), read(case["trajectory"]), **protocol["extraction"])
    write_json(output / "prepared.json", prepared)
    selected = _select(prepared, None, protocol["agent"]["max_candidates"])
    summary = {"case": case["id"], "status": "complete", "seconds": time.monotonic() - started,
               "counts": prepared["counts"], "search": prepared["analysis"]["joint_search"],
               "families": dict(Counter(c["family"] for c in prepared["candidates"])),
               "selected": [{"id": c["id"], "family": c["family"], "test_ids": c["test_ids"],
                              "source_paths": c["source_paths"]} for c in selected],
               "prepared": receipt(output / "prepared.json")}
    write_json(done, summary)
    return summary


def runtime_case(case):
    result = dict(case)
    result["base_commit"] = read(OLD / "cases" / case["id"] / "repository_provenance.json")["base_commit"]
    path = OLD / "environment" / case["id"] / "setup.json"
    environment = read(path) if path.exists() else {}
    if environment.get("status") == "ready" and environment.get("derived_image"):
        result["image"] = environment["derived_image"]
    return result, environment


def execute_case(case, prepared, response, output, command, *, timeout=300, run_baseline=False):
    """Adapt the benchmark-native executor to the unchanged bounded agent."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    candidate = next(c for c in prepared["candidates"] if c["id"] == response["candidate_id"])
    key = "augmented" if response["decision"] == "gap" else "execution"
    folder = output / ("augmented" if key == "augmented" else "selection")
    result = {"decision": response["decision"], "candidate_id": response["candidate_id"],
              "interpretation": "Collection, test failure, and semantic defect are separate. No reference patch was executed or read."}
    try:
        repository = Path(case["repository"]).resolve()
        files, names = {}, []
        if response["decision"] == "gap":
            for edit in response["tests"]:
                path = edit["path"]
                original = repository / path
                if not original.resolve().is_relative_to(repository):
                    raise ValueError("test_path_escapes_repository")
                if edit["mode"] == "append":
                    files[path] = original.read_text() + "\n\n" + edit["code"] + "\n"
                else:
                    if original.exists():
                        raise ValueError("new_file_already_exists")
                    files[path] = edit["code"] + "\n"
                names.extend(u.name for u in units(Source(path, edit["code"], case["language"]))[0] if u.test)
        else:
            for tid in response["existing_test_ids"]:
                test = prepared["tests"][tid]
                if test["origin"] != "repository":
                    raise ValueError("historical_test_requires_explicit_replay_materialization")
                path = test["span"]["path"]
                files[path] = (repository / path).read_text()
                names.append(test["name"])
        names = sorted(set(names))
        if not names:
            raise ValueError("no_named_test_found")
        selector = " or ".join(names) if case["language"] == "python" else "(" + "|".join(re.escape(n) for n in names) + ")"
        runtime, environment = runtime_case(case)
        if environment.get("harness") == "mocha_typescript":
            harness = mocha_typescript_harness(list(files), selector, node_test=any("node:test" in code for code in files.values()))
        elif environment.get("harness") == "ava":
            harness = ava_harness(list(files), names)
        else:
            harness = infer_harness(repository, case["language"], list(files), python="python", name_filter=selector)
        test_command = harness["command"]
        if environment.get("build_command"):
            test_command = environment["build_command"] + " && " + test_command
        if case["language"] == "python":
            test_command = python_source_environment(repository)["command"] + test_command
        if case["language"] == "go" and environment.get("go_build_tags"):
            test_command = test_command.replace("go test ", "go test -tags " + shlex.quote(environment["go_build_tags"]) + " ", 1)
        files.update(harness.get("files", {}))
        # Reuse the algorithm's probes, with paths translated into the fresh container.
        setup = {"status": "activation_unavailable", "reason": "Python probes only; other runtimes retain command logs."}
        if case["language"] == "python":
            from augmentation.feedback import probe_environment
            probe_dir = output / "probe-setup"
            probe_dir.mkdir()
            _, setup = probe_environment(candidate, repository, probe_dir)
            if setup["status"] == "configured":
                config = read(probe_dir / "probes/config.json")
                config.update(repository="/app", output="/combination-logs/trace.jsonl")
                files[".augmentation-probes/config.json"] = json.dumps(config)
                files[".augmentation-probes/sitecustomize.py"] = (probe_dir / "probes/sitecustomize.py").read_text()
                test_command = 'export AUGMENTATION_TRACE_CONFIG=/app/.augmentation-probes/config.json\nexport PYTHONPATH=/app/.augmentation-probes:"${PYTHONPATH:-}"\n' + test_command
        artifact = output / "artifact"
        freeze_artifact(artifact, case["id"], files, test_command, harness["report_format"], harness["report_path"],
                        timeout=timeout, metadata={"generated_test_names": names, "candidate_id": response["candidate_id"],
                        "mode": "unmodified_model_test_additions" if key == "augmented" else "existing_test_probe"})
        execution = run_artifact(artifact, "candidate", folder, registry=[runtime])
        from augmentation.feedback import collect_feedback
        # Keep detailed framework results on disk and supply a bounded view to the model.
        result[key] = {"status": execution["status"], "returncode": execution["process"].get("returncode"),
                       "errors": execution.get("errors", []), "tests": execution.get("tests", [])[:30],
                       "test_result_count": len(execution.get("tests", [])),
                       "activation": collect_feedback(candidate, folder, setup)}
        result["artifact"] = str(artifact)
    except Exception as exc:
        result[key] = {"status": "execution_setup_error", "returncode": None,
                       "error_type": type(exc).__name__, "error": str(exc)}
    write_json(output / "result.json", result)
    return result


def generate_case(case, protocol):
    directory = RUN / "cases" / case["id"]
    done = directory / "generation.json"
    if done.exists():
        return read(done)
    prepared = read(directory / "prepared.json")
    for path, expected in prepared["source_receipts"].items():
        if receipt(Path(case["repository"]) / path)["sha256"] != expected:
            raise ValueError("Prepared source changed: " + path)
    started = time.monotonic()
    result = run_agent(prepared, directory / "agent", provider_root=ROOT,
                       command=["benchmark-native-frozen-harness"],
                       executor=lambda *a, **kw: execute_case(case, *a, **kw), **protocol["agent"])
    summary = {"case": case["id"], "status": "complete", "seconds": time.monotonic() - started,
               "model_calls": result["external_model_calls"], "charged_tokens": result["charged_tokens"],
               "proposals": result["generated_proposals"], "statuses": dict(Counter(r["status"] for r in result["results"])),
               "results": receipt(directory / "agent/results.json")}
    write_json(done, summary)
    return summary


def child(case, stage):
    log = RUN / "logs" / (case["id"] + "-" + stage + ".txt")
    log.parent.mkdir(exist_ok=True)
    with log.open("a") as stream:
        p = subprocess.run([sys.executable, str(Path(__file__).resolve()), stage, "--case", case["id"]],
                           stdout=stream, stderr=subprocess.STDOUT)
    event = {"case": case["id"], "stage": stage, "returncode": p.returncode}
    print(json.dumps(event), flush=True)
    return p.returncode


def campaign(cases):
    outcomes = []
    with ThreadPoolExecutor(max_workers=6) as extraction, ThreadPoolExecutor(max_workers=8) as generation:
        preparing = {extraction.submit(child, case, "prepare"): case for case in cases}
        generating = {}
        for future in as_completed(preparing):
            case = preparing[future]
            code = future.result()
            if code == 0:
                generating[generation.submit(child, case, "generate")] = case
            else:
                outcomes.append({"case": case["id"], "stage": "prepare", "returncode": code})
        for future in as_completed(generating):
            outcomes.append({"case": generating[future]["id"], "stage": "generate", "returncode": future.result()})
            write_json(RUN / "campaign.json", {"status": "running", "outcomes": outcomes})
    write_json(RUN / "campaign.json", {"status": "complete", "outcomes": sorted(outcomes, key=lambda c: c["case"])})


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("stage", choices=("init", "prepare", "generate", "campaign"))
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    if args.stage == "init":
        initialize()
        return
    protocol = check_protocol()
    cases = [c for c in read(RUN / "cases.json") if not args.case or c["id"] in args.case]
    if args.stage == "campaign":
        campaign(cases)
    else:
        for case in cases:
            started = time.monotonic()
            try:
                result = prepare_case(case, protocol) if args.stage == "prepare" else generate_case(case, protocol)
                print(json.dumps({k: v for k, v in result.items() if k not in {"selected", "search", "families"}}), flush=True)
            except Exception as exc:
                write_json(RUN / "cases" / case["id"] / (args.stage + "-failure.json"),
                           {"error_type": type(exc).__name__, "error": str(exc), "seconds": time.monotonic() - started})
                traceback.print_exc()
                raise


if __name__ == "__main__":
    main()
