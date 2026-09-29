import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from relation_search.runtime import HELPER_PATH, HELPER_SOURCE, prepare_python_probes


class RuntimeProbes(unittest.TestCase):
    def instrument(self, source, roles, marker="assert", phase="before", extra_probes=None):
        position = source.encode().index(marker.encode())
        span = {"path": "example.py", "start_byte": position, "end_byte": position}
        probe = {"phase": phase, "insert_before": span, "roles": [
            {"name": name, "expression": expression, "origin_span": span}
            for name, expression in roles]}
        result = prepare_python_probes(source, "example.py", "candidate-x", "window-y",
                                       [probe, *(extra_probes or [])])
        code = source.encode()
        for edit in reversed(result["edits"]):
            a, b = edit["span"]["start_byte"], edit["span"]["end_byte"]
            code = code[:a] + edit["after"].encode() + code[b:]
        return code.decode(), result

    def execute(self, source, roles, **kwargs):
        code, result = self.instrument(source, roles, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, HELPER_PATH).write_text(HELPER_SOURCE)
            with patch.dict(os.environ, {"COMBINATION_REPORT_DIR": directory}), patch.object(sys, "path", [directory, *sys.path]):
                sys.modules.pop("__relation_runtime", None)
                namespace = {}
                exec(compile(code, "example.py", "exec"), namespace)
                namespace["test_seed"]()
                trace = [json.loads(line) for line in Path(directory, "relation_trace.jsonl").read_text().splitlines()]
                sys.modules.pop("__relation_runtime", None)
        return trace, result

    def test_scalar_and_alias_snapshot_no_addresses(self):
        source = "def test_seed():\n    x = [4]\n    y = x\n    z = [4]\n    assert x == y\n"
        trace, _ = self.execute(source, [("x", "x"), ("y", "y"), ("z", "z"), ("item", "x[0]")])
        row = trace[0]
        self.assertEqual(row["alias_partition"], [["x", "y"], ["z"]])
        self.assertEqual(row["roles"][3]["value"], {"type": "int", "value": 4})
        self.assertEqual(row["candidate_id"], "candidate-x")
        self.assertNotIn("0x", json.dumps(row))

    def test_read_attributes_without_running_properties_or_getitem(self):
        source = '''class Subject:
    def __init__(self):
        self.n = 7
        self.calls = 0
    @property
    def danger(self):
        self.calls += 1
        raise RuntimeError("side effect")
    def __getitem__(self, key):
        self.calls += 1
        raise RuntimeError("side effect")
def test_seed():
    obj = Subject()
    assert obj.calls == 0
'''
        trace, _ = self.execute(source, [("n", "obj.n"), ("property", "obj.danger"), ("index", "obj[0]")])
        self.assertEqual([r["status"] for r in trace[0]["roles"]], ["observed", "unknown", "unknown"])

    def test_missing_values_unknown_preserve_original_assertion(self):
        trace, _ = self.execute("def test_seed():\n    x = {}\n    assert x == {}\n",
                                [("missing", "x['missing']"), ("unbound", "not_bound")])
        self.assertTrue(all(r["status"] == "unknown" for r in trace[0]["roles"]))

    def test_reject_call_and_computed_key(self):
        source = "def test_seed():\n    assert True\n"
        for expression in ("api()", "x[y]", "x + 1", "next(x)", "x[1:2]"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                self.instrument(source, [("value", expression)])

    def test_negative_integer_key_and_nested_dict(self):
        trace, _ = self.execute("def test_seed():\n    x = {'k': [1, 8]}\n    assert True\n",
                                [("v", "x['k'][-1]")])
        self.assertEqual(trace[0]["roles"][0]["value"]["value"], 8)

    def test_literal_roles_distinct_from_dynamic_reads(self):
        trace, _ = self.execute("def test_seed():\n    x = 'folder name'\n    assert x\n",
                                [("component", "'folder name'"), ("x", "x"),
                                 ("closed", "{'a': [1, None, True]}")])
        roles = trace[0]["roles"]
        self.assertEqual([r["kind"] for r in roles], ["literal", "read", "literal"])
        self.assertEqual(roles[0]["value"], roles[1]["value"])
        self.assertEqual(trace[0]["alias_partition"], [])

    def test_nonfinite_or_non_json_literals_rejected(self):
        for expression in ("1e309", "{1, 2}", "(1, 2)", "1j"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                self.instrument("def test_seed():\n    assert True\n", [("literal", expression)])

    def test_unicode_offsets_and_nested_statement(self):
        source = "def test_seed():\n    text = '中文'\n    if text:\n        assert text\n"
        trace, _ = self.execute(source, [("value", "text")])
        self.assertEqual(trace[0]["roles"][0]["value"]["value"], "中文")

    def test_cycles_bounded_without_user_repr(self):
        source = "def test_seed():\n    x = []\n    x.append(x)\n    assert len(x) == 1\n"
        trace, _ = self.execute(source, [("x", "x")])
        self.assertTrue(trace[0]["roles"][0]["value"]["items"][0]["reference"])

    def test_probe_exception_cannot_suppress_assertion_failure(self):
        source = "def test_seed():\n    assert False, 'original assertion'\n"
        with self.assertRaisesRegex(AssertionError, "original assertion"):
            self.execute(source, [("unbound", "missing")])

    def test_insert_in_expression_or_inline_suite_rejected(self):
        for source, marker in [("def test_seed():\n    assert True\n", "True"),
                               ("def test_seed(): assert True\n", "assert")]:
            with self.assertRaises(ValueError):
                self.instrument(source, [("v", "x")], marker=marker)

    def test_multiple_probes_at_same_statement_merge_as_one_edit(self):
        source = "def test_seed():\n    x = 5\n    assert x == 5\n"
        position = source.encode().index(b"assert")
        extra = {"phase": "observer", "insert_before": {"path": "example.py", "start_byte": position},
                 "roles": [{"name": "x_again", "expression": "x"}]}
        trace, result = self.execute(source, [("x", "x")], extra_probes=[extra])
        self.assertEqual(len(result["edits"]), 1)
        self.assertEqual([row["phase"] for row in trace], ["before", "observer"])

    def test_generic_emitter_accepts_probe_edits_and_preserves_source_control(self):
        from generic_composition.corpus import build_corpus
        from generic_composition.emitter import emit
        source = "def test_seed():\n    x = 5\n    assert x == 5\n"
        _, instrumentation = self.instrument(source, [("x", "x")])
        for edit in instrumentation["edits"]:
            edit["span"]["path"] = "test_example.py"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "test_example.py").write_text(source)
            corpus = build_corpus(Path(directory), "python")
            identifier = next(iter(corpus["tests"]))
            emitted = emit(corpus, [{"id": "candidate_x", "base_test_id": identifier,
                                    "edits": instrumentation["edits"], "imports": []}])
        self.assertFalse(emitted["unsupported"])
        materialized = emitted["files"]["test_example.py"]
        self.assertEqual(materialized.count(".capture("), 1)
        self.assertEqual(materialized.count("assert x == 5"), 3)
        compile(materialized, "materialized.py", "exec")


if __name__ == "__main__":
    unittest.main()
