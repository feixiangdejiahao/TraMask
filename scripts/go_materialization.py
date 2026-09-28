"""Go parser-backed emission cleanup; no target labels or oracle changes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/go_source_materializer/main.go"
_BUILD_LOCK = threading.Lock()


def _binary():
    key = hashlib.sha256(HELPER.read_bytes()).hexdigest()[:20]
    directory = ROOT / ".cache/go_source_materializer"
    destination = directory / key
    with _BUILD_LOCK:
        if not destination.exists():
            directory.mkdir(parents=True, exist_ok=True)
            environment = dict(os.environ, GOCACHE=str(directory / "build_cache"), GO111MODULE="off")
            temporary = directory / (key + "." + str(os.getpid()))
            subprocess.run(["go", "build", "-o", str(temporary), str(HELPER)],
                           env=environment, check=True, capture_output=True, text=True, timeout=120)
            temporary.replace(destination)
    return destination


def materialize_go_files(files, obligations, controls, corpus, selection, *, repository=None):
    """Modify generated Go bodies and unselected historical test declarations.

    Source control function bodies are never edited. Historical function removal
    is based solely on selected source IDs and lexical function references.
    """
    inputs = []
    for path, code in files.items():
        if not path.endswith(".go"):
            continue
        generated = [row["test_name"] for row in obligations if row["path"] == path]
        keep = [row["test_name"] for row in controls if row["path"] == path]
        for row in [*obligations, *controls]:
            if row["path"] == path:
                keep.append(corpus["tests"][row["base_test_id"]]["name"])
        inputs.append({"path": path, "code": code, "generated": generated, "keep": sorted(set(keep)),
                       "historical": selection.get("files", {}).get(path, {}).get("kind") == "historical_validation"})
    if not inputs:
        return dict(files), []
    process = subprocess.run([str(_binary())], input=json.dumps({"files": inputs, "prune_history": True,
                                                               "repository": str(repository) if repository else ""}),
                             capture_output=True, text=True, check=True, timeout=60)
    records = json.loads(process.stdout)
    output = dict(files)
    for record in records:
        output[record["path"]] = record["code"]
        record["before_sha256"] = hashlib.sha256(files[record["path"]].encode()).hexdigest()
        record["after_sha256"] = hashlib.sha256(record.pop("code").encode()).hexdigest()
    return output, records
