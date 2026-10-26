"""Same evolution experiment, with lossless handling of same-file appends."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from scripts import run_validation_evolution_pilot_v2 as previous
from augmentation import evolution_transport as transport
from augmentation.pipeline import write_json

shared = previous.shared
OLD = previous.RUN
RUN = ROOT/"experiments/validation_evolution/results/pilot12_20261016_v3"
shared.RUN = RUN
old_hashes, old_read = shared.hashes, shared.read
shared.method.validate = transport.validate


def hashes():
    return {**old_hashes(), str(Path(__file__).relative_to(ROOT)): shared.method.previous.digest(__file__),
            str(Path(transport.__file__).relative_to(ROOT)): shared.method.previous.digest(transport.__file__)}


def read(path):
    return transport.parse_completion(Path(path).read_text()) if Path(path).name == "completion.txt" else old_read(path)


shared.hashes = hashes
shared.read = read


def prepare():
    RUN.mkdir(parents=True, exist_ok=False)
    for name in ["inputs", "preflight", "transport_preflight", "real_transport_preflight"]:
        shutil.copytree(OLD/name, RUN/name)
    for name in ["cases.json", "preparation.json", "preflight_summary.json"]:
        shutil.copyfile(OLD/name, RUN/name)
    write_json(RUN/"evaluation/criteria.json", read(OLD/"evaluation/criteria.json"))
    reused = []
    for prefix in sorted(OLD.glob("runs/*/*/*")):
        first = prefix/"stage1/parsed.json"
        if not first.exists() or read(first).get("technical_unknown"): continue
        for stage in [1, 2]:
            source = prefix/f"stage{stage}"
            if not (source/"parsed.json").exists() or read(source/"parsed.json").get("technical_unknown"): continue
            destination = RUN/source.relative_to(OLD)
            shutil.copytree(source, destination)
            write_json(destination/"reuse_receipt.json", {"source": str(source.relative_to(ROOT)),
                        "parsed_sha256": shared.method.previous.digest(source/"parsed.json"),
                        "reason": "Completed valid investigation before the transport fix. No semantic outcome used for reuse selection."})
            for path in destination.glob("*/manifest.json"):
                manifest = read(path)
                manifest["reused_external_model_calls"] = manifest.get("external_model_calls", 0)
                manifest["external_model_calls"] = 0
                manifest["reused_from"] = str((OLD/path.relative_to(RUN)).relative_to(ROOT))
                write_json(path, manifest)
            reused.append(str(destination.relative_to(RUN)))
        if (prefix/"retrieved.json").exists():
            dest = RUN/prefix.relative_to(OLD)/"retrieved.json"
            shutil.copyfile(prefix/"retrieved.json", dest)
    write_json(RUN/"reuse.json", {"stages": reused, "source_run": str(OLD.relative_to(ROOT)),
               "rule": "Reuse every available valid first-stage investigation, and its valid second stage. No final generation, final feedback, scores or evaluator evidence is reused."})
    print(json.dumps({"prepared": str(RUN), "reused_stages": len(reused)}), flush=True)


def freeze():
    if (RUN/"protocol.json").exists(): raise RuntimeError("already_frozen")
    protocol = read(OLD/"protocol.json")
    protocol.update(created_at=datetime.now(timezone.utc).isoformat(),
                    transport_repair="Join sequential append edits to the same path without changing any fragment. Distinct JSON objects may merge only if their keys do not conflict. Same file/test/target caps remain in force.",
                    prefix_reuse=read(RUN/"reuse.json"),
                    budget_accounting="336 logical stage outputs, including reused valid investigations. Count new and inherited physical provider calls separately; retain all stopped-run costs.",
                    code_sha256=hashes(),
                    input_sha256={str(p.relative_to(RUN)): shared.method.previous.digest(p) for p in sorted((RUN/"inputs").glob("*/*.json"))})
    write_json(RUN/"protocol.json", protocol)
    print(json.dumps({"frozen": str(RUN), "outcomes": 96, "logical_stages": 336}), flush=True)


def main():
    if len(sys.argv)>1 and sys.argv[1] == "prepare": prepare(); return
    if len(sys.argv)>1 and sys.argv[1] == "freeze": freeze(); return
    shared.main()


if __name__ == "__main__": main()
