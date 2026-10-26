"""Public synthetic packets only; builders never call providers or Docker."""
import copy
import json

import pytest

from tramask_rerun import prompts_inventory_v02 as prompts


@pytest.fixture
def packet():
    test = {"id": "t1", "command": "python /tmp/check.py", "files": {
        "tmp/check.py": "from lib import route\nqueue = []\nroute(3, queue)\nassert queue == []\n"}}
    return {"id": "synthetic", "issue": "Messages over two hops must not be delivered.",
        "final_patch": "diff --git a/lib.py b/lib.py\n+++ b/lib.py\n@@ -1,2 +1,3 @@\n+    if hops > 2: return\n",
        "selected_test": test, "validation_tests": [test],
        "target": {"behavior": "hop guard", "source_path": "app/lib.py", "anchor": "def route",
                   "logical_effect": "attempted delivery", "public_observation": "queue contents"},
        "alternative": {"kind": "targeted_mutation", "edits": [
            {"path": "app/lib.py", "old": "    if hops > 2: return\n", "new": "    if False: return\n"}]},
        "final_sources": {"app/lib.py": "def route(hops, queue):\n    if hops > 2: return\n    return deliver(queue)\n"},
        "actions": [{"id": "s01", "step_id": 1, "timestamp": "SECRET_TIMESTAMP",
                     "command": "cat lib.py", "output": "first source event", "agent_message": "PRIVATE_REASONING"},
                    {"id": "s02", "command": "python /tmp/check.py", "output": "second execution event"},
                    {"id": "s03", "command": "cat /tmp/check.py", "output": "third test event"}],
        "before_effects": {"p": [{"anchor": "guard", "target_reached": True, "value": False}],
                           "q": [{"anchor": "guard", "target_reached": True, "value": True}]},
        "original_observations": {"p": [{"anchor": "queue", "value": []}], "q": [{"anchor": "queue", "value": []}]}}


def material(request):
    assert request["dispatchable"] and request["status"] == "prepared"
    return json.loads(request["prompt"])["material"]


def planning(packet):
    return {"status": "proposed", "selected_test_id": "t1", "original_command": "python /tmp/check.py",
            "target": copy.deepcopy(packet["target"]), "alternative": copy.deepcopy(packet["alternative"]),
            "instrumentation": {"command": "python /tmp/probe.py", "noninterference": "PROBE_MARKER",
                "shared_anchors": [], "common_edits": [], "p_edits": [], "q_edits": [], "helper_files": []}}


def test_context_visibility_matrix_and_shared_cells(packet):
    requests = {condition: prompts.build_context_request(packet, condition, 1)
                for condition in prompts.CONTEXT_CONDITIONS + prompts.METHODS}
    assert "local_sources" not in material(requests["test_patch"])
    assert "actions" not in material(requests["code"])
    assert "actions" not in material(requests["direct"])
    assert "actions" not in material(requests["two_flip_code"])
    assert material(requests["trajectory"])["actions"]
    assert material(requests["trajectory_direct"])["actions"]
    assert requests["code"]["prompt"] == requests["two_flip_code"]["prompt"]
    assert requests["code"]["system"] == requests["two_flip_code"]["system"]
    assert requests["trajectory"]["prompt"] == requests["two_flip_trajectory"]["prompt"]
    assert requests["code"]["id"] != requests["two_flip_code"]["id"]
    assert requests["two_flip_code"]["input_receipt"]["shared_condition"] == "code"
    assert "before_effects" not in material(requests["direct"])
    assert "alternative" in material(requests["direct"])  # Fixed target Track A supplies Q to every arm.


def test_chronology_ablation_same_content_fixed_shuffle_no_original_ids(packet):
    ordered = prompts.build_context_request(packet, "C3", 1)
    shuffled = prompts.build_context_request(packet, "C4", 1)
    left, right = material(ordered)["actions"], material(shuffled)["actions"]
    assert sorted(left, key=lambda e: e["ref"]) == sorted(right, key=lambda e: e["ref"])
    assert left != right
    assert right == material(prompts.build_context_request(packet, "C4", 2))["actions"]
    assert all(set(event) == {"ref", "command", "output"} for event in left)
    assert "SECRET_TIMESTAMP" not in shuffled["prompt"]
    assert "PRIVATE_REASONING" not in shuffled["prompt"]
    assert '"s01"' not in shuffled["prompt"]
    assert ordered["input_receipt"]["total_input_utf8_bytes"] == shuffled["input_receipt"]["total_input_utf8_bytes"]


def test_private_fields_and_hidden_events_never_serialized(packet):
    packet.update(gold={"edit": "GOLD_ANSWER"}, labels="OLD_LABEL", verifier="VERIFIER_TEXT",
                  reference_solution="REFERENCE_TEXT", failure_analysis="HUMAN_PROSE")
    packet["target"]["label"] = "TARGET_OLD_LABEL"
    packet["selected_test"]["review"] = "TEST_OLD_REVIEW"
    packet["alternative"]["gold"] = "Q_GOLD_ANSWER"
    packet["actions"] += [
        {"command": "cat hidden_tests/test_hidden.py", "output": "HIDDEN_RESULT"},
        {"command": "env DEEPSEEK_API_KEY=credential-secret run", "output": "SECRET_RESULT"},
        {"command": "python evaluator.py", "output": "EVALUATOR_RESULT"}]
    req = prompts.build_context_request(packet, "trajectory", 1)
    for token in ("GOLD_ANSWER", "OLD_LABEL", "VERIFIER_TEXT", "REFERENCE_TEXT", "HUMAN_PROSE",
                  "TEST_OLD_REVIEW", "HIDDEN_RESULT", "credential-secret", "SECRET_RESULT", "EVALUATOR_RESULT"):
        assert token not in req["prompt"]
    omissions = [r for r in req["input_receipt"]["sections"] if r.get("omitted") == "hidden_evaluator_or_credential_related"]
    assert len(omissions) == 3
    assert "credential-secret" not in json.dumps(req)


def test_cutoff_is_exclusive_and_stops_at_submission(packet):
    packet["actions"] += [{"command": "submit", "output": ""},
                           {"command": "cat lib.py", "output": "POST_SUBMISSION"}]
    req = prompts.build_context_request(packet, "trajectory", 1)
    assert len(material(req)["actions"]) == 3
    assert "POST_SUBMISSION" not in req["prompt"]
    packet["submission_event_index"] = 1
    assert len(material(prompts.build_context_request(packet, "trajectory", 1))["actions"]) == 1


def test_no_history_never_reads_action_fields(packet):
    packet["actions"] = "deliberately malformed and private"
    for condition in ("test_patch", "code", "direct", "two_flip_code"):
        assert "actions" not in material(prompts.build_context_request(packet, condition, 1))


def test_target_request_is_target_only_and_does_not_reuse_old_q(packet):
    packet["alternative"]["edits"][0]["new"] = "OLD_Q_CONTENT"
    packet["before_effects"] = {"p": [{"value": "OLD_RUN_EFFECT"}]}
    req = prompts.build_target_request(packet)
    assert "alternative" not in material(req)
    assert "before_effects" not in material(req)
    assert "OLD_Q_CONTENT" not in req["prompt"] and "OLD_RUN_EFFECT" not in req["prompt"]
    assert "TARGET-FLIP stage only" in req["system"]


@pytest.mark.parametrize("method,history", [("direct", False), ("trajectory_direct", True),
                                          ("two_flip_code", False), ("two_flip_trajectory", True)])
def test_track_b_stage1_self_localizes_without_pilot1_target_or_q(packet, method, history):
    packet["target"]["behavior"] = "PILOT1_TARGET"
    packet["alternative"]["edits"][0]["new"] = "PILOT1_Q"
    req = prompts.build_end_to_end_request(packet, method, 1, stage=1)
    data = material(req)
    assert "target" not in data and "alternative" not in data and "selected_test" not in data
    assert "validation_tests" in data and ("actions" in data) == history
    assert "PILOT1_TARGET" not in req["prompt"] and "PILOT1_Q" not in req["prompt"]
    assert "selected_test_id" in json.loads(req["prompt"])["output_schema"]


@pytest.mark.parametrize("method", ["direct", "trajectory_direct"])
def test_direct_stage2_cannot_see_q_probes_or_execution_feedback(packet, method):
    plan = planning(packet)
    plan["alternative"]["edits"][0]["new"] = "Q_SECRET_MARKER"
    feedback = {"before_effects": {"p": [{"value": "EXECUTION_SECRET"}]}, "labels": "VERDICT_SECRET"}
    req = prompts.build_end_to_end_request(packet, method, 2, 2, planning=plan, evidence=feedback)
    data = material(req)
    assert set(data) <= {"issue", "final_patch", "selected_test", "target", "local_sources", "actions"}
    for sentinel in ("Q_SECRET_MARKER", "PROBE_MARKER", "EXECUTION_SECRET", "VERDICT_SECRET"):
        assert sentinel not in req["prompt"]
    assert req["validation_context"]["edit_policy"] == "general_augmentation"


@pytest.mark.parametrize("method", ["two_flip_code", "two_flip_trajectory"])
def test_two_flip_stage2_gets_own_q_probe_and_measured_feedback_only(packet, method):
    feedback = {"before_effects": packet["before_effects"], "original_observations": packet["original_observations"],
                "confirmed_mask": "PRIVATE_VERDICT"}
    req = prompts.build_end_to_end_request(packet, method, 1, 2, planning=planning(packet), evidence=feedback)
    data = material(req)
    assert all(key in data for key in ("target", "alternative", "instrumentation", "before_effects", "original_observations"))
    assert "PRIVATE_VERDICT" not in req["prompt"]
    assert req["validation_context"]["edit_policy"] == "context_only"


def test_stage2_binding_to_original_test_and_command(packet):
    plan = planning(packet)
    plan["selected_test_id"] = "invented"
    with pytest.raises(ValueError, match="not_in_public_inputs"):
        prompts.build_end_to_end_request(packet, "direct", 1, 2, plan)
    plan["selected_test_id"] = "t1"
    plan["original_command"] = "invented replacement"
    with pytest.raises(ValueError, match="changed_original_command"):
        prompts.build_end_to_end_request(packet, "direct", 1, 2, plan)


def test_complete_essential_material_overflow_abstains_without_truncation(packet):
    packet["selected_test"]["files"]["tmp/check.py"] = "#" * 300_000
    req = prompts.build_context_request(packet, "test_patch", 1)
    assert req["status"] == "abstain" and not req["dispatchable"] and req["prompt"] == ""
    assert req["failure_stage"] == "pre_dispatch_material_construction"
    assert req["input_receipt"]["essential_material_truncated"] is False
    assert packet["selected_test"]["files"]["tmp/check.py"] == "#" * 300_000
    assert req["input_receipt"]["budget_tier"] == "large_essential"
    assert req["input_receipt"]["input_utf8_cap"] == 262_144


def test_complete_q_neighborhood_is_never_partially_cut(packet):
    old = "    "+"large_code_token " * 1000+"\n"
    packet["alternative"]["edits"][0]["old"] = old
    packet["final_sources"]["app/lib.py"] = "def route():\n" + old
    req = prompts.build_context_request(packet, "code", 1)
    assert req["status"] == "abstain" and "q_source_neighborhood" in req["reason"]


def test_inline_test_requires_exact_explicit_mapping(packet):
    script = "queue = []\nassert queue == []\n"
    command = "python - <<'PY'\n" + script + "PY"
    start = command.encode().index(script.encode())
    packet["selected_test"] = {"id": "inline", "command": command, "files": {}, "inline_test": {
        "path": "virtual/inline.py", "text": script,
        "command_mapping": {"original_command": command, "script_start_byte": start,
                            "script_end_byte": start + len(script.encode())}}}
    req = prompts.build_context_request(packet, "C1", 1)
    assert material(req)["selected_test"]["files"]["virtual/inline.py"] == script
    assert req["validation_context"]["original_command"] == command
    packet["selected_test"]["inline_test"]["command_mapping"]["script_end_byte"] -= 1
    with pytest.raises(ValueError, match="inline_script_mapping_mismatch"):
        prompts.build_context_request(packet, "C1", 1)


def test_whole_history_event_omission_and_receipts(packet):
    packet["actions"].append({"command": "cat lib.py", "output": "LARGE_EVENT" * 3000})
    req = prompts.build_context_request(packet, "trajectory", 1)
    assert "LARGE_EVENT" not in req["prompt"]
    assert any("whole_event" in r.get("omitted", "") for r in req["input_receipt"]["sections"])
    assert all("source_sha256" in r for r in req["input_receipt"]["sections"] if r.get("section") == "actions")


def test_source_excerpts_use_frozen_patch_ranges_and_preserve_offsets(packet):
    packet["final_sources"]["app/unrelated.py"] = "unused_line\n" * 5000
    req = prompts.build_context_request(packet, "code", 1)
    for path, chunks in material(req)["local_sources"].items():
        original = packet["final_sources"][path].encode()
        for chunk in chunks:
            assert original[chunk["start_byte"]:chunk["end_byte"]] == chunk["text"].encode()
    assert req["input_receipt"]["total_input_utf8_bytes"] <= 64_000


def test_physical_repeat_identity_and_stable_prompt_without_mutation(packet):
    before = copy.deepcopy(packet)
    a = prompts.build_context_request(packet, "C3", 1)
    b = prompts.build_context_request(packet, "C3", 2)
    assert a["id"] != b["id"] and a["prompt"] == b["prompt"]
    assert a["input_receipt"]["prompt_sha256"] == b["input_receipt"]["prompt_sha256"]
    assert packet == before
    with pytest.raises(ValueError, match="repeat_must"):
        prompts.build_context_request(packet, "C3", True)


def test_output_contract_distinguishes_model_abstention_from_format_failure(packet):
    target = prompts.build_target_request(packet)["validation_context"]["output_contract"]
    candidates = prompts.build_context_request(packet, "C2", 1)["validation_context"]["output_contract"]
    assert target["statuses"] == ["proposed", "insufficient_evidence"]
    assert target["malformed_response_is_insufficient_evidence"] is False
    assert candidates["slot_statuses"] == ["proposed", "no_proposal"]
    assert candidates["malformed_response_is_no_proposal"] is False
    assert candidates["exact_ranked_slots"] == [1, 2, 3, 4, 5]


def test_all_supplied_tool_events_are_citable_without_original_step_ids(packet):
    req = prompts.build_target_request(packet)
    data = json.loads(req["prompt"])
    for event in data["material"]["actions"]:
        assert event["ref"] in data["available_evidence_refs"]
        assert event["ref"].startswith("event:") and len(event["ref"]) == 70
    assert "content-SHA256" in req["system"]


def test_patch_budget_keeps_whole_hunks_and_original_byte_receipts(packet):
    unrelated = "diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n@@ -1 +1 @@\n-" + "x" * 20_000 + "\n+small\n"
    relevant = "diff --git a/lib.py b/lib.py\n--- a/lib.py\n+++ b/lib.py\n@@ -1,2 +1,3 @@\n+    if hops > 2: return\n"
    packet["final_patch"] = unrelated + relevant
    req = prompts.build_context_request(packet, "C1", 1)
    excerpt = material(req)["final_patch"]
    assert len(excerpt["pieces"]) == 1 and excerpt["pieces"][0]["path"] == "lib.py"
    piece = excerpt["pieces"][0]
    raw = packet["final_patch"].encode()
    assert raw[piece["header_start_byte"]:piece["header_end_byte"]] == piece["file_header"].encode()
    assert raw[piece["hunk_start_byte"]:piece["hunk_end_byte"]] == piece["hunk"].encode()
    assert piece["hunk"].startswith("@@")
    assert len(json.dumps(excerpt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) <= prompts.PATCH_BYTES
    assert any(r.get("omitted") == "whole_hunk_exceeds_remaining_fixed_patch_quota" for r in req["input_receipt"]["sections"])


def test_source_index_uses_original_patch_even_when_hunk_is_omitted(packet):
    packet.pop("target")
    packet["final_patch"] = "diff --git a/late.py b/late.py\n--- a/late.py\n+++ b/late.py\n@@ -400 +400 @@\n-" + "x" * 20_000 + "\n+fixed\n"
    packet["final_sources"] = {"app/late.py": "irrelevant\n" * 399 + "PATCH_NEIGHBORHOOD\n" + "irrelevant\n" * 100}
    req = prompts.build_target_request(packet)
    assert material(req)["final_patch"]["pieces"] == []
    assert any("PATCH_NEIGHBORHOOD" in c["text"] for c in material(req)["local_sources"]["app/late.py"])


def test_direct_planning_does_not_require_q_or_probe_and_flows_to_stage2(packet):
    request = prompts.build_end_to_end_request(packet, "direct", 1, 1)
    schema = json.loads(request["prompt"])["output_schema"]
    assert "alternative" not in schema and "instrumentation" not in schema
    assert schema["status"].startswith("planned_target")
    assert request["validation_context"]["output_contract"]["statuses"] == ["planned_target", "insufficient_evidence"]
    plan = {"status": "planned_target", "selected_test_id": "t1", "target": packet["target"],
            "original_command": packet["selected_test"]["command"]}
    second = prompts.build_end_to_end_request(packet, "direct", 1, 2, planning=plan)
    assert "alternative" not in material(second)
    with pytest.raises(ValueError, match="requires_proposed_planning"):
        prompts.build_end_to_end_request(packet, "two_flip_code", 1, 2, planning=plan)


def test_measurement_keeps_typed_identity_and_normalizes_aliases(packet):
    packet["before_effects"] = {"p": [{"channel": "effect", "anchor": "a", "test_id": "test",
        "call_id": 3, "input": {"hops": 3}, "invocation": [1, "x"], "value": False, "target_reached": True}]}
    event = material(prompts.build_context_request(packet, "C2", 1))["before_effects"]["p"][0]
    assert event["test"] == "test" and event["call"] == 3 and event["input"] == {"hops": 3}
    assert event["invocation"] == [1, "x"] and "test_id" not in event and "call_id" not in event
    packet["before_effects"]["p"][0]["call"] = True
    with pytest.raises(ValueError, match="conflicting_event_identity_alias"):
        prompts.build_context_request(packet, "C2", 1)


def large_python_packet(packet):
    source = ('import pytest\n\nCONSTANT = 3\n\ndef helper(value):\n    return value\n\n'
              'def test_unmodified():\n    text = "' + 'UNRELATED_BODY_' * 3000 + '"\n    assert text\n\n'
              'def test_selected_only():\n    assert helper(CONSTANT) == 3\n\n'
              '@pytest.mark.parametrize("value", [3])\ndef test_added(value):\n    assert helper(value) == 3\n')
    line = source[:source.index('@pytest.mark')].count('\n') + 1
    test = {"id": "large", "command": "pytest tmp/check.py", "files": {"tmp/check.py": source},
            "target_anchor": "test_selected_only"}
    packet["selected_test"] = test
    packet["validation_tests"] = [test]
    packet["final_patch"] = ("diff --git a/tmp/check.py b/tmp/check.py\n--- a/tmp/check.py\n+++ b/tmp/check.py\n"
                             f"@@ -{line},0 +{line},3 @@\n+@pytest.mark.parametrize(\"value\", [3])\n"
                             "+def test_added(value):\n+    assert helper(value) == 3\n")
    return source


def test_python_views_keep_complete_definitions_helpers_and_receipted_gaps(packet):
    original = large_python_packet(packet)
    req = prompts.build_target_request(packet)
    test = material(req)["selected_test"]
    assert test["files"] == {}
    view = test["file_excerpts"]["tmp/check.py"]
    selected = {row["name"] for row in view["definitions"]}
    assert selected == {"test_added", "test_selected_only"}
    shown = "\n".join(row["text"] for row in view["slices"])
    assert "def helper(value)" in shown and "@pytest.mark.parametrize" in shown
    assert "UNRELATED_BODY_" not in shown
    assert view["gaps"] and view["complete_file"] is False
    for chunk in view["slices"]:
        assert original.encode()[chunk["start_byte"]:chunk["end_byte"]] == chunk["text"].encode()
    for definition in view["definitions"]:
        assert any(chunk["start_byte"] <= definition["start_byte"] and chunk["end_byte"] >= definition["end_byte"] for chunk in view["slices"])
    receipt = next(x for x in req["input_receipt"]["sections"] if x["section"] == "test_file_excerpts")
    assert any(d["name"] == "test_unmodified" and not d["selected"] for d in receipt["all_definition_manifest"])
    assert req["validation_context"]["excerpt_file_hashes"]["tmp/check.py"] == view["original_sha256"]
    assert "tmp/check.py" in req["validation_context"]["editable_paths"]


def test_track_b_large_test_view_does_not_use_pilot1_anchor(packet):
    large_python_packet(packet)
    req = prompts.build_end_to_end_request(packet, "direct", 1, 1)
    view = material(req)["validation_tests"][0]["file_excerpts"]["tmp/check.py"]
    assert {row["name"] for row in view["definitions"]} == {"test_added"}
    assert "def test_selected_only" not in req["prompt"]


def test_changed_line_selection_does_not_treat_unchanged_hunk_context_as_authored(packet):
    patch = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,4 @@\n context\n+added\n context2\n context3\n"
    assert prompts._patch_changed_ranges(patch) == {"a.py": [(2, 1)]}


def test_typescript_views_keep_complete_test_and_scope_setup(packet):
    pytest.importorskip("tree_sitter_typescript")
    source = ('import {describe,it,expect,beforeEach} from "vitest";\n'
              'function helper(value:number){return value;}\n'
              'describe("group",()=>{\n const value=3;\n beforeEach(()=>helper(value));\n'
              ' it("unmodified",()=>{const text="' + 'UNRELATED_TS_' * 3000 + '";expect(text).toBeTruthy();});\n'
              ' it("added",()=>{expect(helper(value)).toBe(3);});\n});\n')
    line = source[:source.index(' it("added"')].count('\n') + 1
    test = {"id": "ts", "command": "vitest tmp/test.ts", "files": {"tmp/test.ts": source}}
    packet["selected_test"] = test
    packet["final_patch"] = ("diff --git a/tmp/test.ts b/tmp/test.ts\n--- a/tmp/test.ts\n+++ b/tmp/test.ts\n"
                             f"@@ -{line},0 +{line},1 @@\n+ it(\"added\",()=>{{expect(helper(value)).toBe(3);}});\n")
    req = prompts.build_target_request(packet)
    view = material(req)["selected_test"]["file_excerpts"]["tmp/test.ts"]
    assert {row["name"] for row in view["definitions"]} == {"added"}
    shown = "\n".join(row["text"] for row in view["slices"])
    assert "function helper" in shown and "const value=3" in shown and "beforeEach" in shown
    assert "UNRELATED_TS_" not in shown
    for definition in view["definitions"]:
        assert any(chunk["start_byte"] <= definition["start_byte"] and chunk["end_byte"] >= definition["end_byte"] for chunk in view["slices"])


def test_unsupported_typescript_parse_falls_back_to_whole_original_test(packet):
    packet["selected_test"]["files"] = {"tmp/test.ts": 'it("bad",()=>{ "' + "x" * 30_000}
    req = prompts.build_target_request(packet)
    assert req["status"] == "prepared" and req["input_receipt"]["budget_tier"] == "large_essential"
    assert material(req)["selected_test"]["files"] == packet["selected_test"]["files"]
    assert "file_excerpts" not in material(req)["selected_test"]
    diagnostics = req["input_receipt"]["budget_tier_eligibility"]["parser_diagnostics"]
    assert diagnostics["error_ranges"]
    assert diagnostics["grammars_attempted"] == ["typescript", "tsx"]


def test_typescript_error_in_unselected_test_does_not_discard_valid_selected_block(packet):
    source = ('import {it,expect} from "vitest";\nconst value=3;\n'
              'it("added",()=>{expect(value).toBe(3);});\n'
              'it("unrelated",()=>{const text="' + 'padding_' * 4000 + '";expect`\\uarr`;});\n')
    packet["selected_test"] = {"id": "ts", "command": "vitest tmp/test.ts", "files": {"tmp/test.ts": source}}
    packet["final_patch"] = ('diff --git a/tmp/test.ts b/tmp/test.ts\n--- a/tmp/test.ts\n+++ b/tmp/test.ts\n'
                             '@@ -3,0 +3,1 @@\n+it("added",()=>{expect(value).toBe(3);});\n')
    req = prompts.build_target_request(packet)
    view = material(req)["selected_test"]["file_excerpts"]["tmp/test.ts"]
    assert [d["name"] for d in view["definitions"]] == ["added"]
    shown = "\n".join(s["text"] for s in view["slices"])
    assert "const value=3" in shown and "padding_" not in shown
    receipt = next(r for r in req["input_receipt"]["sections"] if r["section"] == "test_file_excerpts")
    assert receipt["parser_diagnostics"]["root_has_error"]
    assert receipt["parser_diagnostics"]["error_ranges"]


def test_history_uses_only_remaining_budget_without_cutting_shared_material(packet):
    packet["issue"] = "contract " * 4500
    packet["actions"] = [{"command": "cat lib.py", "output": "event_content " * 350} for _ in range(8)]
    ordered = prompts.build_context_request(packet, "C3", 1)
    shuffled = prompts.build_context_request(packet, "C4", 1)
    a, b = material(ordered), material(shuffled)
    assert a["issue"] == packet["issue"] and a["selected_test"]["files"] == packet["selected_test"]["files"]
    assert sorted(a["actions"], key=lambda e:e["ref"]) == sorted(b["actions"], key=lambda e:e["ref"])
    assert ordered["input_receipt"]["total_input_utf8_bytes"] <= prompts.MAX_PROMPT_UTF8_BYTES


def test_large_essential_tier_is_shared_by_every_condition_without_results(packet):
    source = "# unchanged entire necessary test\n" + "#" * 100_000
    packet["selected_test"]["files"]["tmp/check.py"] = source
    requests = [prompts.build_context_request(packet, condition, 1) for condition in prompts.CONTEXT_CONDITIONS + prompts.METHODS]
    for req in requests:
        assert req["input_receipt"]["budget_tier"] == "large_essential"
        assert req["input_receipt"]["input_utf8_cap"] == 262_144
        assert material(req)["selected_test"]["files"]["tmp/check.py"] == source
        assert req["max_tokens"] == 8192
    assert len({req["input_receipt"]["budget_tier_eligibility"]["eligibility_test_inventory_sha256"] for req in requests}) == 1
    first_stages = [prompts.build_end_to_end_request(packet, method, 1, 1) for method in prompts.METHODS]
    assert all(req["input_receipt"]["budget_tier"] == "large_essential" for req in first_stages)


def test_working_directory_is_shared_public_test_material(packet):
    packet["selected_test"]["working_directory"] = "/tmp/fixture"
    for condition in prompts.CONTEXT_CONDITIONS + prompts.METHODS:
        assert material(prompts.build_context_request(packet, condition, 1))["selected_test"]["working_directory"] == "/tmp/fixture"
    packet["selected_test"]["working_directory"] = "/app/.aws"
    with pytest.raises(ValueError, match="private_path"):
        prompts.build_target_request(packet)
    packet["selected_test"]["working_directory"] = "/etc"
    with pytest.raises(ValueError, match="working_directory"):
        prompts.build_target_request(packet)
