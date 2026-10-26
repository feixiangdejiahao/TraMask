"""Uniform non-thinking transport for the frozen evolution experiment.

The first transport consumed its reasoning budget before emitting JSON on seven
of eight initial requests. This version keeps cases, evidence, prompts, targets,
queries and execution policy; it changes only the model's thinking switch.
"""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from scripts import run_validation_evolution_pilot as shared
from augmentation.provider import dispatch as original_dispatch
from augmentation.pipeline import write_json

OLD = shared.RUN
RUN = ROOT/"experiments/validation_evolution/results/pilot12_20261016_v2"
shared.RUN = RUN
base_hashes = shared.hashes


def hashes():
    return {**base_hashes(), str(Path(__file__).relative_to(ROOT)): shared.method.previous.digest(__file__)}


def dispatch(request, *args, **kwargs):
    return original_dispatch({**request, "thinking": "disabled"}, *args, **kwargs)


shared.hashes = hashes
shared.dispatch = dispatch


def prepare():
    RUN.mkdir(parents=True, exist_ok=False)
    for name in ["inputs", "preflight"]:
        shutil.copytree(OLD/name, RUN/name)
    for name in ["cases.json", "preparation.json", "preflight_summary.json"]:
        shutil.copyfile(OLD/name, RUN/name)
    write_json(RUN/"evaluation/criteria.json", shared.read(OLD/"evaluation/criteria.json"))
    write_json(RUN/"transport_change.json", {"reason": "Seven of the first eight primary calls emitted no JSON before a 32768-token reasoning limit; the eighth returned query-only JSON missing hypotheses.",
                "old_run": str(OLD.relative_to(ROOT)), "change": "Set thinking.type=disabled uniformly at every model stage. Same method prompts and materials, target caps and execution protocol.",
                "model": shared.MODEL, "old_outputs_not_used_as_guidance": True})
    print(json.dumps({"prepared": str(RUN)}), flush=True)


def real_transport_preflight():
    cases = [("T05", "A_final"), ("T06", "C_history")]
    records = []
    for cid, arm in cases:
        public = shared.read(RUN/"inputs"/cid/"base.json")
        if arm != "A_final": public["validation_evolution"] = shared.read(RUN/"inputs"/cid/"evolution.json")
        if arm == "C_history": public["development_history"] = shared.read(RUN/"inputs"/cid/"history.json")
        out = RUN/"real_transport_preflight"/cid/arm
        request = {"id": str(out.relative_to(RUN)), "system": shared.method.COMMON+shared.method.INVESTIGATE,
                   "prompt": json.dumps({"public_evidence": public}, ensure_ascii=False), "max_tokens": 32768, "reasoning_effort": "medium"}
        manifest = shared.read(out/"manifest.json") if (out/"manifest.json").exists() else dispatch(request, out, root=ROOT, model=shared.MODEL)
        if manifest["status"] != "complete": raise RuntimeError("real_preflight_incomplete")
        parsed = shared.method.validate(shared.read(out/"completion.txt"), 1)
        write_json(out/"parsed.json", parsed)
        records.append({"case": cid, "arm": arm, "parsed": True, "response_model": manifest.get("response_model"), "usage": manifest.get("usage")})
        print(json.dumps(records[-1]), flush=True)
    write_json(RUN/"real_transport_preflight/summary.json", records)


def freeze():
    if (RUN/"protocol.json").exists(): raise RuntimeError("already_frozen")
    if len(shared.read(RUN/"transport_preflight/summary.json")) != 3 or len(shared.read(RUN/"real_transport_preflight/summary.json")) != 2:
        raise RuntimeError("preflight_incomplete")
    old = shared.read(OLD/"protocol.json")
    protocol = {**old, "created_at": datetime.now(timezone.utc).isoformat(), "thinking": "disabled",
                "reasoning_effort": "medium parameter retained; thinking disabled; inspect returned usage rather than assume backend behavior",
                "technical_preflight": "Three synthetic schema/code checks and two real-input investigation checks under the same non-thinking switch. Preflight outputs never enter formal generation and are not scored.",
                "transport_change": shared.read(RUN/"transport_change.json"),
                "code_sha256": hashes(),
                "input_sha256": {str(p.relative_to(RUN)): shared.method.previous.digest(p) for p in sorted((RUN/"inputs").glob("*/*.json"))}}
    write_json(RUN/"protocol.json", protocol)
    print(json.dumps({"frozen": str(RUN), "outcomes": 96, "calls": 336, "thinking": "disabled"}), flush=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "prepare": prepare(); return
    if len(sys.argv) > 1 and sys.argv[1] == "real-transport": real_transport_preflight(); return
    if len(sys.argv) > 1 and sys.argv[1] == "freeze": freeze(); return
    shared.main()


if __name__ == "__main__":
    main()
