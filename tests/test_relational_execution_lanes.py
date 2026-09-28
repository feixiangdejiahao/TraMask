from copy import deepcopy

import pytest

from scripts.relational_execution_lanes import execution_lanes


def candidate(identifier="one"):
    return {"id": identifier, "base_test_id": "tests.py:1:test_one", "source_test_ids": [],
            "imports": [], "edits": [{"before": "1", "after": "2", "span": {"start_byte": 20, "end_byte": 21}}],
            "oracle": {"mode": "retain_all", "applicability": "unknown"}}


def request(rows):
    return {"id": "request", "candidate_records": rows}


def test_model_cannot_delete_offered_witness():
    source = candidate()
    rows, ledger = execution_lanes([request([source])], [{"accepted": []}], [source])
    assert len(rows) == 1
    assert rows[0]["edits"] == source["edits"]
    assert rows[0]["execution_lane"] == "source_q"
    assert rows[0]["oracle"]["applicability"].startswith("unknown")
    assert ledger["source_q_count"] == 1 and ledger["llm_q_count"] == 0


def test_local_expected_revision_is_distinct_unknown_hypothesis():
    source = candidate()
    revised = deepcopy(source)
    revised["edits"].append({"role": "semantic_expected", "before": "3", "after": "4", "span": {"start_byte": 50, "end_byte": 51}})
    revised["semantic_admission"] = {"status": "model_admitted"}
    rows, ledger = execution_lanes([request([source])], [{"accepted": [revised]}], [source])
    assert [r["execution_lane"] for r in rows] == ["source_q", "llm_q"]
    assert rows[0]["edits"] == source["edits"]
    assert rows[1]["id"] != source["id"]
    assert rows[1]["static_parent_id"] == rows[1]["parent_candidate_id"] == source["id"]
    assert "semantic_admission" not in rows[1]
    assert rows[1]["oracle"]["applicability"].startswith("unknown")
    assert ledger["same_execution_budget_as_v4"] is False


def test_retained_q_reuses_source_lane():
    source = candidate()
    rows, ledger = execution_lanes([request([source])], [{"accepted": [source]}], [source])
    assert len(rows) == 1
    assert ledger["candidates"][0]["status"] == "model_retained_same_q_reuses_source_execution"


def test_provider_failure_still_keeps_all_offered_sources():
    originals = [candidate(str(index)) for index in range(128)]
    requests = [request(originals[:64]), request(originals[64:])]
    rows, _ = execution_lanes(requests, [], originals)
    assert len(rows) == 128
    assert [row["id"] for row in rows] == [row["id"] for row in originals]


def test_model_input_change_or_unoffered_candidate_cannot_remove_source():
    source = candidate()
    revised = deepcopy(source)
    revised["edits"][0]["after"] = "99"
    for model_row in [revised, candidate("other")]:
        rows, ledger = execution_lanes([request([source])], [{"accepted": [model_row]}], [source])
        assert len(rows) == 1 and rows[0]["execution_lane"] == "source_q"
        assert ledger["model_lane_errors"]


def test_malformed_validation_and_excess_model_rows_keep_sources():
    source = candidate()
    for validations in [[None], [{"accepted": [None]}], [{"accepted": [source] * 33}], [{}, {}, {}]]:
        rows, ledger = execution_lanes([request([source])], validations, [source])
        assert len(rows) == 1 and ledger["model_lane_errors"]


def test_stale_request_source_and_excess_budget_rejected():
    source = candidate()
    stale = deepcopy(source)
    stale["edits"][0]["after"] = "changed"
    with pytest.raises(ValueError, match="frozen preparation"):
        execution_lanes([request([stale])], [], [source])
    with pytest.raises(ValueError, match="64 offered"):
        execution_lanes([request([candidate(str(i)) for i in range(65)])], [], [])


def test_emitted_lanes_isolate_expected_revisions_and_keep_whole_control(tmp_path):
    import hashlib
    import json
    from types import SimpleNamespace
    from generic_composition.corpus import build_corpus
    from scripts.execute_relational_gap_v5 import emit_batch

    repository = tmp_path / "repository"
    repository.mkdir()
    code = "def test_twice():\n    value = 1 * 2\n    assert value == 2\n"
    (repository / "test_toy.py").write_text(code)
    corpus = build_corpus(repository, "python")
    test_id = next(iter(corpus["tests"]))
    source = candidate()
    source["base_test_id"] = test_id
    offset = code.index("1 * 2")
    source["edits"] = [{"before": "1", "after": "2", "span": {"path": "test_toy.py", "start_byte": offset, "end_byte": offset + 1}}]
    revised = deepcopy(source)
    expected_offset = code.rindex("2")
    revised["edits"].append({"role": "semantic_expected", "before": "2", "after": "4", "span": {"path": "test_toy.py", "start_byte": expected_offset, "end_byte": expected_offset + 1}})
    prepared, semantic, completion, output = [tmp_path / name for name in ("prepared", "semantic", "completion", "output")]
    for path in (prepared, semantic, completion):
        path.mkdir()
    def dump(path, value):
        path.write_text(json.dumps(value))
    for name, value in {"corpus.json": corpus, "selection.json": {}, "candidates.json": {"candidates": [source]},
                        "case.json": {"id": "toy", "repository": str(repository), "language": "python"}}.items():
        dump(prepared / name, value)
    dump(prepared / "prepare.json", {"files_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in prepared.iterdir()}})
    dump(semantic / "protocol.json", {"input": str(prepared)})
    dump(semantic / "request_0.json", request([source]))
    dump(completion / "validation.json", {"accepted": [revised]})
    result = emit_batch(SimpleNamespace(input=prepared, output=output, semantics=semantic, completions=[completion], timeout=10))
    assert result["source_q"] == result["llm_q"] == 1
    artifacts = json.loads((output / "artifacts.json").read_text())
    assert len(artifacts) == 2
    for artifact in artifacts:
        from pathlib import Path
        folder = Path(artifact)
        manifest = json.loads((folder / "manifest.json").read_text())
        source_context, generated_context = {}, {}
        exec((folder / "control/files/test_toy.py").read_text(), source_context)
        exec((folder / "generated/files/test_toy.py").read_text(), generated_context)
        for control in manifest["controls"]:
            source_context[control["test_name"]]()
        test = manifest["obligations"][0]["test_name"]
        if manifest["execution_lane"] == "source_q":
            with pytest.raises(AssertionError):
                generated_context[test]()
        else:
            generated_context[test]()
    assert (repository / "test_toy.py").read_text() == code
