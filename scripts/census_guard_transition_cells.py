"""Label-free coverage census of the separate guard-transition prototype."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from relation_search.checkpoint import digest, read, write


def census(args):
    if args.variant == "partial":
        from prototypes.guard_transition_cells_v2 import POLICY, candidate_cells
    else:
        from prototypes.guard_transition_cells import POLICY, candidate_cells
    started = time.monotonic()
    deadline = started + args.max_seconds
    frozen = read(args.sample/"protocol.json")
    source, inventory = Path(frozen["source"]), Path(frozen["inventory"])
    records, selected, checksums = {}, {}, {}
    for case in frozen["cases"]:
        name = "candidates.json" if args.mode == "sample" else "source_pool.json"
        pool_path = inventory/case/name
        pool = read(pool_path)["candidates"]
        if args.mode == "sample":
            ids = [row["candidate_id"] for row in read(args.sample/case/"records.json")]
            by_id = {row["id"]: row for row in pool}
            members = [by_id[identifier] for identifier in ids]
        else:
            members = sorted(pool, key=lambda row: hashlib.sha256(row["id"].encode()).hexdigest())
        records[case] = members
        selected[case] = [row["id"] for row in members]
        checksums[case] = {str(path): digest(path) for path in [pool_path, source/case/"corpus.json", source/case/"frontend.json"]}
    files = [Path(__file__), ROOT/"prototypes/guard_transition_cells.py", ROOT/"relational_gap/frontend.py",
             ROOT/"anchor_retrieval/syntax.py", ROOT/"relation_search/instrument.py"]
    if args.variant == "partial":
        files.append(ROOT/"prototypes/guard_transition_cells_v2.py")
    code = {str(path.relative_to(ROOT)): digest(path) for path in files}
    protocol = dict(policy=POLICY, mode=args.mode, variant=args.variant, sample_protocol_sha256=digest(args.sample/"protocol.json"),
                    candidate_ids=selected, input_sha256=checksums, code_sha256=code,
                    provider_calls=0, subject_executions=0, max_seconds=args.max_seconds,
                    selection="exact previous SHA-selected cohort" if args.mode == "sample" else "all fixed pool candidates, SHA ID order")
    if args.output.exists():
        raise ValueError("output must be new")
    write(args.output/"protocol.json", protocol)
    for path in files:
        target = args.output/"algorithm_snapshot"/path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    totals, summary = Counter(), {}
    all_reasons = Counter()
    all_partial_reasons = Counter()
    stopped = False
    for case, members in records.items():
        case_started = time.monotonic()
        corpus, frontend = read(source/case/"corpus.json"), read(source/case/"frontend.json")
        local, reasons, partial_reasons = Counter(), Counter(), Counter()
        rows = []
        for item in members:
            if time.monotonic() >= deadline:
                stopped = True
                break
            tick = time.monotonic()
            try:
                result = candidate_cells(corpus, frontend, item)
                known = bool(result["records"])
                cross = any(row["before_order"] != row["after_order"] for row in result["records"])
                cause = sorted({row["reason"] for row in result["unknowns"]})
                partial = sorted({row["reason"] for row in result.get("partial_bindings", [])})
                if not known and not cause:
                    cause = ["no_observed_operation_or_changed_supported_guard"]
                row = dict(id=item["id"], status="analyzed", known_cell=known, crossed_guard=cross,
                           comparison_records=len(result["records"]), unknown_reasons=cause,
                           partial_environment=bool(partial), partial_binding_reasons=partial,
                           elapsed_seconds=round(time.monotonic()-tick, 5))
                write(args.output/case/(item["id"]+".json"), result)
            except Exception as error:
                row = dict(id=item["id"], status="error", error_type=type(error).__name__,
                           error=str(error)[:300], known_cell=False, crossed_guard=False,
                           comparison_records=0, unknown_reasons=["analysis_error:"+type(error).__name__],
                           partial_environment=False, partial_binding_reasons=[],
                           elapsed_seconds=round(time.monotonic()-tick, 5))
            rows.append(row)
            local.update(analyzed=1, known_cell=int(row["known_cell"]), crossed_guard=int(row["crossed_guard"]),
                         errors=int(row["status"] == "error"), comparison_records=row["comparison_records"])
            local.update(partial_environment=int(row["partial_environment"]))
            reasons.update(row["unknown_reasons"])
            partial_reasons.update(row["partial_binding_reasons"])
            # Each candidate has its own immutable output; refresh small
            # progress receipts so a supervised stop retains completed work.
            write(args.output/case/"records.json", rows)
        totals.update(local)
        all_reasons.update(reasons)
        all_partial_reasons.update(partial_reasons)
        summary[case] = dict(local, intended=len(members), unknown_candidate_reasons=dict(reasons),
                             partial_binding_candidate_reasons=dict(partial_reasons),
                             elapsed_seconds=round(time.monotonic()-case_started, 3))
        write(args.output/"summary.json", dict(cases=summary, totals=dict(totals),
            unknown_candidate_reasons=dict(all_reasons), stopped_at_budget=stopped,
            partial_binding_candidate_reasons=dict(all_partial_reasons),
            intended=sum(map(len, records.values())), elapsed_seconds=round(time.monotonic()-started, 3)))
        print(json.dumps(dict(case=case, **summary[case])), flush=True)
        if stopped:
            break
    return read(args.output/"summary.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["sample", "full"], default="sample")
    parser.add_argument("--variant", choices=["strict", "partial"], default="strict")
    parser.add_argument("--max-seconds", type=float, default=840)
    args = parser.parse_args()
    result = census(args)
    print(json.dumps(dict(totals=result["totals"], elapsed_seconds=result["elapsed_seconds"],
                          stopped_at_budget=result["stopped_at_budget"])), flush=True)
