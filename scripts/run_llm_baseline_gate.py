"""Exploratory semantic gate for an already frozen, independent LLM round.

  python scripts/run_llm_baseline_gate.py prepare --case CASE --source-round ROUND --output OUTPUT
  python scripts/run_llm_baseline_gate.py admit --case CASE --output OUTPUT
  python scripts/run_llm_baseline_gate.py freeze --case CASE --output OUTPUT
  python scripts/run_llm_baseline_gate.py run --case CASE --output OUTPUT --program candidate

No generation, repair, or round merging occurs. Only admit requests a model;
only run executes subjects. Each output has exactly one declared gate attempt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generic_composition import gate
from scripts import run_generic_experiment as driver

MODEL = "deepseek-v4-flash"
ROUND = "gate"
MAX_TOKENS = 10000
ORIGINAL_SYSTEM = gate.SYSTEM
SYSTEM = '''You judge semantic applicability of LLM-proposed test compositions.
A model proposed complete replacement bodies for existing source tests.
Syntax and binding checks DO NOT establish that an assertion remains
semantically correct in its new context.''' + "\n\n" + ORIGINAL_SYSTEM.split("\n\n", 1)[1]
SOURCE_FILES = ("case.json", "retrieval.json", "corpus.json", "evidence.json", "generated.json", "candidates.json")
EVIDENCE_KEYS = {"issue", "source_tests", "test_helpers", "production_context"}
CANDIDATE_KEYS = {"id", "kind", "language", "base_test_id", "source_test_ids", "imports", "edits", "provenance"}


def bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def adapter_hashes() -> dict:
    path = Path(__file__).resolve()
    return {str(path.relative_to(ROOT)): driver.digest(path)}


def request_template(evidence: dict, candidates: list) -> dict:
    return {"model": MODEL, "response_format": {"type": "json_object"}, "tool_choice": "none",
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps(gate.presentation(
                             evidence, gate.selection_candidates(candidates, "ordinal_v1")), ensure_ascii=False)}],
            "max_tokens": MAX_TOKENS, "temperature": 0, "thinking": {"type": "disabled"}, "reasoning_effort": "none"}


def prepare(args) -> dict:
    from combination_testing.runner import load_artifact

    source = args.source_round.resolve()
    original_prepare = (source / "prepare.json").read_bytes()
    original = json.loads(original_prepare)
    if (original.get("status") != "complete" or original.get("case_id") != args.case
            or original.get("generator") != "independent_llm_baseline"
            or original.get("generation_round") not in {"r1", "r2"}):
        raise ValueError("Input must be one completed independent LLM generation round for this case")
    # Validate all baseline caches against their original manifest, without
    # reinterpreting generation or reading any execution/audit directory.
    driver.checked_preparation(SimpleNamespace(output=source, case=args.case), check_code=False)
    copied = {}
    for name in SOURCE_FILES:
        copied[name] = (source / name).read_bytes()
        if bytes_digest(copied[name]) != original["files_sha256"][name]:
            raise ValueError("Original baseline input changed: " + name)
    receipt_bytes = (source / "freezes/direct.json").read_bytes()
    artifact_bytes = (source / "frozen/direct/manifest.json").read_bytes()
    receipt, artifact = json.loads(receipt_bytes), json.loads(artifact_bytes)
    if (receipt["artifact_sha256"] != bytes_digest(artifact_bytes)
            or artifact["metadata"]["prepare_sha256"] != bytes_digest(original_prepare)
            or artifact["metadata"].get("generation_round") != original["generation_round"]):
        raise ValueError("Original frozen artifact belongs to different bytes or round")
    load_artifact(source / "frozen/direct")
    generated, candidates = (json.loads(copied[name]) for name in ("generated.json", "candidates.json"))
    if generated["candidates"] != candidates:
        raise ValueError("Original candidates differ from the frozen generation output")
    evidence = json.loads(copied["evidence.json"])
    if set(evidence) - EVIDENCE_KEYS:
        raise ValueError("Baseline evidence contains non-static or unexpected fields")
    if any(set(candidate) - CANDIDATE_KEYS for candidate in candidates):
        raise ValueError("Baseline candidates contain unexpected fields")
    evidence["candidate_origin"] = (
        "An independent language-model request proposed each complete parent-test body replacement. "
        "These bodies and expected values are unchanged. Mechanical parsing and lexical checks do not "
        "establish semantic applicability or oracle correctness. No audit label, reference code, or execution outcome is supplied.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name, data in copied.items():
        (output / name).write_bytes(data)
    (output / "source_evidence.json").write_bytes(copied["evidence.json"])
    driver.write_json(output / "evidence.json", evidence)
    (output / "source_prepare.json").write_bytes(original_prepare)
    (output / "source_freeze_receipt.json").write_bytes(receipt_bytes)
    (output / "source_artifact_manifest.json").write_bytes(artifact_bytes)
    (output / "gate_system.txt").write_text(SYSTEM)
    driver.write_json(output / "gate_request_template.json", request_template(
        json.loads((output / "evidence.json").read_bytes()), candidates))
    algorithm, adapter = driver.algorithm_hashes(), adapter_hashes()
    for name in {**algorithm, **adapter}:
        destination = output / "algorithm_snapshot" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    if algorithm != driver.algorithm_hashes() or adapter != adapter_hashes():
        raise ValueError("Algorithm changed during postgate preparation")
    files = [*SOURCE_FILES, "source_evidence.json", "source_prepare.json", "source_freeze_receipt.json",
             "source_artifact_manifest.json", "gate_system.txt", "gate_request_template.json"]
    manifest = {"version": 1, "case_id": args.case, "status": "complete",
                "generator": "independent_llm_baseline_with_semantic_gate", "study_status": "exploratory_postgeneration_filter",
                "created_at": datetime.now(timezone.utc).isoformat(), "source_round": str(source),
                "source_generation_round": original["generation_round"],
                "source_prepare_sha256": bytes_digest(original_prepare),
                "source_artifact_sha256": bytes_digest(artifact_bytes),
                "source_files_sha256": {name: bytes_digest(value) for name, value in copied.items()},
                "source_baseline_algorithm_sha256": original.get("baseline_algorithm_sha256", {}),
                "source_generation_request_sha256": original["files_sha256"].get("generation/request.json"),
                "source_generation_response_sha256": original["files_sha256"].get("generation/response.json"),
                "algorithm_sha256": algorithm, "postgate_adapter_sha256": adapter,
                "original_gate_system_sha256": bytes_digest(ORIGINAL_SYSTEM.encode()),
                "gate_system_sha256": bytes_digest(SYSTEM.encode()),
                "gate_prompt_change": "Only the first paragraph changes from program construction to LLM body proposals; all remaining semantic policy and accepted-ID schema are identical",
                "declared_admission_rounds": [ROUND], "expected_model": MODEL,
                "budget": {"model_calls_per_round": 1, "max_output_tokens_per_round": MAX_TOKENS,
                           "max_candidates": len(candidates)},
                "generation_counts": generated.get("counts", {}), "corpus_coverage": original.get("corpus_coverage", {}),
                "external_model_calls": 0, "subject_execution": False, "execution_outcomes": False,
                "reference_or_verifier_inputs": False, "audit_labels_as_inputs": False,
                "generation_repairs": 0, "rounds_merged": False,
                "files_sha256": {name: driver.digest(output / name) for name in files}}
    driver.write_json(output / "prepare.json", manifest)
    return {"stage": "prepare", "case_id": args.case, "output": str(output),
            "source_generation_round": original["generation_round"], "candidates": len(candidates),
            "study_status": manifest["study_status"]}


def adapted(args):
    values = dict(vars(args))
    values.update(rerun_id=ROUND, model=MODEL, max_tokens=MAX_TOKENS,
                  cache_output=None, direct_baseline=False)
    return SimpleNamespace(**values)


def checked(args, *, check_code=True):
    manifest, _ = driver.checked_preparation(adapted(args), check_code=check_code)
    if (manifest.get("generator") != "independent_llm_baseline_with_semantic_gate"
            or manifest.get("declared_admission_rounds") != [ROUND] or manifest.get("expected_model") != MODEL):
        raise ValueError("Output is not the declared one-shot LLM postgate experiment")
    if check_code and (manifest["postgate_adapter_sha256"] != adapter_hashes()
                       or manifest["gate_system_sha256"] != bytes_digest(SYSTEM.encode())):
        raise ValueError("Postgate adapter or prompt changed after preparation")
    return manifest


def admit(args) -> dict:
    checked(args)
    previous = gate.SYSTEM
    try:
        gate.SYSTEM = SYSTEM
        result = driver.admit(adapted(args))
    finally:
        gate.SYSTEM = previous
    checked(args)
    checked_request(args)
    return result


def checked_request(args):
    output = args.output.resolve()
    marker = json.loads((output / "admission/gate.json").read_bytes())
    if marker["status"] == "no_candidates":
        if json.loads((output / "candidates.json").read_bytes()):
            raise ValueError("Nonempty candidates recorded as no candidates")
        return
    actual = json.loads((Path(marker["cache"]) / "request.json").read_bytes())
    expected = json.loads((output / "gate_request_template.json").read_bytes())
    if actual != expected:
        raise ValueError("Cached admission request differs from frozen postgate evidence and prompt")


def freeze(args) -> dict:
    checked(args)
    checked_request(args)
    return driver.freeze(adapted(args))


def run(args) -> dict:
    checked(args, check_code=False)
    return driver.run(adapted(args))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    stages = parser.add_subparsers(dest="stage", required=True)
    for name in ("prepare", "admit", "freeze", "run"):
        sub = stages.add_parser(name)
        sub.add_argument("--case", required=True)
        sub.add_argument("--output", required=True, type=Path)
        if name == "prepare":
            sub.add_argument("--source-round", required=True, type=Path)
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
