"""Independent LLM generation from frozen retrieval inputs, without feedback.

  python scripts/run_llm_generation_baseline.py prepare --case CASE --source-prepared SOURCE --output BASE
  python scripts/run_llm_generation_baseline.py generate --case CASE --output BASE --rerun-id r1
  python scripts/run_llm_generation_baseline.py generate --case CASE --output BASE --rerun-id r2
  python scripts/run_llm_generation_baseline.py freeze --case CASE --output BASE --rerun-id r1
  python scripts/run_llm_generation_baseline.py run --case CASE --output BASE --rerun-id r1

Only generate contacts the model; only run executes subjects. The two round
directories also support the existing generic CLI's direct-baseline freeze/run.
Use this CLI's freeze to label frozen metadata explicitly as the LLM baseline.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experimental import llm_baseline as baseline
from scripts import run_generic_experiment as driver


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(baseline.encoded(value))


def baseline_hashes() -> dict:
    paths = [ROOT / "experimental/llm_baseline.py", Path(__file__).resolve()]
    return {str(path.relative_to(ROOT)): driver.digest(path) for path in paths}


def prepare(args) -> dict:
    source = args.source_prepared.resolve()
    source_manifest = json.loads((source / "prepare.json").read_bytes())
    if source_manifest.get("status") != "complete" or source_manifest["case_id"] != args.case:
        raise ValueError("Source preparation is incomplete or belongs to a different case")
    names = ("case.json", "retrieval.json", "corpus.json", "evidence.json")
    payloads = {}
    for name in names:
        payloads[name] = (source / name).read_bytes()
        if baseline.digest(payloads[name]) != source_manifest["files_sha256"][name]:
            raise ValueError("Frozen source input changed: " + name)
    corpus, evidence = (json.loads(payloads[name]) for name in ("corpus.json", "evidence.json"))
    selected = baseline.retrieval_evidence(corpus, evidence)
    shown = baseline.presentation(corpus, selected)
    payload = baseline.request_payload(shown)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in ("case.json", "retrieval.json", "corpus.json"):
        (output / name).write_bytes(payloads[name])
    (output / "source_evidence.json").write_bytes(payloads["evidence.json"])
    (output / "source_prepare.json").write_bytes((source / "prepare.json").read_bytes())
    write_json(output / "evidence.json", selected)
    write_json(output / "input.json", shown)
    write_json(output / "request_template.json", payload)
    hashes = driver.algorithm_hashes()
    own_hashes = baseline_hashes()
    for name in {**hashes, **own_hashes}:
        destination = output / "algorithm_snapshot" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    if driver.algorithm_hashes() != hashes or baseline_hashes() != own_hashes:
        raise ValueError("Algorithm changed while preparing baseline inputs")
    files = [*names, "source_evidence.json", "source_prepare.json", "input.json", "request_template.json"]
    manifest = {"version": 1, "case_id": args.case, "status": "complete",
                "generator": "independent_llm_baseline", "expected_model": baseline.MODEL,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_prepared": str(source), "source_prepare_sha256": driver.digest(source / "prepare.json"),
                "algorithm_sha256": hashes, "baseline_algorithm_sha256": own_hashes,
                "files_sha256": {name: driver.digest(output / name) for name in files},
                "declared_generation_rounds": ["r1", "r2"],
                "input_selection": "All frozen corpus parent tests with integer retrieval_rank in 1..10, ordered by (rank, id); independent of constructed candidates",
                "comparison_scope": "Same frozen retrieval entrance, issue and production context; visible parent tests can differ from the gate's candidate-dependent source subset",
                "allowed_parent_ids": list(selected["source_tests"]),
                "budget": {"max_tests_per_round": baseline.MAX_TESTS, "model_calls_per_round": 1,
                           "max_output_tokens_per_round": baseline.MAX_TOKENS,
                           "max_body_bytes": baseline.MAX_BODY_BYTES,
                           "max_request_bytes": baseline.MAX_REQUEST_BYTES,
                           "max_response_bytes": baseline.MAX_RESPONSE_BYTES},
                "external_model_calls": 0, "subject_execution": False,
                "reference_or_verifier_inputs": False, "execution_outcomes": False,
                "corpus_coverage": corpus.get("coverage", {})}
    write_json(output / "baseline_prepare.json", manifest)
    return {"stage": "prepare", "case_id": args.case, "output": str(output),
            "source_parent_count": len(shown["source_tests"]), "rounds": ["r1", "r2"]}


def checked_inputs(args, *, check_code=True):
    output = args.output.resolve()
    manifest = json.loads((output / "baseline_prepare.json").read_bytes())
    if manifest.get("status") != "complete" or manifest["case_id"] != args.case:
        raise ValueError("Baseline input preparation is incomplete or belongs to another case")
    for name, expected in manifest["files_sha256"].items():
        if driver.digest(output / name) != expected:
            raise ValueError("Frozen baseline input changed: " + name)
    if check_code and (manifest["algorithm_sha256"] != driver.algorithm_hashes()
                       or manifest["baseline_algorithm_sha256"] != baseline_hashes()):
        raise ValueError("Algorithm changed after preparation")
    return manifest


def generate(args) -> dict:
    manifest = checked_inputs(args)
    if args.rerun_id not in manifest["declared_generation_rounds"]:
        raise ValueError("Generation round was not declared")
    output = args.output.resolve()
    round_output = output / "rounds" / args.rerun_id
    round_output.mkdir(parents=True, exist_ok=False)
    record = {"round": args.rerun_id, "status": "started", "model": baseline.MODEL,
              "baseline_prepare_sha256": driver.digest(output / "baseline_prepare.json"),
              "model_request_attempts": 1, "execution_outcomes": False}
    marker = round_output / "generation_round.json"
    write_json(marker, record)
    shown = json.loads((output / "input.json").read_bytes())
    corpus = json.loads((output / "corpus.json").read_bytes())
    try:
        response = baseline.request_generation(shown, corpus, round_output / "generation")
        checked_inputs(args)
        if response.get("valid"):
            _, generated = baseline.load_generation(round_output / "generation", shown, corpus)
        else:
            generated = {"version": 1, "generator": "independent_llm_baseline", "candidates": [],
                         "validation": [], "unsupported": [], "request_invalid": True,
                         "failure_kind": response.get("failure_kind"),
                         "counts": {"proposed": None, "candidates": 0, "unsupported": 0}}
        record.update(status="complete" if response.get("valid") else "invalid", result=response)
        write_json(marker, record)
        for name in ("case.json", "retrieval.json", "corpus.json", "evidence.json"):
            shutil.copyfile(output / name, round_output / name)
        write_json(round_output / "generated.json", generated)
        write_json(round_output / "candidates.json", generated["candidates"])
        shutil.copytree(output / "algorithm_snapshot", round_output / "algorithm_snapshot")
        files = ["case.json", "retrieval.json", "corpus.json", "evidence.json", "generated.json", "candidates.json",
                 "generation_round.json"]
        files.extend(str(path.relative_to(round_output)) for path in sorted((round_output / "generation").iterdir()))
        compatible = {"case_id": args.case, "status": "complete", "generator": "independent_llm_baseline",
                      "generation_round": args.rerun_id, "expected_model": baseline.MODEL,
                      "declared_admission_rounds": [], "declared_generation_rounds": ["r1", "r2"],
                      "algorithm_sha256": manifest["algorithm_sha256"],
                      "baseline_algorithm_sha256": manifest["baseline_algorithm_sha256"],
                      "baseline_prepare_sha256": record["baseline_prepare_sha256"],
                      "source_prepare_sha256": manifest["source_prepare_sha256"],
                      "generation_counts": generated["counts"], "corpus_coverage": manifest["corpus_coverage"],
                      "budget": manifest["budget"], "external_model_calls": response["external_model_calls"],
                      "subject_execution": False, "execution_outcomes": False, "reference_or_verifier_inputs": False,
                      "files_sha256": {name: driver.digest(round_output / name) for name in files}}
        write_json(round_output / "prepare.json", compatible)
    except Exception as error:
        record.update(status="failed", error_type=type(error).__name__)
        write_json(marker, record)
        raise
    return {"stage": "generate", "case_id": args.case, "round": args.rerun_id, "status": record["status"],
            "counts": generated["counts"], "compatible_prepared_output": str(round_output),
            "external_model_calls": response["external_model_calls"]}


def round_args(args):
    values = dict(vars(args))
    values.update(output=args.output.resolve() / "rounds" / args.rerun_id, direct_baseline=True)
    return SimpleNamespace(**values)


def checked_round(args, *, check_code=True):
    inputs = checked_inputs(args, check_code=check_code)
    adapted = round_args(args)
    manifest, case = driver.checked_preparation(adapted, check_code=check_code)
    marker = json.loads((adapted.output / "generation_round.json").read_bytes())
    expected = driver.digest(args.output.resolve() / "baseline_prepare.json")
    if (manifest["baseline_prepare_sha256"] != expected or marker["baseline_prepare_sha256"] != expected
            or manifest["generation_round"] != args.rerun_id or marker["round"] != args.rerun_id):
        raise ValueError("Round belongs to different baseline preparation or declared round")
    return inputs, manifest, case


def freeze(args) -> dict:
    from generic_composition.emitter import emit
    from generic_composition.runner import freeze_artifact, infer_harness

    inputs, manifest, case = checked_round(args)
    adapted = round_args(args)
    output = adapted.output
    generated = json.loads((output / "generated.json").read_bytes())
    corpus = json.loads((output / "corpus.json").read_bytes())
    response = json.loads((output / "generation/manifest.json").read_bytes())
    if response.get("valid"):
        _, checked = baseline.load_generation(output / "generation",
                                              json.loads((args.output.resolve() / "input.json").read_bytes()), corpus)
        if checked != generated:
            raise ValueError("Round candidates differ from immutable model output")
    candidates = generated["candidates"]
    emitted = emit(corpus, candidates)
    files = emitted["files"]
    controls = emitted["controls"]
    if files:
        if isinstance(case.get("harness"), dict):
            harness = case["harness"]
        else:
            name_filter = {"python": "test_gc_", "go": "^TestGC_", "typescript": "gc_"}[case["language"]]
            harness = infer_harness(Path(case["repository"]), case["language"], list(files),
                                    python="python" if case.get("image") else sys.executable, name_filter=name_filter)
        files = {**files, **harness.get("files", {})}
    else:
        harness = {"command": "true", "report_format": "jsonl", "report_path": "stdout.txt"}
    unsupported = [*generated.get("unsupported", []), *emitted["unsupported"]]
    metadata = {"algorithm": "independent_llm_generation_baseline", "variant": "direct",
                "generation_round": args.rerun_id, "semantic_admission": False, "direct_baseline": True,
                "model": baseline.MODEL, "prepare_sha256": driver.digest(output / "prepare.json"),
                "baseline_prepare_sha256": manifest["baseline_prepare_sha256"],
                "algorithm_sha256": manifest["algorithm_sha256"],
                "baseline_algorithm_sha256": inputs["baseline_algorithm_sha256"],
                "generation_request_sha256": response["request_sha256"],
                "generation_response_sha256": response.get("response_sha256"),
                "generation_valid": response.get("valid"), "provider_endpoint_sha256": response.get("provider_endpoint_sha256"),
                "accepted_candidate_ids": sorted(row["id"] for row in candidates),
                "candidate_count": len(candidates), "unsupported": unsupported, "no_executable_tests": not bool(files),
                "oracle_status": "Unmodified model-generated expectations; independent audit required"}
    artifact = output / "frozen/direct"
    result = freeze_artifact(artifact, args.case, files, harness["command"], harness["report_format"],
                             harness["report_path"], repository=Path(case["repository"]),
                             obligations=[*emitted["obligations"], *controls], metadata=metadata, timeout=args.timeout)
    receipt = {"variant": "direct", "generation_round": args.rerun_id,
               "artifact_sha256": driver.digest(artifact / "manifest.json"),
               "accepted": len(candidates), "generated": len(emitted["obligations"]),
               "controls": len(controls), "unsupported": unsupported, "files": len(result["files"])}
    write_json(output / "freezes/direct.json", receipt)
    return {"stage": "freeze", "case_id": args.case, **receipt}


def run(args) -> dict:
    checked_round(args, check_code=False)
    return driver.run(round_args(args))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    stages = parser.add_subparsers(dest="stage", required=True)
    for name in ("prepare", "generate", "freeze", "run"):
        sub = stages.add_parser(name)
        sub.add_argument("--case", required=True)
        sub.add_argument("--output", required=True, type=Path)
        if name == "prepare":
            sub.add_argument("--source-prepared", required=True, type=Path)
        else:
            sub.add_argument("--rerun-id", choices=("r1", "r2"), required=True)
        if name == "freeze":
            sub.add_argument("--timeout", type=int, default=180)
        if name == "run":
            sub.add_argument("--program", choices=("candidate", "reference", "base", "pair"), default="candidate")
            sub.add_argument("--reference-patch", type=Path)
            sub.add_argument("--reference-repository", type=Path)
            sub.add_argument("--execution-output", type=Path)
    args = parser.parse_args()
    print(json.dumps(globals()[args.stage](args), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
