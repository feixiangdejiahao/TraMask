"""Parse executed testcase outcomes without treating compilation errors as bugs."""
from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET


def _pytest(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    rows = []
    for case in root.iter("testcase"):
        test_id = "::".join(filter(None, [case.get("classname"), case.get("name")]))
        failure, error, skip = case.find("failure"), case.find("error"), case.find("skipped")
        node = error if error is not None else failure if failure is not None else skip
        status = "error" if error is not None else "fail" if failure is not None else "skip" if skip is not None else "pass"
        detail = "" if node is None else (node.get("message", "") + "\n" + (node.text or ""))
        kind = "assertion" if status == "fail" and ("AssertionError" in detail or "assert " in detail) else "test_failure" if status == "fail" else "setup_or_collection" if status == "error" else status
        rows.append({"id": test_id, "status": status, "kind": kind, "detail": detail})
    return rows


def _go(path: Path) -> list[dict]:
    outcomes, output = {}, {}
    for line in path.read_text().splitlines():
        if not line.lstrip().startswith("{"):
            continue
        event = json.loads(line)
        if not event.get("Test"):
            continue
        test_id = event.get("Package", "") + "::" + event["Test"]
        if "Output" in event:
            output.setdefault(test_id, []).append(event["Output"])
        if event.get("Action") in {"pass", "fail", "skip"}:
            outcomes[test_id] = event["Action"]
    # Parent failures aggregate subtests; retain leaves to avoid duplicate counts.
    return [{"id": key, "status": value, "kind": "test_failure" if value == "fail" else value,
             "detail": "".join(output.get(key, []))}
            for key, value in sorted(outcomes.items())
            if not any(other.startswith(key + "/") for other in outcomes)]


def _vitest(path: Path) -> list[dict]:
    report = json.loads(path.read_text())
    rows = []
    for suite in report.get("testResults", []):
        assertions = suite.get("assertionResults", [])
        if not assertions and suite.get("status") == "failed":
            rows.append({"id": suite.get("name", "unknown_suite"), "status": "error",
                         "kind": "setup_or_collection", "detail": suite.get("message", "")})
        for case in assertions:
            status = {"passed": "pass", "failed": "fail", "pending": "skip",
                      "skipped": "skip", "todo": "skip"}.get(case.get("status"), "error")
            detail = "\n".join(case.get("failureMessages", []))
            rows.append({"id": case.get("fullName") or " ".join(case.get("ancestorTitles", []) + [case["title"]]),
                         "status": status, "kind": "assertion" if status == "fail" and "AssertionError" in detail else "test_failure" if status == "fail" else status,
                         "detail": detail})
    return rows


def _jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        if "CC_RESULT " in line:
            line = line.split("CC_RESULT ", 1)[1]
        elif not line.startswith("{"):
            continue
        record = json.loads(line)
        if not isinstance(record, dict) or "id" not in record or "status" not in record:
            continue
        status = {"violation": "fail", "invalid": "error", "skipped": "skip"}.get(record["status"], record["status"])
        if status not in {"pass", "fail", "error", "skip"}:
            raise ValueError(f"Unknown generated test status: {status}")
        detail = str(record.get("details", record.get("detail", "")))
        kind = "runtime_failure" if status == "fail" and ("panic:" in detail or "Runtime Error:" in detail) else "assertion" if status == "fail" else "invalid_input_or_oracle" if status == "error" else status
        rows.append({**record, "reported_status": record["status"], "status": status, "kind": record.get("kind", kind)})
    return rows


def _selected_test_name(actual: str, selected_names: set[str]) -> bool:
    """Match only declared runtime IDs or standard parameter/subtest suffixes."""
    local = actual.rsplit("::", 1)[-1]
    return any(actual == name or local == name
               or actual.startswith(name + "[") or actual.startswith(name + "/")
               or local.startswith(name + "[") or local.startswith(name + "/")
               for name in selected_names)


def _deduplicate_unselected_skips(rows: list[dict], selected_names: set[str]) -> tuple[list[dict], list[dict]]:
    """Keep one unselected skip; never conceal selected, failed, or error rows."""
    groups = {}
    for row in rows:
        groups.setdefault(row["id"], []).append(row)
    removable = {name for name, group in groups.items()
                 if len(group) > 1 and not _selected_test_name(name, selected_names)
                 and all(row["status"] == "skip" for row in group)}
    retained, excluded, seen = [], [], set()
    for row in rows:
        if row["id"] in removable and row["id"] in seen:
            excluded.append(row)
        else:
            retained.append(row)
            seen.add(row["id"])
    return retained, excluded


def parse_report(output: Path, specification: dict, process: dict, *,
                 selected_names: list[str] | None = None) -> dict:
    """Global failures remain errors; optional selection only deduplicates irrelevant skips."""
    output = Path(output)
    rows = []
    errors = []
    path = output / specification["path"]
    if path.is_file():
        try:
            parser = {"pytest-junit": _pytest, "go-json": _go,
                      "vitest-json": _vitest, "jsonl": _jsonl}[specification["format"]]
            rows = parser(path)
        except (OSError, ValueError, KeyError, ET.ParseError) as exc:
            errors.append(f"Malformed test report: {exc}")
    else:
        errors.append("Test report missing")
    excluded = []
    if selected_names is not None:
        rows, excluded = _deduplicate_unselected_skips(rows, set(selected_names))
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        errors.append("Duplicate testcase IDs in test report")
    if process.get("error"):
        errors.append(f"{process.get('stage')}: {process['error']}")
    if not rows:
        errors.append("No executed testcase outcomes")
    exit_code = process.get("returncode")
    if specification["format"] == "pytest-junit" and exit_code in (2, 3, 4, 5):
        errors.append(f"Pytest collection/harness exit {exit_code}")
    if exit_code not in (0, None) and not any(row["status"] in {"fail", "error"} for row in rows):
        errors.append(f"Nonzero command exit {exit_code} without a failing testcase")
    if exit_code is None and not process.get("error"):
        errors.append("Missing command exit code")
    counts = {state: sum(row["status"] == state for row in rows) for state in ("pass", "fail", "error", "skip")}
    status = "error" if errors or counts["error"] else "fail" if counts["fail"] else "pass" if counts["pass"] else "inconclusive"
    result = {"status": status, "counts": counts, "tests": rows, "errors": errors}
    if selected_names is not None:
        result["selection_parse"] = {
            "selected_names": sorted(set(selected_names)),
            "excluded_unselected_skipped_duplicates": excluded,
        }
    return result
