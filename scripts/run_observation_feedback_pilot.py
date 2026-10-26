"""Uniform feedback-view ablation over every case/repeat of the evolution pilot."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from scripts import run_validation_evolution_pilot_v3 as main_experiment
from augmentation.observation_feedback import observation_view
from augmentation.pipeline import write_json

shared = main_experiment.shared
BASE = main_experiment.RUN
RUN = BASE/"observation_view"
shared.RUN = RUN
read = main_experiment.read


def hashes():
    return {**main_experiment.hashes(), str(Path(__file__).relative_to(ROOT)): shared.method.previous.digest(__file__),
            "src/augmentation/observation_feedback.py": shared.method.previous.digest(ROOT/"src/augmentation/observation_feedback.py")}


def prepare():
    RUN.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(BASE/"cases.json", RUN/"cases.json")
    (RUN/"inputs").symlink_to("../inputs", target_is_directory=True)
    write_json(RUN/"evaluation/criteria.json", read(BASE/"evaluation/criteria.json"))
    protocol = read(BASE/"protocol.json")
    protocol.update(created_at=datetime.now(timezone.utc).isoformat(), arms=["E_observations"], planned_final_outputs=24,
                    unique_planned_model_calls=48, code_sha256=hashes(),
                    comparison="D_probe versus E_observations: identical investigation, ranked hypotheses, diagnostic test bytes and actual executions; only the feedback presentation changes. Final augmentation execution/revision stays the same.",
                    selection="Every one of the twelve cases and both repeats. No success-based or failure-based case selection.",
                    motivation="A logging-only probe can expose the predicted discrepancy while its test framework reports pass. Test whether separating completion from observations changes the model decision.",
                    transformation="Remove framework banners/status fields, retain all textual observations and execution errors, retain returncode and add a generic explanation that runner completion is not a requirement verdict. No target-specific annotation or new execution/source evidence.",
                    primary_comparison_limit="A representation/interpretation diagnostic, not proof of a new program-analysis algorithm or a general model improvement.")
    write_json(RUN/"protocol.json", protocol)
    print(json.dumps({"prepared": str(RUN), "outcomes": 24, "model_calls": 48}), flush=True)


def check():
    p = read(RUN/"protocol.json")
    if p["code_sha256"] != hashes(): raise RuntimeError("frozen_code_changed")
    for path, digest in p["input_sha256"].items():
        if shared.method.previous.digest(RUN/path) != digest: raise RuntimeError("frozen_input_changed")
    return p


def run_one(case, repeat):
    directory = RUN/"runs"/case["id"]/"E_observations"/f"repeat{repeat}"
    if (directory/"result.json").exists(): return
    original_request = BASE/"runs"/case["id"]/"D_probe"/f"repeat{repeat}"/"stage3/primary/request.json"
    if not original_request.exists(): raise RuntimeError("base_probe_request_not_ready")
    request = read(original_request)
    body = json.loads(request["messages"][1]["content"])
    transformed = observation_view(body["diagnostic_observations"])
    material = {**body, "diagnostic_observations": transformed}
    write_json(directory/"comparison_receipt.json", {"base_request": str(original_request.relative_to(ROOT)),
               "base_request_sha256": shared.method.previous.digest(original_request),
               "transformation": transformed, "only_diagnostic_observations_changed": {k:v for k,v in material.items() if k!="diagnostic_observations"} == {k:v for k,v in body.items() if k!="diagnostic_observations"}})
    draft = shared.model_call(directory/"stage3", shared.method.BUILD, material, 3)
    feedback = shared.execute_targets(case, draft, directory/"draft_execution")
    final = shared.model_call(directory/"stage4", shared.method.BUILD+shared.method.REVISE,
                              {**material, "draft": draft, "original_patch_execution": feedback}, 4)
    final_execution = shared.execute_targets(case, final, directory/"final_execution")
    result = {"case": case["id"], "arm": "E_observations", "repeat": repeat, "final": final,
              "technical_unknown": bool(final.get("technical_unknown")),
              "execution_status": {k:v["status"] for k,v in final_execution.items()},
              "shared_prefix": f"../runs/{case['id']}/C_history/repeat{repeat}"}
    write_json(directory/"result.json", result)
    print(json.dumps({"finished": f"{case['id']}/E_observations/{repeat}", "decisions": [r['decision'] for r in final.get('targets',[])], "execution": result["execution_status"]}), flush=True)


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument("action",choices=["prepare","run","status"])
    p.add_argument("--workers",type=int,default=4)
    p.add_argument("--ready-only",action="store_true")
    a=p.parse_args()
    if a.action=="prepare": prepare();return
    check()
    if a.action=="status": shared.status();return
    jobs=[(c,r) for c in read(RUN/"cases.json") for r in [1,2]]
    if a.ready_only:
        jobs=[(c,r) for c,r in jobs if (BASE/"runs"/c['id']/"D_probe"/f"repeat{r}"/"stage3/primary/request.json").exists()]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(run_one,*job) for job in jobs]): f.result()
    shared.status()


if __name__=="__main__":main()
