"""Freeze source-only proposals, complete oracle holes, then execute frozen tests.

  python scripts/run_semantic_transport.py prepare --case CASE --source-prepared SOURCE --output NEW
  python scripts/run_semantic_transport.py complete --case CASE --output NEW --rerun-id r1
  python scripts/run_semantic_transport.py complete --case CASE --output NEW --rerun-id r2
  python scripts/run_semantic_transport.py freeze --case CASE --output NEW --rerun-id r1
  python scripts/run_semantic_transport.py run --case CASE --output NEW --rerun-id r1 --program candidate

Only complete may contact the configured provider. Only run executes a subject.
Every output is new; invalid rounds cannot be retried, repaired, or frozen.
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

from experimental.semantic_transport import model, proposals
from scripts import run_generic_experiment as driver

GENERATOR = "semantic_observation_transport"
ROUNDS = ["r1", "r2"]


def write_json(path: Path, value: object) -> None:
    model.write_json(path, value)


def transport_hashes() -> dict:
    paths = [*sorted((ROOT / "experimental/semantic_transport").glob("*.py")),
             ROOT / "experimental/llm_baseline.py",
             ROOT / "experimental/finite_inputs.py", ROOT / "experimental/state_regions.py",
             ROOT / "experimental/observation_projection.py", ROOT / "experimental/local_literal_contexts.py",
             ROOT / "experimental/port_exchange.py",
             Path(__file__).resolve()]
    return {str(path.relative_to(ROOT)): driver.digest(path) for path in paths}


def _checked_file(directory: Path, name: str, expected: str) -> bytes:
    path = directory / name
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Frozen path escapes its preparation directory")
    raw = path.read_bytes()
    if model.digest(raw) != expected:
        raise ValueError("Frozen input changed: " + name)
    return raw


def prepare(args) -> dict:
    source = args.source_prepared.resolve()
    source_manifest_bytes = (source / "prepare.json").read_bytes()
    source_manifest = json.loads(source_manifest_bytes)
    if source_manifest.get("status") != "complete" or source_manifest["case_id"] != args.case:
        raise ValueError("Source preparation is incomplete or belongs to a different case")
    names = ("case.json", "retrieval.json", "corpus.json", "evidence.json")
    payloads = {name: _checked_file(source, name, source_manifest["files_sha256"][name])
                for name in names}
    hashes, own_hashes = driver.algorithm_hashes(), transport_hashes()
    corpus = json.loads(payloads["corpus.json"])
    source_evidence = json.loads(payloads["evidence.json"])
    budget = proposals.Budget(max_candidates=128, shown_candidates=24, top_k=10)
    pending = proposals.generate(corpus, budget, retrieval=json.loads(payloads["retrieval.json"]))
    shown = model.presentation(corpus, source_evidence, pending)
    profile = getattr(args, "completion_profile", "standard")
    if profile != "standard":
        shown["completion_profile"] = profile
    # Use the same canonical JSON round trip as completion and cache replay.
    shown = json.loads(model.encoded(shown))
    model.validate_input(shown, pending)
    request = model.request_payload(shown)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in ("case.json", "retrieval.json", "corpus.json"):
        (output / name).write_bytes(payloads[name])
    (output / "source_evidence.json").write_bytes(payloads["evidence.json"])
    (output / "source_prepare.json").write_bytes(source_manifest_bytes)
    write_json(output / "pending.json", pending)
    write_json(output / "proposals.json", pending["candidates"])
    write_json(output / "id_map.json", model.id_mapping(pending))
    write_json(output / "evidence.json", {"issue": shown.get("issue", ""),
                                          "input_selection": "program_selected_source_contexts"})
    write_json(output / "input.json", shown)
    write_json(output / "request_template.json", request)
    (output / "algorithm_snapshot").mkdir()
    for name in {**hashes, **own_hashes}:
        destination = output / "algorithm_snapshot" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    if driver.algorithm_hashes() != hashes or transport_hashes() != own_hashes:
        raise ValueError("Algorithm changed while preparing transport inputs")
    files = [*names, "source_evidence.json", "source_prepare.json", "pending.json", "proposals.json",
             "id_map.json", "input.json", "request_template.json"]
    manifest = {"version": 1, "case_id": args.case, "status": "complete", "generator": GENERATOR,
                "expected_model": model.MODEL, "created_at": datetime.now(timezone.utc).isoformat(),
                "source_prepared": str(source),
                "source_prepare_sha256": model.digest(source_manifest_bytes),
                "algorithm_sha256": hashes, "transport_algorithm_sha256": own_hashes,
                "files_sha256": {name: driver.digest(output / name) for name in files},
                "declared_completion_rounds": ROUNDS,
                "budget": {"max_candidates": 128, "shown_candidates": 24, "top_k": 10,
                           "max_completions_per_round": model.MAX_COMPLETIONS,
                           "model_calls_per_round": 1, "max_output_tokens_per_round": request["max_tokens"],
                           "max_request_bytes": model.MAX_REQUEST_BYTES,
                           "max_response_bytes": model.MAX_RESPONSE_BYTES},
                "proposal_counts": pending["counts"], "external_model_calls": 0,
                "subject_execution": False, "reference_or_verifier_inputs": False,
                "execution_outcomes": False, "corpus_coverage": corpus.get("coverage", {})}
    if profile != "standard":
        manifest["completion_profile"] = profile
    write_json(output / "transport_prepare.json", manifest)
    return {"stage": "prepare", "case_id": args.case, "output": str(output),
            "counts": pending["counts"], "rounds": ROUNDS}


def checked_inputs(args, *, check_code=True) -> dict:
    output = args.output.resolve()
    manifest = json.loads((output / "transport_prepare.json").read_bytes())
    if (manifest.get("status") != "complete" or manifest["case_id"] != args.case
            or manifest.get("generator") != GENERATOR):
        raise ValueError("Transport preparation is incomplete or belongs to another case")
    if manifest.get("declared_completion_rounds") != ROUNDS or manifest.get("expected_model") != model.MODEL:
        raise ValueError("Prepared rounds or model differ from the fixed protocol")
    for name, expected in manifest["files_sha256"].items():
        _checked_file(output, name, expected)
    for name, expected in {**manifest["algorithm_sha256"], **manifest["transport_algorithm_sha256"]}.items():
        _checked_file(output / "algorithm_snapshot", name, expected)
    if check_code and (manifest["algorithm_sha256"] != driver.algorithm_hashes()
                       or manifest["transport_algorithm_sha256"] != transport_hashes()):
        raise ValueError("Algorithm changed after preparation; use a new output directory")
    if not check_code:
        # Execution consumes already frozen bytes. Recreating an old prompt
        # with a new generator is neither necessary nor a valid integrity test.
        return manifest
    pending = json.loads((output / "pending.json").read_bytes())
    shown = json.loads((output / "input.json").read_bytes())
    model.validate_input(shown, pending)
    request = model.request_payload(shown)
    if (manifest.get("completion_profile", "standard") != shown.get("completion_profile", "standard")
            or manifest["budget"]["max_output_tokens_per_round"] != request["max_tokens"]):
        raise ValueError("Prepared completion profile or token budget differs from the frozen request")
    if (model.encoded(model.id_mapping(pending)) != (output / "id_map.json").read_bytes()
            or model.encoded(pending["candidates"]) != (output / "proposals.json").read_bytes()
            or model.encoded(request) != (output / "request_template.json").read_bytes()):
        raise ValueError("Prepared presentation differs from immutable proposals")
    return manifest


def materialized_generation(corpus: dict, pending: dict, validation: dict) -> dict:
    offered = {row["candidate_id"]: row for row in model.offered_candidates(pending)}
    candidates, unsupported = [], []
    for completion in validation["accepted"]:
        candidate = offered[completion["candidate_id"]]
        try:
            candidates.append(proposals.materialize(corpus, candidate, completion))
        except (ValueError, TypeError, KeyError) as exc:
            unsupported.append({"candidate_id": candidate["candidate_id"],
                                "reason": "completion_materialization_failed", "error_type": type(exc).__name__})
    return {"version": 1, "generator": GENERATOR, "candidates": candidates,
            "validation": validation, "unsupported": unsupported,
            "counts": {"proposed": len(pending["candidates"]), "shown": len(offered),
                       "accepted_completions": len(validation["accepted"]),
                       "rejected_completions": len(validation["rejected"]),
                       "candidates": len(candidates), "unsupported": len(unsupported)}}


def complete(args) -> dict:
    manifest = checked_inputs(args)
    if args.rerun_id not in manifest["declared_completion_rounds"]:
        raise ValueError("Completion round was not declared")
    output = args.output.resolve()
    round_output = output / "rounds" / args.rerun_id
    round_output.mkdir(parents=True, exist_ok=False)
    pending = json.loads((output / "pending.json").read_bytes())
    shown = json.loads((output / "input.json").read_bytes())
    record = {"round": args.rerun_id, "status": "started", "model": model.MODEL,
              "transport_prepare_sha256": driver.digest(output / "transport_prepare.json"),
              "model_request_attempts": int(bool(model.offered_candidates(pending))),
              "execution_outcomes": False, "subject_execution": False}
    marker = round_output / "completion_round.json"
    write_json(marker, record)
    try:
        response = model.request_completion(shown, pending, round_output / "completion")
        checked_inputs(args)
        record.update(status="complete" if response.get("valid") else "invalid", result=response,
                      model_request_attempts=response["model_request_attempts"])
        write_json(marker, record)
        if not response.get("valid"):
            return {"stage": "complete", "case_id": args.case, "round": args.rerun_id,
                    "status": "invalid", "failure_kind": response.get("failure_kind"),
                    "external_model_calls": response["external_model_calls"],
                    "compatible_prepared_output": None}
        _, validation = model.load_completion(round_output / "completion", shown, pending)
        corpus = json.loads((output / "corpus.json").read_bytes())
        generated = materialized_generation(corpus, pending, validation)
        for name in ("case.json", "retrieval.json", "corpus.json", "evidence.json"):
            shutil.copyfile(output / name, round_output / name)
        write_json(round_output / "generated.json", generated)
        write_json(round_output / "candidates.json", generated["candidates"])
        shutil.copytree(output / "algorithm_snapshot", round_output / "algorithm_snapshot")
        files = ["case.json", "retrieval.json", "corpus.json", "evidence.json", "generated.json",
                 "candidates.json", "completion_round.json"]
        files.extend(str(path.relative_to(round_output)) for path in sorted((round_output / "completion").iterdir()))
        compatible = {"case_id": args.case, "status": "complete", "generator": GENERATOR,
                      "completion_round": args.rerun_id, "expected_model": model.MODEL,
                      "declared_admission_rounds": [], "declared_completion_rounds": ROUNDS,
                      "algorithm_sha256": manifest["algorithm_sha256"],
                      "transport_algorithm_sha256": manifest["transport_algorithm_sha256"],
                      "transport_prepare_sha256": record["transport_prepare_sha256"],
                      "source_prepare_sha256": manifest["source_prepare_sha256"],
                      "generation_counts": generated["counts"], "corpus_coverage": manifest["corpus_coverage"],
                      "budget": manifest["budget"], "external_model_calls": response["external_model_calls"],
                      "subject_execution": False, "execution_outcomes": False, "reference_or_verifier_inputs": False,
                      "files_sha256": {name: driver.digest(round_output / name) for name in files}}
        write_json(round_output / "prepare.json", compatible)
    except Exception as exc:
        record.update(status="failed", error_type=type(exc).__name__)
        write_json(marker, record)
        raise
    return {"stage": "complete", "case_id": args.case, "round": args.rerun_id,
            "status": record["status"], "counts": generated["counts"],
            "compatible_prepared_output": str(round_output),
            "external_model_calls": response["external_model_calls"]}


def round_args(args):
    values = dict(vars(args))
    values.update(output=args.output.resolve() / "rounds" / args.rerun_id, direct_baseline=True)
    return SimpleNamespace(**values)


def checked_round(args, *, check_code=True):
    inputs = checked_inputs(args, check_code=check_code)
    if args.rerun_id not in inputs["declared_completion_rounds"]:
        raise ValueError("Completion round was not declared")
    adapted = round_args(args)
    manifest, case = driver.checked_preparation(adapted, check_code=check_code)
    marker = json.loads((adapted.output / "completion_round.json").read_bytes())
    expected = driver.digest(args.output.resolve() / "transport_prepare.json")
    if (manifest["transport_prepare_sha256"] != expected or marker["transport_prepare_sha256"] != expected
            or manifest["completion_round"] != args.rerun_id or marker["round"] != args.rerun_id
            or marker["status"] != "complete"):
        raise ValueError("Round belongs to a different preparation or is incomplete")
    for name, expected_hash in {**manifest["algorithm_sha256"], **manifest["transport_algorithm_sha256"]}.items():
        _checked_file(adapted.output / "algorithm_snapshot", name, expected_hash)
    if not check_code:
        response = json.loads((adapted.output / "completion/manifest.json").read_bytes())
        if not response.get("valid") or model.encoded(response) != model.encoded(marker["result"]):
            raise ValueError("Round receipt differs from its frozen completion cache")
        return inputs, manifest, case
    pending = json.loads((args.output / "pending.json").read_bytes())
    shown = json.loads((args.output / "input.json").read_bytes())
    response, validation = model.load_completion(adapted.output / "completion", shown, pending)
    if model.encoded(response) != model.encoded(marker["result"]):
        raise ValueError("Round receipt differs from the completion cache")
    if check_code:
        corpus = json.loads((adapted.output / "corpus.json").read_bytes())
        generated = materialized_generation(corpus, pending, validation)
        if model.encoded(generated) != (adapted.output / "generated.json").read_bytes():
            raise ValueError("Round candidates differ from immutable oracle completion")
        if model.encoded(generated["candidates"]) != (adapted.output / "candidates.json").read_bytes():
            raise ValueError("Executable candidates differ from accepted completions")
    return inputs, manifest, case


def freeze(args) -> dict:
    from generic_composition.emitter import emit
    from generic_composition.runner import freeze_artifact, infer_harness

    inputs, manifest, case = checked_round(args)
    output = round_args(args).output
    generated = json.loads((output / "generated.json").read_bytes())
    corpus = json.loads((output / "corpus.json").read_bytes())
    response = json.loads((output / "completion/manifest.json").read_bytes())
    emitted = emit(corpus, generated["candidates"])
    files = emitted["files"]
    controls = [dict(row, is_control=True) if isinstance(row, dict) else {"id": row, "is_control": True}
                for row in emitted.get("controls", [])]
    if files:
        if isinstance(case.get("harness"), dict):
            harness = case["harness"]
        else:
            name_filter = {"python": "test_gc_", "go": "^TestGC_", "typescript": "gc_", "javascript": "gc_"}[case["language"]]
            harness = infer_harness(Path(case["repository"]), case["language"], list(files),
                                    python="python" if case.get("image") else sys.executable,
                                    name_filter=name_filter)
        files = {**files, **harness.get("files", {})}
    else:
        harness = {"command": "true", "report_format": "jsonl", "report_path": "stdout.txt"}
    unsupported = [*generated["unsupported"], *emitted.get("unsupported", [])]
    metadata = {"algorithm": GENERATOR, "variant": "direct", "completion_round": args.rerun_id,
                "semantic_completion": True, "semantic_admission": False, "direct_baseline": True,
                "model": model.MODEL, "prepare_sha256": driver.digest(output / "prepare.json"),
                "transport_prepare_sha256": manifest["transport_prepare_sha256"],
                "algorithm_sha256": manifest["algorithm_sha256"],
                "transport_algorithm_sha256": inputs["transport_algorithm_sha256"],
                "completion_request_sha256": response["request_sha256"],
                "completion_response_sha256": response.get("response_sha256"),
                "provider_endpoint_sha256": response.get("provider_endpoint_sha256"),
                "accepted_candidate_ids": sorted(row["id"] for row in generated["candidates"]),
                "candidate_count": len(generated["candidates"]), "unsupported": unsupported,
                "no_executable_tests": not bool(files),
                "oracle_status": "Frozen source-value transformer; independent semantic evaluation required"}
    artifact = output / "frozen/direct"
    result = freeze_artifact(artifact, args.case, files, harness["command"], harness["report_format"],
                             harness["report_path"], repository=Path(case["repository"]),
                             obligations=[*emitted.get("obligations", []), *controls],
                             metadata=metadata, timeout=args.timeout)
    receipt = {"variant": "direct", "completion_round": args.rerun_id,
               "artifact_sha256": driver.digest(artifact / "manifest.json"),
               "accepted": len(generated["candidates"]), "generated": len(emitted.get("obligations", [])),
               "controls": len(controls), "unsupported": unsupported, "files": len(result["files"])}
    write_json(output / "freezes/direct.json", receipt)
    return {"stage": "freeze", "case_id": args.case, **receipt}


def run(args) -> dict:
    checked_round(args, check_code=False)
    return driver.run(round_args(args))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    stages = parser.add_subparsers(dest="stage", required=True)
    for name in ("prepare", "complete", "freeze", "run"):
        sub = stages.add_parser(name)
        sub.add_argument("--case", required=True)
        sub.add_argument("--output", required=True, type=Path)
        if name == "prepare":
            sub.add_argument("--source-prepared", required=True, type=Path)
            sub.add_argument("--completion-profile", choices=model.COMPLETION_PROFILES, default="standard")
        else:
            sub.add_argument("--rerun-id", choices=ROUNDS, required=True)
        if name == "freeze":
            sub.add_argument("--timeout", type=int, default=180)
        if name == "run":
            sub.add_argument("--program", choices=("candidate", "reference"), default="candidate")
            sub.add_argument("--reference-patch", type=Path)
            sub.add_argument("--reference-repository", type=Path)
            sub.add_argument("--execution-output", type=Path)
    args = parser.parse_args()
    print(json.dumps(globals()[args.stage](args), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
