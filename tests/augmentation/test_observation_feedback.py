from augmentation.observation_feedback import observation_view


def test_completed_logging_probe_keeps_distinguishing_values():
    raw = {"h1": {"status": "pass", "process": {"stage": "finished", "returncode": 0},
                  "tests": [{"id": "TestCCPilot", "status": "pass", "detail": "=== RUN   TestCCPilot\n    a.go:3: inc=3 get=2\n--- PASS: TestCCPilot (0.00s)\n"}], "logs": {}}}
    r = observation_view(raw)["h1"]
    assert r["execution_completed"]
    assert r["observations"][0]["text"] == "a.go:3: inc=3 get=2"
    assert "status" not in r
    assert raw["h1"]["status"] == "pass"


def test_failed_setup_remains_visible():
    r = observation_view({"h1": {"status": "error", "process": {"stage": "finished", "returncode": 2},
         "tests": [], "errors": ["collection failed"], "logs": {"stderr.txt": "ImportError: unavailable"}}})["h1"]
    assert r["execution_issues"] == ["collection failed"]
    assert r["process_returncode"] == 2
    assert r["observations"][0]["text"] == "ImportError: unavailable"
