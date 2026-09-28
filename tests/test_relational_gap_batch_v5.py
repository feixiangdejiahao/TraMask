"""Provider failures cannot suppress already offered source hypotheses."""
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import run_relational_gap_batch_v5 as batch


def test_decoder_process_failure_still_emits_and_runs_source_lane(tmp_path, monkeypatch):
    root, prefix = tmp_path / "prepared", tmp_path / "output"
    (root / "toy").mkdir(parents=True)
    (root / "toy/prepare.json").write_text("{}")
    registry = tmp_path / "registry.json"
    registry.write_text('[{"id": "toy"}]')
    stages = []

    def fake_run(command, **_):
        stage = command[2]
        stages.append(stage)
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        if stage == "requests":
            (output / "request_0.json").write_text("{}")
        if stage == "complete":
            return SimpleNamespace(returncode=1, stdout="", stderr="decoder failed")
        if stage == "emit":
            assert "--semantics" in command
            assert command[-1] == "--completions"
        return SimpleNamespace(returncode=0, stdout="{}\n", stderr="")

    monkeypatch.setattr(batch.subprocess, "run", fake_run)
    monkeypatch.setattr(batch.sys, "argv", ["batch", "--batch-root", str(root), "--prefix", str(prefix),
                                          "--registry", str(registry), "--workers", "1"])
    batch.main()
    assert stages == ["requests", "complete", "emit", "run"]
    ledger = Path(str(prefix) + "_pipeline")
    summary = json.loads((ledger / "toy/summary.json").read_text())
    assert summary["status"] == "complete"
    assert summary["stages"]["complete_0"]["status"] == "model_stage_error_source_lane_retained"
    assert (ledger / "toy/complete_0.stderr").read_text() == "decoder failed"
