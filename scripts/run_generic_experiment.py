"""Stage a generic composition experiment without outcome-driven regeneration.

Example (each output directory belongs to exactly one case):
  .venv/bin/python scripts/run_generic_experiment.py prepare --registry holdout --case TASK --output results/run/TASK
  .venv/bin/python scripts/run_generic_experiment.py admit --case TASK --output results/run/TASK --rerun-id r1
  .venv/bin/python scripts/run_generic_experiment.py freeze --case TASK --output results/run/TASK --rerun-id r1
  .venv/bin/python scripts/run_generic_experiment.py run --case TASK --output results/run/TASK --rerun-id r1

Only admit contacts the configured model; only run executes frozen subject tests.
Two admission rounds (r1/r2) are declared in advance and never selected by score.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def algorithm_files() -> list[Path]:
    return sorted([*ROOT.glob("generic_composition/*.py"), *ROOT.glob("anchor_retrieval/*.py"),
                   *ROOT.glob("experimental/generic_v2/*.py"),
                   ROOT / "combination_testing/runner.py", ROOT / "combination_testing/container_runner.py",
                   ROOT / "combination_testing/test_reports.py", Path(__file__).resolve()])


def algorithm_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): digest(path) for path in algorithm_files()}


def production_context(repository: Path, language: str, patch: str) -> dict:
    """Bounded, mechanically selected source context; never an executable oracle."""
    from anchor_retrieval.syntax import Source, diff_lines, is_test_path, units
    repository = Path(repository).resolve()
    suffixes = {"python": {".py"}, "go": {".go"}, "typescript": {".ts", ".tsx"},
                "javascript": {".js", ".jsx", ".mjs"}}[language]
    changed = diff_lines(patch)
    candidates = sorted(path for path in changed if Path(path).suffix in suffixes and not is_test_path(path))
    selection = "patch_touched_non_test_source"
    if not patch.strip():
        candidates = sorted(path.name for path in repository.iterdir()
                            if path.is_file() and path.suffix in suffixes and not is_test_path(path.name))
        selection = "root_level_non_test_source_fallback"
    result = {"interpretation": "Candidate implementations may be buggy. Their bodies or current outputs are not independent specifications or oracle proofs. Docstrings and README provide fallible contract evidence.",
              "selection": selection, "files": [], "omitted": [], "max_files": 8,
              "max_bytes_per_file": 12000, "max_source_bytes": 64000}
    remaining = 64000
    for name in candidates:
        path = repository / name
        if not path.resolve().is_relative_to(repository) or not path.is_file():
            result["omitted"].append({"path": name, "reason": "unavailable_or_outside_repository"})
            continue
        if len(result["files"]) >= 8 or remaining <= 0:
            result["omitted"].append({"path": name, "reason": "source_context_budget"})
            continue
        payload = path.read_bytes()
        try:
            text = payload.decode()
        except UnicodeError:
            result["omitted"].append({"path": name, "reason": "non_utf8_source"})
            continue
        limit = min(12000, remaining)
        record = {"path": name, "sha256": hashlib.sha256(payload).hexdigest(),
                  "original_bytes": len(payload), "snippets": []}
        if len(payload) <= limit:
            record["snippets"] = [{"start_line": 1, "code": text, "truncated": False}]
            record["mode"] = "complete_file"
        else:
            source = Source(name, text, language)
            functions, _ = units(source)
            selected = {}
            for line in sorted(changed.get(name, [])):
                containing = [unit for unit in functions if unit.node.start_point.row + 1 <= line <= unit.node.end_point.row + 1]
                if containing:
                    unit = min(containing, key=lambda item: item.node.end_byte - item.node.start_byte)
                    selected[unit.id] = unit
            space = limit
            for unit in sorted(selected.values(), key=lambda item: item.node.start_byte):
                if space <= 0:
                    break
                data = source.data[unit.node.start_byte:unit.node.end_byte]
                excerpt = data[:space].decode(errors="ignore")
                record["snippets"].append({"start_line": unit.node.start_point.row + 1, "code": excerpt,
                                            "truncated": len(data) > space})
                space -= len(excerpt.encode())
            if record["snippets"]:
                record["mode"] = "changed_enclosing_functions"
                record["omitted_enclosing_functions"] = max(0, len(selected) - len(record["snippets"]))
            else:
                record["mode"] = "file_head_truncated_no_enclosing_function"
                record["snippets"] = [{"start_line": 1, "code": payload[:limit].decode(errors="ignore"), "truncated": True}]
        record["included_bytes"] = sum(len(row["code"].encode()) for row in record["snippets"])
        remaining -= record["included_bytes"]
        result["files"].append(record)
    result["included_source_bytes"] = 64000 - remaining
    for name in ("README.md", "README.rst", "README.txt", "README"):
        path = repository / name
        if path.is_file() and path.resolve().is_relative_to(repository):
            payload = path.read_bytes()
            result["root_readme"] = {"path": name, "sha256": hashlib.sha256(payload).hexdigest(),
                                     "text": payload[:8000].decode(errors="ignore"), "truncated": len(payload) > 8000}
            break
    return result


def resolve_case(registry: str, case_id: str, case_root: Path | None = None) -> tuple[dict, Path]:
    aliases = {"pilot": ROOT / "data/cases.json", "holdout": ROOT / "data/generic_holdout_v1/registry.json",
               "controls": ROOT / "data/generic_controls_v1/manifest.json"}
    registry_path = aliases.get(registry, Path(registry)).resolve()
    content = json.loads(registry_path.read_text())
    rows = content.get("cases", []) if isinstance(content, dict) else content
    row = dict(next(row for row in rows if row["id"] == case_id))
    default_root = ROOT / "data/cases" if registry == "pilot" else registry_path.parent
    base = (case_root or default_root).resolve() / case_id

    def path_value(key: str, default: Path) -> str:
        path = Path(row[key]) if row.get(key) else default
        if not path.is_absolute():
            path = (case_root or registry_path.parent) / path
        return str(path.resolve())

    case = {"id": case_id, "language": row["language"], "task": row.get("task", case_id),
            "repository": path_value("repository", base / "repository"),
            "candidate_patch": path_value("candidate_patch", base / "model.patch"),
            "trajectory": path_value("trajectory", base / "trajectory.json"),
            "issue": path_value("issue", base / "issue.md")}
    for key in ("image", "base_commit", "base_commit_hash", "harness", "seed_command", "base_repository"):
        if key in row:
            case[key] = row[key]
    if not Path(case["repository"]).is_dir():
        raise FileNotFoundError(case["repository"])
    return case, registry_path


def checked_preparation(args, *, check_code: bool = True) -> tuple[dict, dict]:
    output = args.output.resolve()
    manifest = json.loads((output / "prepare.json").read_text())
    if manifest["case_id"] != args.case:
        raise ValueError("Output directory belongs to a different case")
    if manifest.get("status") != "complete":
        raise ValueError("Preparation did not finish")
    for name, expected in manifest["files_sha256"].items():
        if digest(output / name) != expected:
            raise ValueError(f"Prepared artifact changed: {name}")
    if check_code and algorithm_hashes() != manifest["algorithm_sha256"]:
        raise ValueError("Algorithm changed after preparation; use a new version/output directory")
    return manifest, json.loads((output / "case.json").read_text())


def prepare(args) -> dict:
    from anchor_retrieval.retrieve import retrieve
    from generic_composition.corpus import build_corpus
    generator = getattr(args, 'generator', 'context')
    if generator == 'analogy':
        from experimental.generic_v2.generate import Budget, gate_evidence, generate
    elif generator == 'context':
        from generic_composition.engine import Budget, gate_evidence, generate
    else:
        raise ValueError('Unknown generator')

    if not 1 <= args.max_candidates <= 128:
        raise ValueError("The preregistered candidate budget is 1..128")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    case, registry = resolve_case(args.registry, args.case, args.case_root)
    hashes = algorithm_hashes()
    for name in hashes:
        destination = output / "algorithm_snapshot" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    write_json(output / "case.json", case)
    manifest = {"case_id": args.case, "status": "preparing", "algorithm_sha256": hashes,
                "generator": generator,
                "registry_path": str(registry), "registry_sha256": digest(registry),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "declared_admission_rounds": ["r1", "r2"],
                "expected_model": args.model,
                "budget": {"max_candidates": args.max_candidates, "model_calls_per_round": 1,
                           "max_output_tokens_per_round": 10000, "top_k": args.top_k},
                "external_model_calls": 0, "subject_execution": False,
                "reference_or_verifier_inputs": False, "execution_outcomes": False}
    manifest["dependencies"] = {name: importlib.metadata.version(name) for name in
                                ("tree-sitter", "tree-sitter-python", "tree-sitter-go", "tree-sitter-typescript", "httpx")}
    write_json(output / "prepare.json", manifest)
    started = time.monotonic()
    try:
        patch = Path(case["candidate_patch"])
        if not patch.exists():
            if case.get("image"):
                raise FileNotFoundError(patch)
            patch = output / "empty.patch"
            patch.write_text("")
        trajectory = Path(case["trajectory"])
        trajectory = trajectory if trajectory.is_file() else None
        if args.retrieval:
            retrieval = json.loads(args.retrieval.read_text())
            manifest["retrieval_source"] = {"mode": "explicit_frozen_input", "path": str(args.retrieval.resolve()), "sha256": digest(args.retrieval)}
        else:
            retrieval = retrieve(Path(case["repository"]), patch, case["language"], trajectory)
            manifest["retrieval_source"] = {"mode": "automatic_observation_frontier"}
        write_json(output / "retrieval.json", retrieval)
        corpus = build_corpus(case["repository"], case["language"], retrieval,
                              max_files=args.max_files, top_k=args.top_k)
        generated = generate(corpus, Budget(max_candidates=args.max_candidates, top_k=args.top_k))
        issue_path = Path(case["issue"])
        issue = issue_path.read_text() if issue_path.is_file() else ""
        evidence, candidates = gate_evidence(corpus, generated, issue)
        evidence["production_context"] = production_context(Path(case["repository"]), case["language"], patch.read_text())
        for name, value in (("corpus.json", corpus), ("generated.json", generated),
                            ("evidence.json", evidence), ("candidates.json", candidates)):
            write_json(output / name, value)
        if algorithm_hashes() != hashes:
            raise ValueError("Algorithm changed while preparing")
        manifest.update(status="complete", seconds=time.monotonic() - started,
                        generation_counts=generated.get("counts", {}), corpus_coverage=corpus.get("coverage", {}),
                        input_hashes={"candidate_patch": digest(patch),
                                      "trajectory": digest(trajectory) if trajectory else None,
                                      "issue": digest(issue_path) if issue_path.is_file() else None},
                        files_sha256={name: digest(output / name) for name in
                                      ("case.json", "retrieval.json", "corpus.json", "generated.json", "evidence.json", "candidates.json")})
    except Exception as error:
        manifest.update(status="failed", error_type=type(error).__name__, error=str(error), seconds=time.monotonic() - started)
        write_json(output / "prepare.json", manifest)
        raise
    write_json(output / "prepare.json", manifest)
    return {"stage": "prepare", "case_id": args.case, "counts": manifest["generation_counts"], "output": str(output)}


def admit(args) -> dict:
    from generic_composition.gate import request_admission
    manifest, _ = checked_preparation(args)
    if args.rerun_id not in manifest["declared_admission_rounds"]:
        raise ValueError("Admission round was not preregistered")
    if args.model != manifest["expected_model"]:
        raise ValueError("Admission model differs from the frozen preparation")
    if args.max_tokens != manifest["budget"]["max_output_tokens_per_round"]:
        raise ValueError("Admission token budget differs from the frozen preparation")
    output = args.output.resolve()
    cache = args.cache_output.resolve() if args.cache_output else output / "admission" / args.rerun_id
    marker = output / "admission" / f"{args.rerun_id}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if marker.exists() or cache.exists():
        raise FileExistsError("Admission round/cache already exists; no overwrite or automatic retry")
    candidates = json.loads((output / "candidates.json").read_text())
    record = {"round": args.rerun_id, "cache": str(cache), "status": "started",
              "prepare_sha256": digest(output / "prepare.json"),
              "algorithm_sha256": manifest["algorithm_sha256"],
              "max_output_tokens": args.max_tokens, "model": args.model,
              "model_request_attempts": int(bool(candidates))}
    write_json(marker, record)
    if not candidates:
        record.update(status="no_candidates", external_model_calls=0, accepted=[])
    else:
        try:
            response = request_admission(json.loads((output / "evidence.json").read_text()),
                                         candidates, cache, model=args.model, max_tokens=args.max_tokens)
            record.update(status="complete" if response.get("valid") else "invalid", result=response)
        except Exception as error:
            record.update(status="failed", error_type=type(error).__name__)
            write_json(marker, record)
            raise
    write_json(marker, record)
    return {"stage": "admit", "case_id": args.case, "round": args.rerun_id, "status": record["status"],
            "accepted": len(record.get("result", {}).get("accepted", [])), "cache": str(cache)}


def freeze(args) -> dict:
    from generic_composition.emitter import emit
    from generic_composition.gate import load_admission
    from generic_composition.runner import freeze_artifact, infer_harness

    manifest, case = checked_preparation(args)
    output = args.output.resolve()
    candidates = json.loads((output / "candidates.json").read_text())
    variant = "direct" if args.direct_baseline else args.rerun_id
    admission = None
    if args.direct_baseline:
        accepted = {row["id"] for row in candidates}
    else:
        if args.rerun_id not in manifest["declared_admission_rounds"]:
            raise ValueError("Admission round was not preregistered")
        marker = json.loads((output / "admission" / f"{args.rerun_id}.json").read_text())
        if marker["prepare_sha256"] != digest(output / "prepare.json"):
            raise ValueError("Admission was prepared with different inputs")
        if marker["status"] == "no_candidates" and not candidates:
            accepted = set()
        else:
            admission = load_admission(Path(marker["cache"]), candidates)
            if admission["model"] != manifest["expected_model"]:
                raise ValueError("Cached admission uses a different model")
            accepted = set(admission["accepted"])
    selected = [row for row in candidates if row["id"] in accepted]
    corpus = json.loads((output / "corpus.json").read_text())
    emitted = emit(corpus, selected)
    files = emitted["files"]
    controls = [dict(row, is_control=True) if isinstance(row, dict) else {"id": row, "is_control": True}
                for row in emitted.get("controls", [])]
    obligations = [*emitted.get("obligations", []), *controls]
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
    artifact = output / "frozen" / variant
    metadata = {"algorithm": "generic_context_composition", "variant": variant,
                "semantic_admission": not args.direct_baseline, "direct_baseline": args.direct_baseline,
                "prepare_sha256": digest(output / "prepare.json"), "algorithm_sha256": manifest["algorithm_sha256"],
                "accepted_candidate_ids": sorted(accepted), "candidate_count": len(candidates),
                "unsupported": emitted.get("unsupported", []), "no_executable_tests": not bool(files)}
    if admission:
        metadata["admission_request_sha256"] = admission["request_sha256"]
        metadata["admission_response_sha256"] = admission["response_sha256"]
    result = freeze_artifact(artifact, args.case, files, harness["command"], harness["report_format"],
                             harness["report_path"], repository=Path(case["repository"]),
                             obligations=obligations, metadata=metadata, timeout=args.timeout)
    receipt = {"variant": variant, "artifact_sha256": digest(artifact / "manifest.json"),
               "accepted": len(accepted), "generated": len(emitted.get("obligations", [])),
               "controls": len(controls), "unsupported": emitted.get("unsupported", []),
               "files": len(result["files"])}
    write_json(output / "freezes" / f"{variant}.json", receipt)
    return {"stage": "freeze", "case_id": args.case, **receipt}


def run(args) -> dict:
    from combination_testing.runner import load_artifact
    from generic_composition.runner import run_artifact, run_pair
    _, case = checked_preparation(args, check_code=False)
    output = args.output.resolve()
    variant = "direct" if args.direct_baseline else args.rerun_id
    artifact = output / "frozen" / variant
    receipt = json.loads((output / "freezes" / f"{variant}.json").read_text())
    if digest(artifact / "manifest.json") != receipt["artifact_sha256"]:
        raise ValueError("Frozen manifest changed")
    manifest = load_artifact(artifact)
    destination = args.execution_output.resolve() if args.execution_output else output / "execution" / variant
    if manifest["metadata"].get("no_executable_tests"):
        destination.mkdir(parents=True, exist_ok=False)
        result = {"case_id": args.case, "status": "not_executed", "reason": "no_frozen_tests", "tests": []}
        write_json(destination / "not_executed.json", result)
        return result
    kwargs = {"registry": [case], "reference_patch": args.reference_patch,
              "reference_repository": args.reference_repository}
    if args.program == "pair":
        result = run_pair(artifact, destination, **kwargs)
    else:
        result = run_artifact(artifact, args.program, destination / args.program, **kwargs)
    return {"stage": "run", "case_id": args.case, "variant": variant,
            "execution": str(destination), "status": result.get("status"), "counts": result.get("counts", {})}


def summarize(args) -> dict:
    manifest, _ = checked_preparation(args, check_code=False)
    output = args.output.resolve()
    admissions = []
    for path in sorted((output / "admission").glob("*.json")):
        row = json.loads(path.read_text())
        gate_manifest = Path(row["cache"]) / "manifest.json"
        result = json.loads(gate_manifest.read_text()) if gate_manifest.exists() else row.get("result", {})
        calls = result.get("external_model_calls", row.get("external_model_calls"))
        admissions.append({"round": row["round"], "status": row["status"], "model": row["model"],
                           "accepted": len(result.get("accepted", [])), "usage": result.get("usage"),
                           "external_model_calls": calls, "model_request_attempts": row.get("model_request_attempts", 0),
                           "seconds": result.get("seconds"), "transport_error": result.get("transport_error"),
                           "validation_error": result.get("validation_error"), "cost_usd": None})
    variants = []
    for path in sorted((output / "freezes").glob("*.json")):
        row = json.loads(path.read_text())
        execution = output / "execution" / row["variant"]
        evaluation = execution / "evaluation.json"
        row["evaluation"] = json.loads(evaluation.read_text()) if evaluation.exists() else None
        if row["evaluation"] is None and all((execution / program / "result.json").exists() for program in ("candidate", "reference")):
            from combination_testing.evaluate import evaluate_case
            row["evaluation"] = evaluate_case(output / "frozen" / row["variant"], execution)
        row["runs"] = {}
        for program in ("candidate", "reference", "base"):
            result_path = execution / program / "result.json"
            if result_path.exists():
                result = json.loads(result_path.read_text())
                row["runs"][program] = {key: result.get(key) for key in ("status", "counts", "errors", "artifact_sha256")}
        row["not_executed"] = (execution / "not_executed.json").exists()
        variants.append(row)
    result = {"case_id": args.case, "generation_counts": manifest["generation_counts"],
              "corpus_coverage": manifest["corpus_coverage"], "budget": manifest["budget"],
              "declared_admission_rounds": manifest["declared_admission_rounds"], "admissions": admissions,
              "external_model_calls": sum(row["external_model_calls"] or 0 for row in admissions),
              "unresolved_model_call_records": sum(row["external_model_calls"] is None for row in admissions),
              "model_request_attempts": sum(row["model_request_attempts"] for row in admissions),
              "missing_admission_rounds": sorted(set(manifest["declared_admission_rounds"]) - {row["round"] for row in admissions}),
              "variants": variants, "all_rounds_reported_without_best_selection": True,
              "interpretation": "Candidate/reference outcomes are evaluation evidence, not oracle truth; no execution result is fed back into generation."}
    write_json(output / "summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="stage", required=True)
    for name in ("prepare", "admit", "freeze", "run", "summarize"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--registry", default="pilot", help="pilot, holdout, controls, or a JSON registry path")
        sub.add_argument("--case", required=True)
        sub.add_argument("--output", required=True, type=Path)
        sub.add_argument("--case-root", type=Path)
        if name == "prepare":
            sub.add_argument("--model", default="closeai/gpt-5.6-luna")
            sub.add_argument("--generator", choices=("context", "analogy"), default="context")
            sub.add_argument("--retrieval", type=Path)
            sub.add_argument("--max-candidates", type=int, default=128)
            sub.add_argument("--top-k", type=int, default=10)
            sub.add_argument("--max-files", type=int, default=400)
        if name in {"admit", "freeze", "run"}:
            sub.add_argument("--rerun-id", choices=("r1", "r2"), default="r1")
        if name == "admit":
            sub.add_argument("--cache-output", type=Path)
            sub.add_argument("--model", default="closeai/gpt-5.6-luna")
            sub.add_argument("--max-tokens", type=int, default=10000)
        if name in {"freeze", "run"}:
            sub.add_argument("--direct-baseline", action="store_true")
        if name == "freeze":
            sub.add_argument("--timeout", type=int, default=180)
        if name == "run":
            sub.add_argument("--program", choices=("candidate", "reference", "base", "pair"), default="candidate")
            sub.add_argument("--reference-patch", type=Path)
            sub.add_argument("--reference-repository", type=Path)
            sub.add_argument("--execution-output", type=Path)
    args = parser.parse_args()
    if args.stage == "prepare" and not 1 <= args.max_candidates <= 128:
        parser.error("The preregistered candidate budget is 1..128")
    if args.stage == "admit" and not 1 <= args.max_tokens <= 10000:
        parser.error("The preregistered output-token budget is 1..10000")
    result = globals()[args.stage](args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
