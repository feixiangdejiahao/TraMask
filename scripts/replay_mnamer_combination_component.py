"""Replay the public candidate's daemon component, without its CLI parser.

Only import-only package shells and a settings value object are substituted.
The complete added mnamer/daemon.py is extracted verbatim from model.patch.
No reference implementation, provider, background daemon or network is used.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types


ROOT = Path(__file__).resolve().parents[1]
TRIAL = "mnamer-daemon-watch-lifecycle__4add9Ug"
DEST = ROOT / "results/expanded_trials_20260926/trials" / TRIAL


def main() -> None:
    patch = (DEST / "model.patch").read_text()
    section = patch.split("diff --git a/mnamer/daemon.py b/mnamer/daemon.py\n", 1)[1]
    section = section.split("\ndiff --git ", 1)[0]
    assert "--- /dev/null" in section
    source = "\n".join(line[1:] for line in section.splitlines()
                       if line.startswith("+") and not line.startswith("+++")) + "\n"
    out = DEST / "component_replay"
    out.mkdir(exist_ok=True)
    (out / "candidate_daemon.py").write_text(source)

    package = types.ModuleType("mnamer")
    package.__file__ = str(out / "__init__.py")
    exceptions = types.ModuleType("mnamer.exceptions")
    exceptions.MnamerException = type("MnamerException", (Exception,), {})
    settings_module = types.ModuleType("mnamer.setting_store")
    settings_module.SettingStore = types.SimpleNamespace
    sys.modules.update({"mnamer": package, "mnamer.exceptions": exceptions,
                        "mnamer.setting_store": settings_module})
    candidate = types.ModuleType("candidate_mnamer_daemon")
    sys.modules[candidate.__name__] = candidate
    exec(compile(source, str(out / "candidate_daemon.py"), "exec"), candidate.__dict__)

    results = []
    # Cross the two properties: duplicate source identity and a finite quota.
    for duplicate, quota in [(False, None), (False, 2), (True, None), (True, 2)]:
        with tempfile.TemporaryDirectory(prefix="mnamer-combination-") as temp:
            folder = Path(temp)
            watch, movies = folder / "Downloads", folder / "Movies"
            watch.mkdir()
            for n in range(5):
                (watch / f"movie.{n:02d}.mp4").write_bytes(b"x" * 10)
            settings = types.SimpleNamespace(
                daemon_state=folder / "state.json", watch=[str(watch)],
                targets=[watch] if duplicate else [], movie_directory=movies,
                daemon_config=None, batch_size=quota, dry_run=False,
                stability_checks=0, stability_interval_ms=0, notify_webhook=None,
            )
            daemon = candidate.Daemon(settings)
            scan = daemon._scan(daemon._resolve_watch_configs())
            candidate_names = [source.name for _, source in scan]
            daemon.run_once()
            moved = sorted(path.name for path in movies.glob("*.mp4"))
            expected = 5 if quota is None else quota
            results.append({"duplicate_watch_and_positional": duplicate,
                            "batch_size": quota, "scan": candidate_names,
                            "moved": moved, "expected_count": expected,
                            "actual_count": len(moved), "passed": len(moved) == expected})

    report = {
        "trial": TRIAL,
        "scope": "component replay; CLI parsing, stability polling and subprocess lifecycle are not replayed",
        "candidate_patch_sha256": hashlib.sha256((DEST / "model.patch").read_bytes()).hexdigest(),
        "extracted_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "substitutions": ["import-only mnamer package shell", "MnamerException class", "SimpleNamespace settings"],
        "results": results,
    }
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert [row["passed"] for row in results] == [True, True, True, False]


if __name__ == "__main__":
    main()
