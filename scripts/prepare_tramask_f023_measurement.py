"""Fixed-Q F023 measurement of actual version returns and original test values."""
import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.study import RUN, now, write_new
from tramask_rerun.reserved import load_cases
from tramask_rerun.workflow import public_packet
from tramask_rerun.variants import stage_hypothesis
from tramask_rerun.paired import execution_binding


HELPER = '''import collections
import json
import sys

_test = "outside_test"
_counts = collections.Counter()
_previous = None
_stream = None

def emit(channel, anchor, value):
    key = (_test, channel, anchor)
    _counts[key] += 1
    event = {"channel": channel, "anchor": anchor, "target_reached": True,
             "test": _test, "call": _counts[key], "value": value}
    _stream.write("TRAMASK_EVENT " + json.dumps(event, sort_keys=True, allow_nan=False) + "\\n")
    _stream.flush()

def _profile(frame, event, value):
    if event == "return" and frame.f_code.co_name == "_get_vulture_version" and frame.f_code.co_filename.endswith("/vulture/cache.py"):
        if type(value) is str:
            emit("effect", "vulture_version_return", value)
        else:
            _stream.write("TRAMASK_UNRESOLVED non-string version return\\n")
            _stream.flush()

def pytest_sessionstart(session):
    global _stream, _previous
    _previous = sys.getprofile()
    if _previous is not None:
        raise RuntimeError("existing profiler prevents independent observation")
    _stream = open("/tmp/tramask_f023_events.jsonl", "w", encoding="utf-8")
    sys.setprofile(_profile)

def pytest_runtest_setup(item):
    global _test
    _test = item.nodeid

def pytest_sessionfinish(session, exitstatus):
    sys.setprofile(_previous)
    if _stream is not None:
        _stream.close()
'''


if __name__ == "__main__":
    case = dict(next(c for c in load_cases() if c["id"] == "F023"))
    directory = RUN / "runs/F023"
    packet = public_packet(case)
    files = {**packet["final_sources"], **packet["selected_test"]["files"]}
    fixed_path = directory / "reference_canonical_v01/fixed_counterfactual.json"
    fixed = read(fixed_path)
    h = copy.deepcopy(fixed)
    test = "app/tests/test_cache.py"
    changes = [
        {"path": test, "old": "import pytest\n", "new": "import pytest\nimport tramask_measurement_probe as _tramask_probe\n"},
        {"path": test, "old": "    assert cached_unused == fresh_unused\n", "new": '    _tramask_probe.emit("observation", "cache_reuse_values", {"cached_unused": cached_unused, "fresh_unused": fresh_unused})\n    assert cached_unused == fresh_unused\n'},
        {"path": test, "old": '    assert meta["sha256"] == hashlib.sha256(content).hexdigest()\n', "new": '    _tramask_probe.emit("observation", "original_meta_sha256", meta["sha256"])\n    assert meta["sha256"] == hashlib.sha256(content).hexdigest()\n'},
    ]
    h["instrumentation"] = {
        "shared_anchors": [
            {"id": "vulture_version_return", "channel": "effect", "p_location": "_get_vulture_version return event", "q_location": "_get_vulture_version return event", "meaning": "Actual returned version string; Python profile callback does not reevaluate or replace the call."},
            {"id": "cache_reuse_values", "channel": "observation", "p_location": "before original cached_unused equality", "q_location": "before original cached_unused equality", "meaning": "Existing cached_unused and fresh_unused built-in tuples/lists of strings."},
            {"id": "original_meta_sha256", "channel": "observation", "p_location": "before original meta sha256 equality", "q_location": "before original meta sha256 equality", "meaning": "Already loaded raw meta digest; no repeated hashing and no path/time normalization."}],
        "common_edits": changes, "p_edits": [], "q_edits": [],
        "helper_files": [{"path": "app/tramask_measurement_probe.py", "content": HELPER}],
        "command": "python -m pytest -p tramask_measurement_probe tests/test_cache.py -q 2>&1 | tail -5",
        "noninterference": "Observer-only profile callback reads actual function-return arguments without calling the target again. Logging copies existing builtin strings/lists into separate measurement file, preserving capsys/coverage streams and every original assertion. Hooks supply test identity and per-anchor call IDs. Non-string returns are unresolved. Original tests and program run separately in P/Q controls; timing overhead remains measured."}
    compile(HELPER, "tramask_measurement_probe.py", "exec")
    out = directory / "measurement_reference_v01"
    write_new(out / "hypothesis.json", h)
    stage_hypothesis(files, h, out / "staging", source_origins={}, test_paths=[test])
    write_new(out / "technical_review.json", {"created_at": now(), "fixed_Q": receipt(fixed_path),
        "fixed_Q_preserved": h["alternative"] == fixed["alternative"], "investigator_authored_measurement": True,
        "original_model_probe_failure_retained": receipt(directory / "reference_canonical_v01/result.json"),
        "notes": h["instrumentation"]["noninterference"], "scientific_label": None})
    selected = read(directory / "selection.json")
    case["working_directory"] = selected["working_directory"]
    observations = ["/tmp/tramask_f023_events.jsonl"]
    b = execution_binding(case, files, h, source_origins={}, test_paths=[test], build_commands=[],
                          generated_runtime=False, observation_paths=observations, repeats=3)
    execution = directory / "measurement_execution_v01"
    inputs = {"case": case, "source_files": files, "hypothesis": h, "source_origins": {}, "test_paths": [test],
              "build_commands": [], "generated_runtime": False, "observation_paths": observations,
              "bound_artifacts": [receipt(fixed_path), receipt(out / "hypothesis.json"), receipt(out / "technical_review.json"),
                                  receipt(ROOT / "src/tramask_rerun/paired.py"), receipt(ROOT / "src/tramask_rerun/runtime.py")]}
    write_new(execution / "inputs.json", inputs)
    write_new(execution / "execution_review.json", {"approved_for_execution": True, "reviewer_id": "root-technical-measurement-review-v01",
        "binding": b, "rationale": h["instrumentation"]["noninterference"], "scientific_label": None})
    print("F023 fixed-Q measurement staged and bound")
