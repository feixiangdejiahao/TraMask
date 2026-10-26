import pytest

from tramask_pilot.context_candidates import merge_measurement


def test_setup_edit_and_later_probe_are_both_preserved(tmp_path):
    base = "setup = 1\nprepare()\nrun()\nassert result\n"
    candidate = base.replace("setup = 1", "setup = 2")
    measured = base.replace("assert result", "observe(result)\nassert result")
    merged = merge_measurement(candidate, base, measured, tmp_path)
    assert merged == "setup = 2\nprepare()\nrun()\nobserve(result)\nassert result\n"


def test_conflicting_candidate_cannot_silently_drop_probe(tmp_path):
    with pytest.raises(ValueError, match="merge_conflict"):
        merge_measurement("setup = 2\n", "setup = 1\n", "setup = 3\n", tmp_path)
