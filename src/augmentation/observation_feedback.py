"""Represent diagnostic execution as observations, not an assertion verdict."""
import hashlib
import json
import re


def without_framework_banners(text):
    rows = []
    for line in text.splitlines():
        if re.match(r"^\s*(?:===\s+(?:RUN|PAUSE|CONT)\b|---\s+(?:PASS|FAIL|SKIP):|(?:PASS|FAIL)\s*$|ok\s+\S+\s+\d)", line):
            continue
        rows.append(line)
    return "\n".join(rows).strip()


def observation_view(feedback):
    if not isinstance(feedback, dict): return feedback
    result = {}
    for key, original in feedback.items():
        observations = []
        for test in original.get("tests", []):
            text = without_framework_banners(test.get("detail", ""))
            if text:
                observations.append({"source": "test_output", "test_id": test["id"], "text": text})
        for name in ["stdout.txt", "stderr.txt"]:
            text = without_framework_banners(original.get("logs", {}).get(name, ""))
            if text: observations.append({"source": name, "text": text})
        issues = list(original.get("errors", []))
        if original.get("error"): issues.append(original["error"])
        for test in original.get("tests", []):
            if test.get("status") in {"fail", "error"}:
                issues.append({"test_id": test["id"], "kind": test.get("kind"), "detail": without_framework_banners(test.get("detail", ""))})
        result[key] = {"execution_completed": original.get("process", {}).get("stage") == "finished",
                       "process_returncode": original.get("process", {}).get("returncode"),
                       "observations": observations, "execution_issues": issues,
                       "semantic_verdict": "The runner has not checked the target requirement. A diagnostic probe that only logs values can complete successfully while revealing the predicted defect. Compare the observed values with the independently justified target, not with the framework's completion label.",
                       "original_feedback_sha256": hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()}
    return result
