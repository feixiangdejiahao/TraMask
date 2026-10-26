"""Source-view regression tests; no provider or subject execution."""
import copy
import json
from pathlib import Path

import pytest

from tramask_rerun import prompts as frozen
from tramask_rerun import prompts_context_v02 as revised


def synthetic(sources, edits, *, target="app/a.py", patch="", anchor="missing"):
    test = {"id": "original", "command": "python /tmp/check.py",
            "files": {"tmp/check.py": "assert True\n"}}
    return {"id": "synthetic", "issue": "Preserve the target behavior.",
            "final_patch": patch, "selected_test": test, "validation_tests": [test],
            "target": {"source_path": target, "anchor": anchor, "behavior": "original operation",
                       "logical_effect": "original result", "public_observation": "original check"},
            "alternative": {"kind": "targeted_mutation", "edits": edits},
            "final_sources": sources, "actions": []}


def material(request):
    assert request["dispatchable"], request.get("reason")
    return json.loads(request["prompt"])["material"]


def assert_exact_nonoverlapping_views(packet, views):
    assert revised._size(views) <= 10_000
    for name, pieces in views.items():
        raw = packet["final_sources"][name].encode()
        assert pieces == sorted(pieces, key=lambda x: x["start_byte"])
        assert all(a["end_byte"] <= b["start_byte"] for a, b in zip(pieces, pieces[1:]))
        for piece in pieces:
            assert raw[piece["start_byte"]:piece["end_byte"]].decode() == piece["text"]
    for edit in packet["alternative"]["edits"]:
        assert sum(edit["old"] in piece["text"] for piece in views[edit["path"]]) == 1


def test_large_optional_patch_cannot_enlarge_small_required_neighborhood():
    lines = [f"# optional line {i:03d} " + "x" * 90 + "\n" for i in range(220)]
    lines[100] = "value = original_target()\n"
    packet = synthetic({"app/a.py": "".join(lines)},
        [{"path": "app/a.py", "old": lines[100], "new": "value = changed_target()\n"}],
        patch="diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1,220 +1,220 @@\n+changed\n")
    old = frozen.build_context_request(packet, "C2", 1)
    assert not old["dispatchable"]
    assert old["reason"] == "required_q_source_neighborhood_exceeds_quota"
    request = revised.build_context_request(packet, "C2", 1)
    views = material(request)["local_sources"]
    assert_exact_nonoverlapping_views(packet, views)
    assert "# optional line 096" in views["app/a.py"][0]["text"]
    assert "# optional line 104" in views["app/a.py"][0]["text"]
    assert request["input_receipt"]["total_input_utf8_bytes"] <= 64_000


def test_later_required_file_is_reserved_before_earlier_optional_file():
    source_a = "def first_target():\n" + "# " + "x" * 7500 + "\n"
    source_b = "# " + "y" * 3500 + "\nkeep_b = 17\n"
    packet = synthetic({"app/a.py": source_a, "app/b.py": source_b},
        [{"path": "app/b.py", "old": "keep_b = 17", "new": "keep_b = 0"}])
    assert not frozen.build_context_request(packet, "C2", 1)["dispatchable"]
    views = material(revised.build_context_request(packet, "C2", 1))["local_sources"]
    assert "app/b.py" in views
    assert "app/a.py" not in views
    assert_exact_nonoverlapping_views(packet, views)


def test_genuinely_oversized_required_neighborhood_still_refuses():
    line = "value = " + repr("x" * 11_000) + "\n"
    packet = synthetic({"app/a.py": line},
        [{"path": "app/a.py", "old": line, "new": "value = None\n"}])
    request = revised.build_context_request(packet, "C2", 1)
    assert not request["dispatchable"]
    assert request["prompt"] == ""
    assert request["reason"] == "required_q_source_neighborhood_exceeds_quota"
    assert request["input_receipt"]["essential_material_truncated"] is False


def test_overlapping_required_neighborhoods_merge_without_duplicate_source():
    source = "one = 1\ntwo = 2\nthree = 3\nfour = 4\nfive = 5\n"
    packet = synthetic({"app/a.py": source}, [
        {"path": "app/a.py", "old": "two = 2", "new": "two = 0"},
        {"path": "app/a.py", "old": "four = 4", "new": "four = 0"}],
        anchor="one = 1")
    views = material(revised.build_context_request(packet, "C2", 1))["local_sources"]
    assert len(views["app/a.py"]) == 1
    assert views["app/a.py"][0]["text"] == source
    assert_exact_nonoverlapping_views(packet, views)


@pytest.fixture(scope="module")
def actual_hf012():
    root = Path(__file__).resolve().parents[2] / "results/behavioral_masking/20261023_tramask_evidence_n60_r01/runs/HF012"
    # Only frozen public material and actual raw diagnostics, never audit/reviewer answers.
    packet = json.loads((root / "target_generation/public_input.json").read_text())
    hypothesis = json.loads((root / "measurement_execution_v01/inputs.json").read_text())["hypothesis"]
    packet["target"] = copy.deepcopy(hypothesis["target"])
    packet["alternative"] = {"kind": hypothesis["alternative"]["kind"],
                             "edits": copy.deepcopy(hypothesis["alternative"]["edits"])}
    diagnoses = {v: json.loads((root / f"measurement_execution_v01/execution/repeat_01/{v}_instrumented/diagnosis.json").read_text())
                 for v in ("p", "q")}
    packet["before_effects"] = {v: diagnoses[v]["effects"] for v in diagnoses}
    packet["original_observations"] = {v: diagnoses[v]["observations"] for v in diagnoses}
    return packet


def test_actual_hf012_all_twelve_requests_keep_exact_pair_and_common_source_views(actual_hf012):
    requests = {(c, r): revised.build_context_request(actual_hf012, c, r)
                for c in ("C1", "C2", "C3", "C4", "M1", "M2") for r in (1, 2)}
    source_views, tests = [], []
    for (condition, repeat), request in requests.items():
        value = material(request)
        assert request["input_receipt"]["total_input_utf8_bytes"] <= request["input_receipt"]["input_utf8_cap"]
        assert request["input_receipt"]["input_utf8_cap"] == 64_000
        assert value["target"] == actual_hf012["target"]
        assert value["alternative"] == actual_hf012["alternative"]
        tests.append(value["selected_test"])
        if condition != "C1":
            views = value["local_sources"]
            source_views.append(views)
            assert_exact_nonoverlapping_views(actual_hf012, views)
        else:
            assert "local_sources" not in value
        if condition in ("M1", "M2"):
            assert "before_effects" not in value and "original_observations" not in value
        else:
            assert value["before_effects"] == actual_hf012["before_effects"]
            assert value["original_observations"] == actual_hf012["original_observations"]
    assert all(x == source_views[0] for x in source_views)
    assert all(x == tests[0] for x in tests)
    assert requests[("C2", 1)]["prompt"] == requests[("C2", 2)]["prompt"]
    assert requests[("C2", 1)]["id"] != requests[("C2", 2)]["id"]


def test_actual_hf012_chronology_preserves_event_multiset_and_shared_arms(actual_hf012):
    for repeat in (1, 2):
        c3 = revised.build_context_request(actual_hf012, "C3", repeat)
        c4 = revised.build_context_request(actual_hf012, "C4", repeat)
        left, right = material(c3), material(c4)
        a, b = left.pop("actions"), right.pop("actions")
        assert len(a) > 1
        assert a != b
        assert sorted(json.dumps(x, sort_keys=True) for x in a) == sorted(json.dumps(x, sort_keys=True) for x in b)
        assert left == right
        assert all(set(event) == {"ref", "command", "output"} for event in a + b)
        for method, condition in (("M3", "C2"), ("M4", "C3")):
            alias = revised.build_context_request(actual_hf012, method, repeat)
            common = revised.build_context_request(actual_hf012, condition, repeat)
            assert alias["system"] == common["system"]
            assert alias["prompt"] == common["prompt"]
            assert alias["max_tokens"] == common["max_tokens"]


def test_original_quotas_are_unchanged():
    for name in ("SOURCE_BYTES", "MAX_PROMPT_UTF8_BYTES", "LARGE_ESSENTIAL_PROMPT_UTF8_BYTES", "HISTORY_BYTES", "PATCH_BYTES", "MAX_OUTPUT_TOKENS"):
        assert getattr(revised, name) == getattr(frozen, name)
