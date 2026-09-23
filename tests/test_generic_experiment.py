import argparse
import json
import sys
from types import SimpleNamespace

import pytest

from scripts import run_generic_experiment as cli


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    import anchor_retrieval.retrieve as retrieval
    import generic_composition.corpus as corpus
    import generic_composition.engine as engine
    repo = tmp_path / "repository"
    repo.mkdir()
    (repo / "test_a.py").write_text("def test_seed():\n    assert True\n")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps([{"id": "unseen", "language": "python", "repository": str(repo)}]))
    proposals = [{"id": "keep"}, {"id": "reject"}]
    calls = []
    monkeypatch.setattr(retrieval, "retrieve", lambda *args: {"selected_tests": [], "automatic": True})
    monkeypatch.setattr(corpus, "build_corpus", lambda *args, **kwargs: {"language": "python", "coverage": {"tests_processed": 1}})
    monkeypatch.setattr(engine, "generate", lambda *args: {"candidates": proposals, "counts": {"candidates": len(proposals)}})
    monkeypatch.setattr(engine, "gate_evidence", lambda c, g, issue: ({"issue": issue}, proposals))
    # Other agents may add implementation files during this unit test; its
    # isolated pipeline uses one stable source snapshot rather than live code.
    hashes = {"scripts/run_generic_experiment.py": cli.digest(cli.ROOT / "scripts/run_generic_experiment.py")}
    monkeypatch.setattr(cli, "algorithm_hashes", lambda: hashes)
    args = argparse.Namespace(registry=str(registry), case="unseen", case_root=None,
                              output=tmp_path / "experiment", retrieval=None, max_candidates=128,
                              max_files=400, top_k=10, cache_output=None, rerun_id="r1",
                              model="fixture-model", max_tokens=10000, direct_baseline=False, timeout=10)
    return args, calls, hashes


def test_prepare_is_local_and_admission_round_cannot_be_overwritten(experiment, monkeypatch):
    from generic_composition import gate
    args, calls, _ = experiment

    def request(evidence, candidates, output, **kwargs):
        calls.append({"evidence": evidence, "ids": [row["id"] for row in candidates]})
        output.mkdir(parents=True)
        return {"valid": True, "accepted": ["keep"], "external_model_calls": 1, "usage": {"prompt_tokens": 10}}

    monkeypatch.setattr(gate, "request_admission", request)
    cli.prepare(args)
    assert not calls
    assert json.loads((args.output / "prepare.json").read_text())["status"] == "complete"
    assert cli.admit(args)["accepted"] == 1
    with pytest.raises(FileExistsError):
        cli.admit(args)
    assert len(calls) == 1
    args.rerun_id = "r2"
    cli.admit(args)
    assert len(calls) == 2 and calls[0] == calls[1]
    summary = cli.summarize(args)
    assert summary["external_model_calls"] == 2
    assert [row["round"] for row in summary["admissions"]] == ["r1", "r2"]


def test_admission_rejects_code_or_prepared_data_drift(experiment, monkeypatch):
    args, _, hashes = experiment
    cli.prepare(args)
    monkeypatch.setattr(cli, "algorithm_hashes", lambda: {"different.py": "changed"})
    with pytest.raises(ValueError, match="Algorithm changed"):
        cli.admit(args)
    monkeypatch.setattr(cli, "algorithm_hashes", lambda: hashes)
    (args.output / "candidates.json").write_text("[]")
    with pytest.raises(ValueError, match="Prepared artifact changed"):
        cli.admit(args)


def test_direct_admission_api_rejects_unregistered_round_and_model(experiment):
    args, _, _ = experiment
    cli.prepare(args)
    args.rerun_id = "r3"
    with pytest.raises(ValueError, match="not preregistered"):
        cli.admit(args)
    args.rerun_id = "r1"
    args.model = "different-model"
    with pytest.raises(ValueError, match="differs from the frozen"):
        cli.admit(args)


def test_summary_counts_invalid_gate_manifest_even_without_inline_result(experiment):
    args, _, _ = experiment
    cli.prepare(args)
    cache = args.output / "cache"
    cli.write_json(cache / "manifest.json", {"valid": False, "external_model_calls": 1,
                                            "validation_error": "invalid JSON", "usage": {"completion_tokens": 5}})
    cli.write_json(args.output / "admission/r1.json", {"round": "r1", "status": "invalid", "cache": str(cache),
                                                     "model": args.model, "model_request_attempts": 1})
    result = cli.summarize(args)
    assert result["external_model_calls"] == 1
    assert result["admissions"][0]["usage"] == {"completion_tokens": 5}


def test_freeze_selects_only_admitted_ids_and_labels_direct_baseline(experiment, monkeypatch):
    from generic_composition import gate
    args, calls, _ = experiment
    cli.prepare(args)
    cache = args.output / "cache"
    cli.write_json(args.output / "admission/r1.json", {
        "cache": str(cache), "status": "complete", "prepare_sha256": cli.digest(args.output / "prepare.json")})
    monkeypatch.setattr(gate, "load_admission", lambda *args: {
        "accepted": ["keep"], "model": "fixture-model", "request_sha256": "request", "response_sha256": "response"})

    def emit(corpus, candidates):
        ids = [row["id"] for row in candidates]
        calls.append(ids)
        return {"files": {"test_a.py": "def test_gc_control_seed():\n    assert True\n"},
                "obligations": [{"id": "test_gc_" + name, "control_id": "test_gc_control_seed"} for name in ids],
                "controls": [{"id": "test_gc_control_seed"}], "unsupported": []}

    monkeypatch.setitem(sys.modules, "generic_composition.emitter", SimpleNamespace(emit=emit))
    result = cli.freeze(args)
    assert result["accepted"] == 1 and calls == [["keep"]]
    manifest = json.loads((args.output / "frozen/r1/manifest.json").read_text())
    assert manifest["metadata"]["semantic_admission"] is True
    assert " -k test_gc_" in manifest["command"]
    args.direct_baseline = True
    cli.freeze(args)
    assert calls[-1] == ["keep", "reject"]
    manifest = json.loads((args.output / "frozen/direct/manifest.json").read_text())
    assert manifest["metadata"]["direct_baseline"] is True
    with pytest.raises(FileExistsError):
        cli.freeze(args)


def test_production_context_enforces_byte_budgets_and_excludes_tests(tmp_path):
    for index in range(10):
        (tmp_path / f"module_{index}.py").write_text("# " + "中文" * 9000 + "\ndef f():\n    return 1\n")
    (tmp_path / "test_secret.py").write_text("SHOULD_NOT_APPEAR = 1")
    (tmp_path / "README.md").write_text("r" * 9000)
    context = cli.production_context(tmp_path, "python", "")
    assert context["included_source_bytes"] <= 64000
    assert all(row["included_bytes"] <= 12000 for row in context["files"])
    assert len(context["files"]) <= 8 and context["omitted"]
    assert "test_secret.py" not in [row["path"] for row in context["files"]]
    assert len(context["root_readme"]["text"].encode()) == 8000
    assert context["root_readme"]["truncated"]
    assert "not independent specifications" in context["interpretation"]


def test_large_patch_context_uses_changed_enclosing_function(tmp_path):
    (tmp_path / "module.py").write_text("# padding\n" * 2000 +
        'def contract():\n    """Sentinel public contract."""\n    return 1\n')
    (tmp_path / "other.py").write_text("SHOULD_NOT_APPEAR = 2\n")
    patch = "diff --git a/module.py b/module.py\n--- a/module.py\n+++ b/module.py\n@@ -2003 +2003 @@\n-    return 0\n+    return 1\n"
    context = cli.production_context(tmp_path, "python", patch)
    assert [row["path"] for row in context["files"]] == ["module.py"]
    assert context["files"][0]["mode"] == "changed_enclosing_functions"
    assert "Sentinel public contract" in context["files"][0]["snippets"][0]["code"]


def test_analogy_cli_prepares_and_freezes_joint_input_and_oracle_change(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'test_values.py').write_text('''def f(value):
    return [2 * x for x in value] if isinstance(value, list) else 2 * value

def test_a():
    assert f(3) == 6

def test_b():
    assert f([3]) == [6]

def test_c():
    assert f(5) == 10
''')
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps([{'id': 'toy', 'language': 'python', 'repository': str(repo)}]))
    hashes = {'scripts/run_generic_experiment.py': cli.digest(cli.ROOT / 'scripts/run_generic_experiment.py')}
    monkeypatch.setattr(cli, 'algorithm_hashes', lambda: hashes)
    args = argparse.Namespace(registry=str(registry), case='toy', case_root=None,
        output=tmp_path / 'out', retrieval=None, max_candidates=128, max_files=400,
        top_k=10, model='not-called', generator='analogy', rerun_id='r1',
        direct_baseline=True, timeout=10)
    cli.prepare(args)
    generated = json.loads((args.output / 'generated.json').read_text())
    wanted = [row for row in generated['candidates'] if 'f([5]) == [10]' in row['edits'][0]['after']]
    assert wanted and wanted[0]['oracle']['mode'] == 'transport_from_source'
    assert json.loads((args.output / 'prepare.json').read_text())['generator'] == 'analogy'
    cli.freeze(args)
    artifact = args.output / 'frozen/direct'
    manifest = json.loads((artifact / 'manifest.json').read_text())
    assert any(row['candidate_id'] == wanted[0]['id'] for row in manifest['metadata']['obligations'])
    assert manifest['metadata']['semantic_admission'] is False
    assert not (args.output / 'admission').exists()
