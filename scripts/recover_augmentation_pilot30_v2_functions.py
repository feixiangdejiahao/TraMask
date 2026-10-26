"""Recover missing historical function metadata before T01's first model call.

The frontend can retain a resolved historical call target but omit its function
record. Reconstruct that record from the original parsed source. No target is
selected using reference labels. A reachability cache preserves search results.
The original algorithm files and initial failure remain immutable.
"""
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts import run_augmentation_pilot30_v2 as campaign
from augmentation import pipeline, program, search
from augmentation.pipeline import write_json
from anchor_retrieval.syntax import units


def restore_function_records(result):
    references = {fid for node in result["behavior_graph"]["nodes"].values() for fid in node.get("targets", [])}
    references.update(fid for call in result["calls"] for fid in call["targets"])
    missing = references - result["functions"].keys()
    recovered = []
    for source in result["sources"].values():
        if not any(fid.startswith(source.path + ":") for fid in missing):
            continue
        for unit in units(source)[0]:
            if unit.id not in missing:
                continue
            result["functions"][unit.id] = {"id": unit.id, "name": unit.name, "owner": unit.owner,
                "span": program.span(source, unit.node), "body_span": program.span(source, unit.body),
                "parameters": [{"name": name, "index": i} for i, name in enumerate(unit.params)],
                "production": not unit.test, "test": unit.test}
            recovered.append({"id": unit.id, "origin": source.origin,
                              "span": program.span(source, unit.node)})
    remaining = missing - result["functions"].keys()
    if remaining:
        raise ValueError("Unrecoverable source function references: " + repr(sorted(remaining)))
    return recovered


def cached_reachable(result, start):
    cache = result.setdefault("_recovery_reachability_cache", OrderedDict())
    key = tuple(sorted(set(start)))
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    edges = result.get("_recovery_call_adjacency")
    if edges is None:
        edges = defaultdict(set)
        for edge in result["edges"]:
            if edge["kind"] == "call":
                edges[edge["from"]].add(edge["to"])
        result["_recovery_call_adjacency"] = edges
    seen, pending = set(), list(key)
    while pending:
        item = pending.pop()
        if item not in seen:
            seen.add(item)
            pending.extend(edges.get(item, set()) - seen)
    cache[key] = seen
    if len(cache) > 4096:
        cache.popitem(last=False)
    return seen


def main():
    case_id = sys.argv[1]
    assert case_id == "T01"
    protocol = campaign.check_protocol()
    case = next(c for c in campaign.read(campaign.RUN / "cases.json") if c["id"] == case_id)
    directory = campaign.RUN / "cases" / case_id
    assert not (directory / "agent").exists()
    original_build = pipeline.build_program

    def recovered_build(*args, **kwargs):
        started = time.monotonic()
        result = original_build(*args, **kwargs)
        recovered = restore_function_records(result)
        write_json(directory / "function-record-recovery.json", {
            "cause": "A resolved historical helper target lacked its retained function metadata.",
            "script": campaign.receipt(__file__), "prior_model_calls": 0,
            "original_algorithm_unchanged": True, "selection_and_model_budget_unchanged": True,
            "reconstructed_from_public_source_only": recovered,
            "reachability_cache": "Identical directed-call transitive closure with bounded memoization.",
            "program_build_seconds": time.monotonic() - started,
        })
        print({"case": case_id, "stage": "program_built", "recovered_functions": len(recovered)}, flush=True)
        return result

    pipeline.build_program = recovered_build
    pipeline.reachable = cached_reachable
    search.reachable = cached_reachable
    extracted = campaign.prepare_case(case, protocol)
    write_json(directory / "recovery-extraction-receipt.json", {
        "extraction": campaign.receipt(directory / "extraction.json"),
        "recovery": campaign.receipt(directory / "function-record-recovery.json"),
    })
    print({"case": case_id, "stage": "prepared", "seconds": extracted["seconds"]}, flush=True)
    print(campaign.generate_case(case, protocol), flush=True)


if __name__ == "__main__":
    main()
