import json

import pytest

from tramask_pilot.hypotheses import parse_events


def test_merged_pytest_progress_retains_actual_event_without_parsing_source_echo():
    event = {"channel": "effect", "anchor": "actual_return", "target_reached": True,
             "value": ["a", "b"]}
    line = "TRAMASK_EVENT " + json.dumps(event)
    assert parse_events("....." + line + "\nassert log == '" + line + "'\n") == [event]
    with pytest.raises(ValueError, match="malformed_tramask_event"):
        parse_events("..TRAMASK_EVENT {broken}")
