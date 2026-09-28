"""Environment and queue fixes must remain independent of trial labels."""
import json
from pathlib import Path
import threading
from types import SimpleNamespace

from scripts.execute_relational_gap_v3 import python_source_environment
from scripts import run_relational_gap_batch_v3 as batch


def test_python_source_roots_follow_existing_layout_and_metadata(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "pyproject.toml").write_text('[tool.setuptools.package-dir]\n"" = "lib"\n"escape" = "../outside"\n')
    result = python_source_environment(tmp_path)
    assert result["repository_source_roots"] == [".", "lib", "src"]
    assert "/app:/app/lib:/app/src" in result["command"]
    assert "outside" not in result["command"]
    assert '${PYTHONPATH:-}' in result["command"]


def test_slow_execution_does_not_block_later_provider_requests(tmp_path, monkeypatch):
    cases = [f"toy{i}" for i in range(5)]
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps([{"id": case} for case in cases]))
    root, prefix = tmp_path / "batch", tmp_path / "output"
    for case in cases:
        (root / case).mkdir(parents=True)
        (root / case / "prepare.json").write_text("{}")
    all_requested, lock = threading.Event(), threading.Lock()
    requested, running, peak = set(), 0, 0

    def fake_run(command, **_):
        nonlocal running, peak
        stage = command[2]
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        if stage == "requests":
            with lock:
                requested.add(output.name)
                if len(requested) == len(cases):
                    all_requested.set()
        elif stage == "run":
            with lock:
                running += 1
                peak = max(peak, running)
            assert all_requested.wait(timeout=3), "Docker blocked later model preparation"
            with lock:
                running -= 1
        return SimpleNamespace(returncode=0, stdout="{}\n", stderr="")

    monkeypatch.setattr(batch.subprocess, "run", fake_run)
    monkeypatch.setattr(batch.sys, "argv", ["batch", "--batch-root", str(root), "--prefix", str(prefix),
                                          "--registry", str(registry), "--workers", "2"])
    batch.main()
    summary = json.loads(Path(str(prefix) + "_pipeline/summary.json").read_text())
    assert len(summary) == len(cases)
    assert all(row["status"] == "complete" for row in summary)
    assert peak <= 2
