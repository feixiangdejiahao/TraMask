"""Synthetic driver/cache checks: no real cases, provider calls or subjects."""
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from experimental.semantic_transport import model
from scripts import run_semantic_transport as transport


def synthetic_inputs(count=1):
    code = "def test_example():\n    assert result == 4\n"
    hole = code.index("4")
    span = {"path": "tests/test_example.py", "start_byte": 0, "end_byte": len(code)}
    corpus = {"language": "python", "sources": {span["path"]: {"code": code}},
              "tests": {"parent": {"span": span, "support": {"helpers": [], "imports": []}}},
              "coverage": {}}
    candidates = [{"id": f"hash-{index}", "candidate_id": f"hash-{index}",
                   "language": "python", "base_test_id": "parent", "source_test_ids": ["parent"],
                   "expected_span": {**span, "start_byte": hole, "end_byte": hole + 1},
                   "preview_body": "assert result == 4", "pre": [4], "arg": [2],
                   "observations": [{"text": "result", "predicate": "==",
                                     "expected_source": {"kind": "literal"}}]}
                  for index in range(count)]
    pending = {"candidates": candidates, "shown_ids": [row["id"] for row in candidates],
               "counts": {"candidates": count, "shown": count}}
    evidence = {"issue": "The combined value doubles.",
                "production_context": {"files": [{"path": "public.py", "snippets": [{
                    "code": 'def combine(value):\n    """Return the combined value."""\n    return "DO_NOT_SEND_IMPLEMENTATION"\n'}]}]},
                "execution_outcomes": "DO_NOT_SEND_OUTCOMES"}
    return corpus, evidence, pending


def envelope(content):
    return {"model": model.MODEL, "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 13}}


def completion(cid="c0", expression="pre[0] * arg[0]", guard=None):
    return {"candidate_id": cid, "observe": 0, "expected": expression, "guard": guard}


class FakeProvider:
    """httpx transport handles test requests entirely in memory."""
    def __init__(self, root, raw=None, *, status=200, body=None):
        self.root, self.raw, self.status, self.body = root, raw, status, body
        self.requests = []
        self.stack = ExitStack()

    def __enter__(self):
        policy = self.root / "configs/execution_policy.json"
        model.write_json(policy, {"allow_model_code_upload": True})
        model.write_json(self.root / "results/api_route.json", {"prefix": "v1/"})
        real_client = httpx.Client

        def handler(request):
            self.requests.append(request)
            if self.body is not None:
                return httpx.Response(self.status, content=self.body)
            return httpx.Response(self.status, json=self.raw)

        self.stack.enter_context(patch.object(model, "ROOT", self.root))
        self.stack.enter_context(patch.object(model, "dotenv_values", return_value={
            "BASE_URL": "https://provider.invalid", "API_KEY": "test-secret"}))
        self.stack.enter_context(patch.object(model.httpx, "Client", side_effect=lambda **kw:
            real_client(transport=httpx.MockTransport(handler), **kw)))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


class CompletionCacheTests(unittest.TestCase):
    def test_request_is_one_fixed_dispatch_with_hash_mapping_and_usage(self):
        corpus, evidence, pending = synthetic_inputs()
        shown = model.presentation(corpus, evidence, pending)
        raw = envelope(json.dumps({"completions": [completion()]}))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with FakeProvider(root, raw) as provider:
                result = model.request_completion(shown, pending, root / "round")
                self.assertEqual(len(provider.requests), 1)
                self.assertEqual(str(provider.requests[0].url), "https://provider.invalid/v1/chat/completions")
                request = json.loads(provider.requests[0].content)
                self.assertEqual(request["model"], "deepseek-v4-flash")
                self.assertEqual(request["max_tokens"], 10000)
                self.assertEqual(request["temperature"], 0)
                self.assertEqual(request["thinking"], {"type": "disabled"})
                self.assertEqual(request["reasoning_effort"], "none")
                self.assertIn("json", request["messages"][0]["content"].lower())
                self.assertEqual(request["response_format"], {"type": "json_object"})
                self.assertEqual(result["usage"], raw["usage"])
                checked, validation = model.load_completion(root / "round", shown, pending)
                self.assertTrue(checked["valid"])
                self.assertEqual(validation["accepted"][0]["candidate_id"], "hash-0")
                self.assertEqual(validation["accepted"][0]["literal"], "8")
                text = (root / "round/manifest.json").read_text()
                self.assertNotIn("provider.invalid", text)
                self.assertNotIn("test-secret", text)
                self.assertEqual((root / "round/request.json").read_bytes(), model.encoded(model.request_payload(shown)))

    def test_empty_candidates_do_not_read_credentials_or_contact_provider(self):
        corpus, evidence, pending = synthetic_inputs(0)
        shown = model.presentation(corpus, evidence, pending)
        with TemporaryDirectory() as temporary, patch.object(model, "dotenv_values") as credentials, \
                patch.object(model.httpx, "Client") as client:
            output = Path(temporary) / "empty"
            result = model.request_completion(shown, pending, output)
            self.assertTrue(result["valid"])
            self.assertEqual(result["external_model_calls"], 0)
            self.assertEqual(model.load_completion(output, shown, pending)[1], {"accepted": [], "rejected": []})
            credentials.assert_not_called()
            client.assert_not_called()

    def test_invalid_protocol_is_not_valid_all_rejection(self):
        corpus, evidence, pending = synthetic_inputs()
        shown = model.presentation(corpus, evidence, pending)
        for content in ("not JSON", '{"completions": [], "tests": []}',
                        json.dumps({"completions": [completion("unknown")]})):
            with self.subTest(content=content), TemporaryDirectory() as temporary:
                root = Path(temporary)
                with FakeProvider(root, envelope(content)) as provider:
                    result = model.request_completion(shown, pending, root / "round")
                    self.assertFalse(result["valid"])
                    self.assertEqual(result["failure_kind"], "invalid_completion_protocol")
                    self.assertNotIn("accepted", result)
                    self.assertEqual(len(provider.requests), 1)
                    with self.assertRaisesRegex(ValueError, "No valid"):
                        model.load_completion(root / "round", shown, pending)

    def test_valid_empty_list_and_false_guard_are_explicit_rejections(self):
        _, _, pending = synthetic_inputs()
        for payload, reason in (({"completions": []}, "missing_completion"),
                                ({"completions": [completion(guard="arg[0] < 0")]}, "guard_false")):
            result = model.resolve_completion(json.dumps(payload), pending)
            self.assertNotIn("protocol_error", result)
            self.assertEqual(result["accepted"], [])
            self.assertEqual(result["rejected"][0]["code"], reason)

    def test_ninth_completion_invalidates_response(self):
        _, _, pending = synthetic_inputs(9)
        payload = {"completions": [completion(f"c{index}") for index in range(9)]}
        result = model.resolve_completion(json.dumps(payload), pending)
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["protocol_error"]["code"], "payload_budget")

    def test_tampered_cache_and_reused_output_are_rejected(self):
        corpus, evidence, pending = synthetic_inputs()
        shown = model.presentation(corpus, evidence, pending)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with FakeProvider(root, envelope(json.dumps({"completions": [completion()]}))) as provider:
                output = root / "round"
                model.request_completion(shown, pending, output)
                with self.assertRaises(FileExistsError):
                    model.request_completion(shown, pending, output)
                self.assertEqual(len(provider.requests), 1)
                (output / "completion.txt").write_text('{"completions": []}')
                with self.assertRaisesRegex(ValueError, "artifact changed"):
                    model.load_completion(output, shown, pending)

    def test_error_body_and_usage_envelope_are_cached_without_retry(self):
        corpus, evidence, pending = synthetic_inputs()
        shown = model.presentation(corpus, evidence, pending)
        for status, body, reason in ((503, b'{"error":"unavailable"}', "http_status_error"),
                                      (200, b"not JSON", "invalid_response_envelope")):
            with self.subTest(status=status), TemporaryDirectory() as temporary:
                root = Path(temporary)
                with FakeProvider(root, status=status, body=body) as provider:
                    result = model.request_completion(shown, pending, root / "round")
                    self.assertFalse(result["valid"])
                    self.assertEqual(result["failure_kind"], reason)
                    self.assertEqual(len(provider.requests), 1)
                    self.assertEqual((root / "round/response.body").read_bytes(), body)

    def test_response_byte_budget_stops_without_retry(self):
        corpus, evidence, pending = synthetic_inputs()
        shown = model.presentation(corpus, evidence, pending)
        with TemporaryDirectory() as temporary, patch.object(model, "MAX_RESPONSE_BYTES", 12):
            root = Path(temporary)
            with FakeProvider(root, body=b"x" * 100) as provider:
                result = model.request_completion(shown, pending, root / "round")
                self.assertEqual(result["failure_kind"], "response_byte_budget")
                self.assertEqual(len(provider.requests), 1)
                self.assertEqual(len((root / "round/response.body").read_bytes()), 13)
                self.assertIn("seconds", json.loads((root / "round/manifest.json").read_bytes()))

    def test_presentation_deduplicates_source_and_does_not_show_implementation(self):
        corpus, evidence, pending = synthetic_inputs(2)
        shown = model.presentation(corpus, evidence, pending)
        self.assertEqual(len(shown["source_tests"]), 1)
        self.assertEqual(shown["candidates"][0]["source_test_ids"], ["t0"])
        self.assertEqual(shown["candidates"][1]["source_test_ids"], ["t0"])
        self.assertEqual(shown["candidates"][0]["expected_hole"]["original_text"], "4")
        request = model.encoded(model.request_payload(shown)).decode()
        self.assertIn("Return the combined value.", request)
        for forbidden in ("DO_NOT_SEND_IMPLEMENTATION", "DO_NOT_SEND_OUTCOMES", "hash-0", "hash-1"):
            self.assertNotIn(forbidden, request)

    def test_helper_filter_only_shows_bounded_test_or_oracle_support(self):
        corpus, evidence, pending = synthetic_inputs(2)
        helpers = []
        for name, path, code, oracle_helper in (
                ("test_support", "tests/helpers.py", "TEST_HELPER_ALLOWED", False),
                ("oracle_support", "checks.py", "ORACLE_HELPER_ALLOWED", True),
                ("implementation", "production.py", "PRODUCTION_HELPER_FORBIDDEN", False),
                ("huge", "tests/huge.py", "X" * 14001, False)):
            corpus["sources"][path] = {"code": code}
            helpers.append({"id": name, "name": name, "oracle_helper": oracle_helper,
                            "span": {"path": path, "start_byte": 0, "end_byte": len(code)}})
        helpers.append({"id": "missing", "name": "missing", "oracle_helper": True,
                        "span": {"path": "missing.py", "start_byte": 0, "end_byte": 3}})
        corpus["tests"]["parent"]["support"]["helpers"] = helpers
        shown = model.presentation(corpus, evidence, pending)
        request = model.encoded(shown).decode()
        self.assertEqual(len(shown["test_helpers"]), 2)
        self.assertEqual(len(shown["source_tests"]["t0"]["test_helper_ids"]), 2)
        self.assertIn("TEST_HELPER_ALLOWED", request)
        self.assertIn("ORACLE_HELPER_ALLOWED", request)
        self.assertNotIn("PRODUCTION_HELPER_FORBIDDEN", request)
        self.assertEqual({row["reason"] for row in shown["omitted_helpers"]},
                         {"source_unavailable", "not_a_test_or_oracle_helper", "helper_source_byte_budget"})


class DriverStagesTests(unittest.TestCase):
    def source_preparation(self, root, corpus, evidence):
        source = root / "source"
        source.mkdir()
        values = {"case.json": {"id": "synthetic", "language": "python", "repository": str(root / "subject")},
                  "retrieval.json": {}, "corpus.json": corpus, "evidence.json": evidence}
        for name, value in values.items():
            model.write_json(source / name, value)
        manifest = {"case_id": "synthetic", "status": "complete",
                    "files_sha256": {name: model.digest((source / name).read_bytes()) for name in values}}
        model.write_json(source / "prepare.json", manifest)
        return source

    def test_two_rounds_use_identical_frozen_requests_and_cannot_be_repeated(self):
        corpus, evidence, pending = synthetic_inputs()
        with TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            stack.enter_context(patch.object(transport.driver, "algorithm_hashes", return_value={}))
            stack.enter_context(patch.object(transport, "transport_hashes", return_value={}))
            stack.enter_context(patch.object(transport.proposals, "generate", return_value=pending))
            materialize = stack.enter_context(patch.object(transport.proposals, "materialize", return_value={
                "id": "executable", "base_test_id": "parent", "source_test_ids": ["parent"]}))
            source = self.source_preparation(root, corpus, evidence)
            args = SimpleNamespace(case="synthetic", source_prepared=source, output=root / "prepared", rerun_id="r1")
            transport.prepare(args)
            with FakeProvider(root, envelope(json.dumps({"completions": [completion()]}))) as provider:
                first = transport.complete(args)
                args.rerun_id = "r2"
                second = transport.complete(args)
                self.assertEqual(first["counts"]["candidates"], 1)
                self.assertEqual(second["counts"]["candidates"], 1)
                self.assertEqual(len(provider.requests), 2)
                self.assertEqual(provider.requests[0].content, provider.requests[1].content)
                self.assertEqual(materialize.call_args.args[2]["literal"], "8")
                transport.checked_round(args)
                with self.assertRaises(FileExistsError):
                    transport.complete(args)
                self.assertEqual(len(provider.requests), 2)
                changed = args.output / "rounds/r2/generated.json"
                changed.write_text("{}")
                with self.assertRaisesRegex(ValueError, "artifact changed"):
                    transport.checked_round(args)

    def test_invalid_round_has_no_generic_preparation_and_is_not_freezable(self):
        corpus, evidence, pending = synthetic_inputs()
        with TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            stack.enter_context(patch.object(transport.driver, "algorithm_hashes", return_value={}))
            stack.enter_context(patch.object(transport, "transport_hashes", return_value={}))
            stack.enter_context(patch.object(transport.proposals, "generate", return_value=pending))
            materialize = stack.enter_context(patch.object(transport.proposals, "materialize"))
            source = self.source_preparation(root, corpus, evidence)
            args = SimpleNamespace(case="synthetic", source_prepared=source, output=root / "prepared", rerun_id="r1")
            transport.prepare(args)
            with FakeProvider(root, envelope("unusable")):
                result = transport.complete(args)
            self.assertEqual(result["status"], "invalid")
            self.assertIsNone(result["compatible_prepared_output"])
            self.assertFalse((args.output / "rounds/r1/prepare.json").exists())
            materialize.assert_not_called()
            with self.assertRaises(FileNotFoundError):
                transport.checked_round(args)

    def test_tampered_source_rejected_before_output_is_created(self):
        corpus, evidence, _ = synthetic_inputs()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_preparation(root, corpus, evidence)
            (source / "evidence.json").write_text("{}")
            args = SimpleNamespace(case="synthetic", source_prepared=source, output=root / "prepared")
            with self.assertRaisesRegex(ValueError, "Frozen input changed"):
                transport.prepare(args)
            self.assertFalse(args.output.exists())

    def test_empty_round_freezes_without_subject_or_provider_execution(self):
        corpus, evidence, pending = synthetic_inputs(0)
        with TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            stack.enter_context(patch.object(transport.driver, "algorithm_hashes", return_value={}))
            stack.enter_context(patch.object(transport, "transport_hashes", return_value={}))
            stack.enter_context(patch.object(transport.proposals, "generate", return_value=pending))
            client = stack.enter_context(patch.object(model.httpx, "Client"))
            credentials = stack.enter_context(patch.object(model, "dotenv_values"))
            stack.enter_context(patch("generic_composition.emitter.emit", return_value={
                "files": {}, "obligations": [], "controls": [], "unsupported": []}))

            def fake_freeze(artifact, *args, **kwargs):
                model.write_json(artifact / "manifest.json", {"metadata": kwargs["metadata"]})
                return {"files": {}}

            freeze = stack.enter_context(patch("generic_composition.runner.freeze_artifact", side_effect=fake_freeze))
            source = self.source_preparation(root, corpus, evidence)
            args = SimpleNamespace(case="synthetic", source_prepared=source, output=root / "prepared",
                                   rerun_id="r1", timeout=180)
            transport.prepare(args)
            completed = transport.complete(args)
            frozen = transport.freeze(args)
            self.assertEqual(completed["external_model_calls"], 0)
            self.assertEqual(frozen["accepted"], 0)
            self.assertTrue(freeze.call_args.kwargs["metadata"]["no_executable_tests"])
            credentials.assert_not_called()
            client.assert_not_called()

    def test_algorithm_snapshot_tampering_is_detected(self):
        corpus, evidence, pending = synthetic_inputs(0)
        with TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            own_name = "scripts/run_semantic_transport.py"
            own_hash = transport.driver.digest(transport.ROOT / own_name)
            stack.enter_context(patch.object(transport.driver, "algorithm_hashes", return_value={}))
            stack.enter_context(patch.object(transport, "transport_hashes", return_value={own_name: own_hash}))
            stack.enter_context(patch.object(transport.proposals, "generate", return_value=pending))
            source = self.source_preparation(root, corpus, evidence)
            args = SimpleNamespace(case="synthetic", source_prepared=source, output=root / "prepared")
            transport.prepare(args)
            transport.checked_inputs(args)
            (args.output / "algorithm_snapshot" / own_name).write_text("changed")
            with self.assertRaisesRegex(ValueError, "Frozen input changed"):
                transport.checked_inputs(args)


if __name__ == "__main__":
    unittest.main()
