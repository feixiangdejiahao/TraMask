"""Limit the old T01 metadata recovery to historical function references.

The initial runner applied that strict recovery to repository symbols too. It
rejected unresolved TypeScript arrow-function references which the unchanged
extractor otherwise preserves as partial evidence. No affected trial had a
model call. This adapter restores only historical records and leaves repository
resolution exactly as the v3 extractor supplies it.
"""
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT)]
from scripts import run_augmentation_detection30_v3 as campaign
from augmentation.pipeline import write_json
from augmentation.program import span
from anchor_retrieval.syntax import units


def historical_records(program):
    paths={p for p,s in program["sources"].items() if s.origin!="repository"}
    references={fid for n in program["behavior_graph"]["nodes"].values() for fid in n.get("targets",[])}
    references.update(fid for call in program["calls"] for fid in call["targets"])
    missing=references-program["functions"].keys()
    wanted={fid for fid in missing if any(fid.startswith(p+":") for p in paths)}
    recovered=[]
    for path in paths:
        source=program["sources"][path]
        if not any(fid.startswith(path+":") for fid in wanted):
            continue
        for unit in units(source)[0]:
            if unit.id not in wanted:
                continue
            program["functions"][unit.id]={"id":unit.id,"name":unit.name,"owner":unit.owner,
                "span":span(source,unit.node),"body_span":span(source,unit.body),
                "parameters":[{"name":p,"index":i} for i,p in enumerate(unit.params)],
                "production":not unit.test,"test":unit.test}
            recovered.append({"id":unit.id,"origin":source.origin,"span":span(source,unit.node)})
    if wanted-program["functions"].keys():
        raise ValueError("Historical references still lack metadata")
    return recovered


def recover(case,protocol):
    from scripts import recover_augmentation_pilot30_v2_functions as old
    old.restore_function_records=historical_records
    directory=campaign.RUN/"cases"/case["id"]
    assert not list(directory.glob("detector/*/round*/manifest.json"))
    write_json(directory/"extraction_recovery.json",{
        "reason":"The runner applied the historical-only recovery to unresolved repository arrow-function symbols.",
        "fix":"Reconstruct historical metadata only; retain the original v3 repository resolution.",
        "algorithm_source_unchanged":True,"prior_model_calls":0,"script":campaign.receipt(__file__),
        "initial_failure":campaign.receipt(directory/"extraction_failure.json")})
    return campaign.prepare_case(case,protocol)


def main():
    protocol=campaign.check_protocol()
    cases=[c for c in campaign.read(campaign.RUN/"cases.json")
           if (campaign.RUN/"cases"/c["id"]/"extraction_failure.json").exists()
           and not (campaign.RUN/"cases"/c["id"]/"extraction.json").exists()]
    with ProcessPoolExecutor(max_workers=4) as pool:
        pending={pool.submit(recover,c,protocol):c for c in cases}
        for future in as_completed(pending):
            case=pending[future]
            try:
                row=future.result();print(json.dumps({"case":case["id"],"status":"recovered","seconds":row["seconds"]}),flush=True)
            except Exception as exc:
                campaign.record_failure(case,"recovery",exc)


if __name__=="__main__":
    main()
