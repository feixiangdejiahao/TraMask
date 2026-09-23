"""Exploratory low-thinking protocol for the unchanged independent LLM baseline.

Use the same prepare/generate/freeze/run arguments as run_llm_generation_baseline.
Only thinking.type=enabled and reasoning_effort=low differ in model requests.
Every stage must use this wrapper so cached requests are verified under the
same frozen protocol. No model request or subject execution occurs on import.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experimental import llm_baseline as baseline
from scripts import run_llm_generation_baseline as original

PROTOCOL = {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}


@contextmanager
def protocol_context():
    payload_before = baseline.request_payload
    hashes_before = original.baseline_hashes
    write_before = original.write_json

    def request_payload(shown):
        payload = payload_before(shown)
        payload.update(thinking={"type": "enabled"}, reasoning_effort="low")
        if len(baseline.encoded(payload)) > baseline.MAX_REQUEST_BYTES:
            raise ValueError("Frozen evidence exceeds request byte limit; no truncation")
        return payload

    def hashes():
        path = Path(__file__).resolve()
        return {**hashes_before(), str(path.relative_to(ROOT)): original.driver.digest(path)}

    def write_json(path, value):
        if Path(path).name in {"baseline_prepare.json", "prepare.json"}:
            value = {**value, "study_status": "exploratory_model_protocol_comparison",
                     "request_protocol": PROTOCOL,
                     "protocol_adapter_sha256": original.driver.digest(Path(__file__).resolve())}
        write_before(path, value)

    baseline.request_payload = request_payload
    original.baseline_hashes = hashes
    original.write_json = write_json
    try:
        yield
    finally:
        baseline.request_payload = payload_before
        original.baseline_hashes = hashes_before
        original.write_json = write_before


def prepare(args):
    with protocol_context():
        return original.prepare(args)


def generate(args):
    with protocol_context():
        return original.generate(args)


def freeze(args):
    with protocol_context():
        return original.freeze(args)


def run(args):
    with protocol_context():
        return original.run(args)


if __name__ == "__main__":
    with protocol_context():
        original.main()
