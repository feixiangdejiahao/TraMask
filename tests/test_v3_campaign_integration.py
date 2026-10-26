"""Offline integration checks using source-only toy programs and stub workers."""
import copy
import json
import sys
import types
from threading import Lock
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relation_search.checkpoint import read, write
from relation_search.instrument import instrument_candidates
from relation_search.oracle import prepare_requests, validate
from prototypes.oracle_batch_recovery import plan_recovery, validate_frozen_request
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts import run_relation_campaign as campaign_module


def source_candidate():
    path = "test_combination.py"
    code = """def combine(first, second):
    return first + second

def test_values():
    first = 3
    second = 4
    result = combine(first, second)
    assert result == 7
"""
    frontend = extract_frontend([Source(path, code, "python")])
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus["tests"]))
    start = code.index("3", corpus["tests"][test_id]["span"]["start_byte"])
    qstart = code.index("assert result == 7")
    item = dict(id="changed_input", base_test_id=test_id, language="python", imports=[],
        source_test_ids=[], operator="input_change", edits=[dict(before="3", after="9", role="input",
            span=dict(path=path, start_byte=start, end_byte=start+1))],
        runtime_probes=[dict(phase="before_assertion", insert_before=dict(
            path=path, start_byte=qstart, end_byte=qstart+len("assert result == 7")),
            roles=[dict(name="result", expression="result")])])
    instrumented = next(row for row in instrument_candidates(corpus, [item])["candidates"]
                        if row["id"] == item["id"])
    return corpus, frontend, item, instrumented


def test_dependency_prompt_uses_source_edits_and_keeps_probe_overlapped_assertion():
    corpus, frontend, original, instrumented = source_candidate()
    request = prepare_requests(corpus, frontend, [instrumented], "Return the sum.",
                               evidence_mode="dependency", per_request=1)[0]
    wire = json.loads(request["prompt"])["candidates"][0]
    assert wire["input_changes"] == [dict(before="3", after="9")]
    assert "first = 9" in wire["modified_test"]
    assert "assert result == 7" in wire["modified_test"]
    assert len(wire["assertions"]) == 1
    assert wire["assertions"][0]["observed"] == "result"
    assert "rs_probe" not in wire["modified_test"]
    assert "__rs" not in wire["modified_test"]
    # Validation retains the real execution candidate, not a probe-free clone.
    assert request["offered"]["C0"]["candidate"] == instrumented
    before = prepare_requests(corpus, frontend, [original], "Return the sum.",
                              evidence_mode="dependency", per_request=1)[0]
    assert json.loads(before["prompt"])["candidates"][0] == wire


def test_dependency_batch_recovery_preserves_probe_free_evidence_and_execution_candidates():
    corpus, frontend, original, first = source_candidate()
    alternate = copy.deepcopy(original)
    alternate["id"] = "another_input"
    alternate["edits"][0]["after"] = "12"
    second = next(row for row in instrument_candidates(corpus, [alternate])["candidates"]
                  if row["id"] == alternate["id"])
    parent = prepare_requests(corpus, frontend, [first, second], "Return the sum.",
                              evidence_mode="dependency", per_request=2)[0]
    payload = validate_frozen_request(parent)
    plan = plan_recovery(parent, dict(request_id=parent["id"], status="complete", finish_reason="length"), "")
    assert len(plan["requests"]) == 2
    for old_alias, child, wire in zip(["C0", "C1"], plan["requests"], payload["candidates"]):
        child_wire = validate_frozen_request(child)["candidates"][0]
        assert child["evidence_mode"] == "dependency" and child["system"] == parent["system"]
        assert child["offered"]["C0"] == parent["offered"][old_alias]
        assert child_wire["dependency_evidence"] == wire["dependency_evidence"]
        assert child_wire["modified_test"] == wire["modified_test"]
        assert len(child_wire["input_changes"]) == 1


def test_dependency_revision_at_probe_boundary_survives_validation_and_execution(tmp_path, monkeypatch):
    from generic_composition.emitter import emit
    corpus, frontend, _, item = source_candidate()
    request = prepare_requests(corpus, frontend, [item], "Return the sum.",
                               evidence_mode="dependency", per_request=1)[0]
    result = validate(request, dict(revisions=[dict(candidate="C0", basis="9 + 4 = 13",
        updates=[dict(assertion="A0", code="assert result == 13")])]), corpus)
    assert len(result["revisions"]) == 1, result["decisions"]
    revision = result["revisions"][0]
    instrumented = instrument_candidates(corpus, [revision])
    for helper in instrumented["helper_files"]:
        module = types.ModuleType(helper["path"].removesuffix(".py"))
        exec(helper["code"], module.__dict__)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("COMBINATION_REPORT_DIR", str(tmp_path))
    emitted = emit(corpus, instrumented["candidates"])
    assert not emitted["unsupported"]
    namespace = {}
    exec(compile(emitted["files"]["test_combination.py"], "<toy>", "exec"), namespace)
    generated = next(row for row in emitted["obligations"] if row["candidate_id"] == revision["id"])
    namespace[generated["test_name"]]()
    events = [json.loads(line) for line in (tmp_path/"relation_trace.jsonl").read_text().splitlines()]
    assert len(events) == 1 and events[0]["candidate_id"] == revision["id"]


def prepare_semantic_fixture(tmp_path):
    corpus, frontend, _, item = source_candidate()
    prepared = tmp_path / "prepared"
    write(prepared/"corpus.json", corpus)
    write(prepared/"frontend.json", frontend)
    write(prepared/"candidates.json", dict(candidates=[item]))
    write(prepared/"case.json", dict(id="unlabelled_toy"))
    write(prepared/"prepare.json", dict(selected=1, source_identity="toy"))
    (prepared/"issue.md").write_text("The function returns its arguments' sum.")
    args = SimpleNamespace(oracle_mode="fresh", oracle_cache=None, semantic_budget=1,
        per_request=1, model_workers=1, semantic_policy="impact", oracle_evidence="dependency")
    return prepared, args


def test_impact_selection_evidence_reaches_real_semantic_prompt_and_resume_is_idempotent(tmp_path, monkeypatch):
    from scripts import relation_search_semantics
    prepared, args = prepare_semantic_fixture(tmp_path)
    calls = []

    def complete(local_args):
        request = read(local_args.input)
        calls.append(request)
        write(local_args.output/"manifest.json", dict(status="complete", external_model_calls=0,
                                                     request_id=request["id"], finish_reason="stop"))
        (local_args.output/"completion.txt").write_text('{"revisions":[]}')

    monkeypatch.setattr(relation_search_semantics, "complete", complete)
    monkeypatch.setattr(campaign_module, "code_identity", lambda: {"toy_algorithm": "frozen"})
    output = tmp_path / "semantic"
    first = campaign_module.semantic_batch(prepared, output, args, [])
    assert len(calls) == 1
    wire = json.loads(calls[0]["prompt"])["candidates"][0]
    # The full structured evidence is kept locally; prompt text carries its
    # deterministic rendered form once, without duplicating every declaration.
    evidence = calls[0]["analysis_evidence"]["C0"]
    obligations = evidence["original_observation_obligations"]
    assert obligations and obligations[0]["observed"] == "result"
    assert obligations[0]["path"]
    assert obligations[0]["actual_span"] and obligations[0]["expected_span"]
    assert "q="+obligations[0]["observation_id"] in wire["dependency_evidence"]["rendered"]
    assert "original_observation_obligations" not in wire["dependency_evidence"]
    frontier = read(output/"semantic_frontier.json")
    assert "impact_evidence" not in frontier["candidates"][0]
    assert campaign_module.semantic_batch(prepared, output, args, []) == first
    assert len(calls) == 1


def campaign_fixture(tmp_path):
    source, output = tmp_path/"source", tmp_path/"output"
    for name in ["amber", "blue", "green"]:
        write(source/name/"corpus.json", dict(language="python", sources={}, tests={}))
        write(source/name/"case.json", dict(id=name))
    return SimpleNamespace(source=source, output=output, cases=None, rounds=2, limit=8, pool=32,
        strategy="profile", max_edits=2, workers=1, group_size=4, timeout=5,
        include_baseline=False, writer_priority=False, oracle_mode="fresh", semantic_budget=2,
        semantic_policy="impact", oracle_evidence="dependency", per_request=1, model_workers=1,
        case_workers=2, case_schedule="round", oracle_cache=None,
        registry=tmp_path/"registry.json", dependency_packages_root=tmp_path/"packages")


def install_stages(monkeypatch):
    events, lock = [], Lock()
    executions = []

    def prepared(args):
        case = args.source.name
        index = int(args.output.parent.name.removeprefix("round_"))
        with lock:
            events.append(("prepare", case, index))
        if index:
            assert args.previous is not None and args.previous.is_file()
            assert read(args.previous)["profiles"] == [case+":0"]
        result = dict(selected=1)
        write(args.output/"prepare.json", result)
        return result

    def semantic(prepared, output, args, previous_selected, previous_semantic=None):
        case, index = output.parent.parent.name, int(output.parent.name.removeprefix("round_"))
        if index:
            assert previous_selected == [case+":0"]
            assert previous_semantic.parent.name == "round_000"
        else:
            assert previous_selected == [] and previous_semantic is None
        write(output/"semantic_frontier.json", dict(pending_ids=[]))
        return dict(previous_selected=[*previous_selected, case+":"+str(index)], revised_count=0)

    def emit(args):
        return dict(status="emitted")

    def run(args):
        marker = args.output/"runs.json"
        if not marker.exists():
            case, index = args.output.parent.parent.name, int(args.output.parent.name.removeprefix("round_"))
            with lock:
                executions.append((case, index))
            write(marker, dict(status="complete"))
        return read(marker)

    def feedback(args):
        case, index = args.output.parent.parent.name, int(args.output.parent.name.removeprefix("round_"))
        result = dict(profiles=[case+":"+str(index)])
        write(args.output, result)
        with lock:
            events.append(("feedback", case, index))
        return result

    monkeypatch.setattr(campaign_module, "code_identity", lambda: {})
    monkeypatch.setattr(campaign_module, "prepare", prepared)
    monkeypatch.setattr(campaign_module, "semantic_batch", semantic)
    monkeypatch.setattr(campaign_module, "emit_batch", emit)
    monkeypatch.setattr(campaign_module, "run", run)
    monkeypatch.setattr(campaign_module, "feedback", feedback)
    return events, executions


def test_round_major_barrier_case_state_and_completed_resume(tmp_path, monkeypatch):
    args = campaign_fixture(tmp_path)
    events, executions = install_stages(monkeypatch)
    campaign_module.campaign(args)
    names = {"amber", "blue", "green"}
    first_next_round = next(i for i, event in enumerate(events) if event[0] == "prepare" and event[2] == 1)
    assert {event[1] for event in events[:first_next_round] if event[0] == "feedback" and event[2] == 0} == names
    rows = read(args.output/"campaign.json")
    assert {row["case"] for row in rows} == names
    assert all(row["stopped_reason"] == "round_budget" and len(row["rounds"]) == 2 for row in rows)
    assert len(executions) == 6
    before = copy.deepcopy(rows)
    campaign_module.campaign(args)
    assert read(args.output/"campaign.json") == before
    assert len(executions) == 6


def test_one_case_exception_preserves_other_case_receipts_and_resume(tmp_path, monkeypatch):
    args = campaign_fixture(tmp_path)
    _, executions = install_stages(monkeypatch)
    original_feedback = campaign_module.feedback
    failed = False

    def interrupted_feedback(local_args):
        nonlocal failed
        if local_args.output.parent.parent.name == "blue" and not failed:
            failed = True
            raise ValueError("simulated interruption after execution")
        return original_feedback(local_args)

    monkeypatch.setattr(campaign_module, "feedback", interrupted_feedback)
    with pytest.raises(ValueError, match="simulated interruption"):
        campaign_module.campaign(args)
    receipt = read(args.output/"campaign.json")
    completed = {row["case"] for row in receipt if len(row["rounds"]) == 1}
    assert {"amber", "green"} <= completed
    assert all(row["rounds"][0]["round"] == 0 for row in receipt if row["rounds"])
    campaign_module.campaign(args)
    rows = read(args.output/"campaign.json")
    assert {row["case"] for row in rows} == {"amber", "blue", "green"}
    assert all(row["stopped_reason"] == "round_budget" and len(row["rounds"]) == 2 for row in rows)
    assert len(executions) == 6  # The completed blue execution is not repeated.
