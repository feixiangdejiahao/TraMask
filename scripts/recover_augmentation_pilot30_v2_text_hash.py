"""Recover pre-dispatch CRLF hash mismatches without changing model inputs.

The extractor hashes decoded source text. The campaign initially compared raw
bytes. Verify decoded text with the same normalization and retain raw receipts.
No candidate, prompt, model budget, generated test, or production file changes.
"""
from collections import Counter
import hashlib
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.run_augmentation_pilot30_v2 import RUN, read, receipt, check_protocol, execute_case
from augmentation.agent import run_agent
from augmentation.pipeline import write_json


def main():
    case_id = sys.argv[1]
    protocol = check_protocol()
    case = next(c for c in read(RUN / "cases.json") if c["id"] == case_id)
    directory = RUN / "cases" / case_id
    if (directory / "agent").exists():
        raise ValueError("Only pre-dispatch failures can use this recovery")
    prepared = read(directory / "prepared.json")
    mismatches = []
    for path, expected in prepared["source_receipts"].items():
        source = Path(case["repository"]) / path
        raw = receipt(source)
        if raw["sha256"] != expected:
            normalized = hashlib.sha256(source.read_text().encode()).hexdigest()
            if normalized != expected:
                raise ValueError("Source text changed: " + path)
            mismatches.append({**raw, "decoded_text_sha256": normalized,
                               "crlf_count": source.read_bytes().count(b"\r\n")})
    assert mismatches
    write_json(directory / "text-hash-recovery.json", {
        "reason": "Extractor hashed decoded source text; campaign compared raw CRLF bytes.",
        "source_text_unchanged": True, "prepared": receipt(directory / "prepared.json"),
        "mismatches": mismatches, "recovery_script": receipt(__file__),
        "model_inputs_and_budget_unchanged": True, "prior_model_calls": 0,
    })
    started = time.monotonic()
    result = run_agent(prepared, directory / "agent", provider_root=ROOT,
                       command=["benchmark-native-frozen-harness"],
                       executor=lambda *a, **kw: execute_case(case, *a, **kw), **protocol["agent"])
    summary = {"case": case_id, "status": "complete", "seconds": time.monotonic() - started,
               "model_calls": result["external_model_calls"], "charged_tokens": result["charged_tokens"],
               "proposals": result["generated_proposals"], "statuses": dict(Counter(r["status"] for r in result["results"])),
               "results": receipt(directory / "agent/results.json"),
               "transport_recovery": receipt(directory / "text-hash-recovery.json")}
    write_json(directory / "generation.json", summary)
    print(summary)


if __name__ == "__main__":
    main()
