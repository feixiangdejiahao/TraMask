"""Independent language fixtures, with no discovery-case/project fixtures."""
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, source_text, to_emitter_corpus


def frontend(code, language="python", path="test_sample.py", **kwargs):
    return extract_frontend([Source(path, code, language)], **kwargs)


def call_named(data, name):
    return next(c for c in data["calls"] if c["callee"] == name)


def test_utf8_value_slots_and_keyword_deletion_are_exact():
    data = frontend('''
def accepts(value, enabled=True):
    return value > 0

def test_value():
    title = "界🙂"
    answer = accepts(2, enabled=True)
    assert answer is True
''')
    call = call_named(data, "accepts")
    arg = call["arguments"][1]
    assert source_text(data, arg["span"]) == "True"
    assert source_text(data, arg["argument_span"]) == "enabled=True"
    assert source_text(data, arg["removal_span"]) == ", enabled=True"
    assert arg["keyword"] == "enabled"
    assert call["argument_bindings"][1]["parameter"] == "enabled"
    definition = next(f for f in data["functions"] if f["name"] == "accepts")
    assert definition["parameters"][1]["default"]["literal_value"] is True
    assert data["comparisons"][0]["operator"] == ">"
    assert data["comparisons"][0]["parameter_names"] == ["value"]


def test_decorated_method_owner_clones_in_original_class():
    data = frontend('''
def tag(function):
    return function

def accepts(value):
    return value < 4

class TestExamples:
    @tag
    def test_value(self):
        answer = accepts(2)
        assert answer is True
''')
    test = data["tests"][0]
    assert source_text(data, test["span"]).startswith("@tag")
    assert source_text(data, test["definition_span"]).startswith("def test_value")
    corpus = to_emitter_corpus(data)
    argument = call_named(data, "accepts")["arguments"][0]
    emitted = emit(corpus, [{"id": "small_change", "base_test_id": test["id"],
                             "edits": [{"span": argument["span"], "before": "2", "after": "3"}]}])
    assert not emitted["unsupported"]
    code = emitted["files"]["test_sample.py"]
    compile(code, "test_sample.py", "exec")
    assert "@tag\n    def test_gc_small_change(self):" in code
    assert "answer = accepts(3)" in code
    assert len(emitted["controls"]) == 1


def test_record_presence_is_syntactic_and_literal_strings_stay_opaque():
    data = frontend('''
def test_record():
    answer = build({"left": 1, "right": "x < 9"})
    assert answer == {"count": 2}
''')
    arg = call_named(data, "build")["arguments"][0]
    assert arg["structure"]["complete_keys"]
    assert [f["key"] for f in arg["structure"]["fields"]] == ["left", "right"]
    string = next(v for v in data["values"] if v["text"] == '"x < 9"')
    assert string["embedded_language"] == "opaque"
    assert string["role"] == "input"
    assert not data["comparisons"]
    expected = next(v for v in data["values"] if v["text"] == '{"count": 2}')
    assert expected["oracle_dependency"]


def test_expected_alias_protected_from_input_donor_pool():
    data = frontend('''
def test_alias():
    expected = {"count": 2}
    answer = build({"count": 1})
    assert answer == expected
''')
    corpus = to_emitter_corpus(data)
    expected = next(d for d in corpus["donors"] if d["text"] == '{"count": 2}')
    actual = next(d for d in corpus["donors"] if d["text"] == '{"count": 1}')
    assert expected["oracle_dependency"]
    assert expected["role"] == "expected"
    assert not actual["oracle_dependency"]
    assert actual["call_context"]["callee"] == "build"


def test_setup_value_provenance_reaches_argument_slot():
    data = frontend('''
def test_argument():
    payload = {"count": 3}
    answer = build(payload)
    assert answer == 3
''')
    corpus = to_emitter_corpus(data)
    donor = next(d for d in corpus["donors"] if d["text"] == '{"count": 3}')
    assert donor["input_slots"][0]["callee"] == "build"
    assert donor["input_slots"][0]["argument_slot"] == 0


def test_alias_revision_and_observation_phase_remain_explicit():
    data = frontend('''
def test_identity():
    first = make()
    alias = first
    first = make()
    alias.start()
    assert alias.ready
    alias.finish()
    if flag:
        alias = first
    alias.check()
''')
    start = call_named(data, "alias.start")
    constructors = [b for b in data["bindings"] if b["name"] == "first"]
    assert start["receiver_binding"]["origin_binding_id"] == constructors[0]["id"]
    assert start["receiver_binding"]["origin_binding_id"] != constructors[1]["id"]
    check = call_named(data, "alias.check")
    assert check["receiver_binding"]["resolution"] == "conditional_write_unknown"
    assert check["receiver_binding"]["origin_binding_id"] is None
    observation = data["observations"][0]
    assert start["id"] in observation["before_call_ids"]
    assert call_named(data, "alias.finish")["id"] in observation["after_call_ids"]
    assert all(e["ordering_status"] == "lexical_only_not_runtime_happens_before" for e in data["events"])


def test_go_testing_guard_and_formals():
    data = frontend('''package example
import "testing"
func accepts(value, limit int) bool {
    if value <= limit { return true }
    return false
}
func TestValue(t *testing.T) {
    value := accepts(2, 4)
    if !value { t.Fatal("unexpected") }
}
''', "go", "value_test.go")
    assert data["stats"]["observations"] == 1
    observation = data["observations"][0]
    assert observation["predicate"] == "truthy"
    assert observation["adapter"] == "go_testing_failure_guard"
    call = call_named(data, "accepts")
    assert [b["parameter"] for b in call["argument_bindings"]] == ["value", "limit"]
    comparison = data["comparisons"][0]
    assert comparison["guard_span"] is not None
    assert comparison["parameter_names"] == ["limit", "value"]
    corpus = to_emitter_corpus(data)
    emitted = emit(corpus, [{"id": "go_clone", "base_test_id": data["tests"][0]["id"], "edits": []}])
    assert not emitted["unsupported"]
    assert "func TestGC_go_clone" in emitted["files"]["value_test.go"]


def test_typescript_default_records_and_whole_registration():
    data = frontend('''
function accepts(value: number, options = {low: 1, high: 3}) {
    return value >= options.low && value <= options.high;
}
describe("outer", () => {
  it("sample", () => {
    const answer = accepts(2, {low: 1, high: 3});
    expect(answer).toBe(true);
  });
});
''', "typescript", "value.test.ts")
    assert data["stats"]["tests"] == 1
    assert data["stats"]["observations"] == 1
    assert len(data["comparisons"]) == 2
    call = call_named(data, "accepts")
    assert call["arguments"][1]["structure"]["explicit_count"] == 2
    fn = next(f for f in data["functions"] if f["name"] == "accepts")
    assert fn["parameters"][1]["default"]["text"] == "{low: 1, high: 3}"
    corpus = to_emitter_corpus(data)
    emitted = emit(corpus, [{"id": "ts_clone", "base_test_id": data["tests"][0]["id"], "edits": []}])
    assert not emitted["unsupported"]
    assert emitted["obligations"][0]["id"] == "outer gc_ts_clone"


def test_changed_unreachable_function_predicates_are_retained():
    sources = [Source("main.py", "def accepts(x):\n    return x < 4\n", "python"),
               Source("test_main.py", "def test_value():\n    assert 1 == 1\n", "python")]
    patch = "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n def accepts(x):\n-    return x <= 4\n+    return x < 4\n"
    data = extract_frontend(sources, patch=patch)
    assert len(data["comparisons"]) == 1
    assert data["comparisons"][0]["relevance"][0]["kind"] == "changed_function"
    assert data["comparisons"][0]["operator"] == "<"


def test_historical_module_output_is_not_an_assertion():
    data = extract_frontend([Source("trajectory/probe.py", 'value = operation(3)\nprint(value)\n', "python", "trajectory")])
    assert data["tests"][0]["owner_kind"] == "module_script"
    assert data["tests"][0]["emission_status"] == "wrapper_required"
    assert data["observations"][0]["kind"] == "output"
    assert data["observations"][0]["oracle_status"] == "unchecked_output_no_assertion"
    assert not to_emitter_corpus(data)["capsules"]


def test_historical_module_assertion_preserves_complete_owner():
    code = "from library import operation\nvalue = operation(3)\nassert value == 4\n"
    data = extract_frontend([Source("trajectory/check.py", code, "python", "trajectory")])
    assert source_text(data, data["tests"][0]["span"]) == code
    assert data["observations"][0]["kind"] == "assertion"
    assert data["observations"][0]["expected"]["literal_value"] == 4


def test_pytest_exception_context_is_an_existing_observation():
    data = frontend('''
from pytest import raises as rejects

def test_exception():
    with rejects(ValueError):
        decode("invalid")
''')
    assert len(data["observations"]) == 1
    observation = data["observations"][0]
    assert observation["predicate"] == "raises"
    assert observation["observation_type"] == "exception"
    assert observation["expected"]["text"] == "ValueError"
    assert observation["observed"]["text"] == 'decode("invalid")'
    assert source_text(data, observation["assertion_span"]).startswith("with rejects")
    assert len(to_emitter_corpus(data)["capsules"]) == 1


def test_go_callback_assertion_keeps_whole_executable_test_owner():
    data = frontend('''package example
import "testing"
func check(value int) int { return value + 1 }
func TestCallbacks(t *testing.T) {
    t.Run("nested", func(t *testing.T) {
        got := check(2)
        if got != 3 { t.Fatal("unexpected") }
    })
}
''', "go", "callback_test.go")
    assert len(data["tests"]) == 1
    assert len(data["observations"]) == 1
    observation = data["observations"][0]
    assert observation["test_id"] == data["tests"][0]["id"]
    assert observation["observed"]["text"] == "got"
    assert any(c["kind"] == "func_literal" for c in observation["contexts"])
    assert call_named(data, "check")["id"] in observation["source_call_ids"]


def test_typescript_callback_assertion_remains_static_unknown_execution():
    data = frontend('''
test("callbacks", () => {
    later(() => {
        const value = read(2);
        expect(value).toBe(3);
    });
});
''', "typescript", "callback.test.ts")
    assert len(data["observations"]) == 1
    observation = data["observations"][0]
    assert observation["coverage_status"] == "static_observation_only"
    assert any(c["kind"] == "arrow_function" for c in observation["contexts"])
    assert observation["test_id"] == data["tests"][0]["id"]


def test_field_default_traces_forwarded_parameter_to_test_argument():
    data = frontend('''
function inner({mode = "write", range: {low = 0}}: Options = {}) {
    return mode;
}
function outer(options: Options) {
    if (enabled) return inner(options);
    return "write";
}
test("default fields", () => {
    const value = outer({mode: "write", range: {low: 0}});
    expect(value).toBe("write");
});
''', "typescript", "fields.test.ts")
    mode = next(d for d in data["field_defaults"] if d["field"] == "mode")
    low = next(d for d in data["field_defaults"] if d["field"] == "low")
    assert mode["default"]["literal_value"] == "write"
    assert mode["parameter_index"] == 0
    assert mode["field_path"] == ["mode"]
    assert low["field_path"] == ["range", "low"]
    binding = mode["caller_bindings"][0]
    assert binding["call_id"] == call_named(data, "outer")["id"]
    assert binding["slot"] == 0
    assert len(binding["path"]) == 2
    assert binding["applicability"] == "source_default_not_proved_on_all_paths"


def test_field_default_local_destructuring_and_nullish_syntax():
    data = frontend('''
function read(options: Options) {
    const {mode = "write"} = options;
    const retries = options.retries ?? 2;
    return mode;
}
test("fields", () => { expect(read({mode: "write"})).toBe("write"); });
''', "typescript", "defaults.test.ts")
    assert {d["mechanism"] for d in data["field_defaults"]} == {"destructuring_default", "nullish_coalescing"}
    assert all(len(d["caller_bindings"]) == 1 for d in data["field_defaults"])


def test_whole_object_default_does_not_claim_per_field_defaults():
    data = frontend('''
function read(options = {mode: "write"}) { return options.mode; }
test("whole", () => { expect(read({mode: "write"})).toBe("write"); });
''', "typescript", "whole.test.ts")
    assert not data["field_defaults"]


def test_assigned_arrow_functions_supply_defaults_and_guards():
    data = frontend('''
const internal = ({mode = "write"}: Options) => mode;
const outer = (options: Options, count = 2) => {
    if (count < 3) return internal(options);
    return "skip";
};
test("arrows", () => { expect(outer({mode: "write"}, 2)).toBe("write"); });
''', "typescript", "arrows.test.ts")
    assert {f["name"] for f in data["functions"]} >= {"internal", "outer"}
    assert data["comparisons"][0]["parameter_names"] == ["count"]
    default = data["field_defaults"][0]
    assert default["field"] == "mode"
    assert default["caller_bindings"][0]["call_id"] == call_named(data, "outer")["id"]


def test_imported_class_reexport_alias_resolves_generic_method_and_forwarded_defaults():
    sources = [
        Source("core/defaults.ts", 'export const normalize = ({mode = "write"}: Options = {}) => mode;', "typescript"),
        Source("core/container.ts", '''
import { normalize } from "./defaults";
export class Holder {
  constructor(schema: object) {}
  public parser<T>(value: T, options: Options = {}) { return normalize(options); }
}
''', "typescript"),
        Source("bridge.ts", 'export { Holder as Container } from "./core/container";', "typescript"),
        Source("index.ts", 'export * from "./bridge";', "typescript"),
        Source("sample.test.ts", '''
import { Container as Imported } from "./index";
test("instance", () => {
  const original = new Imported({field: 1});
  const alias = original;
  const result = alias.parser<number>(1, {mode: "write"});
  expect(result).toBe("write");
});
''', "typescript"),
    ]
    data = extract_frontend(sources)
    call = call_named(data, "alias.parser")
    assert call["targets"] == [{"function_id": "core/container.ts:5:Holder.parser",
                                "reason": "source_constructor_receiver", "resolved": True}]
    assert call["callee_identity"]["canonical"] == "core/container.ts::Holder.parser"
    default = next(f for f in data["field_defaults"] if f["field"] == "mode")
    binding = default["caller_bindings"][0]
    assert binding["call_id"] == call["id"]
    assert binding["slot"] == 1
    assert len(binding["path"]) == 2


def test_constructor_class_identity_uses_module_not_same_name():
    data = extract_frontend([
        Source("good.ts", 'export class Box { parse(x: number, limit = 3) { return x <= limit; } }', "typescript"),
        Source("other.ts", 'export class Box { parse(x: number, limit = 99) { return false; } }', "typescript"),
        Source("sample.test.ts", '''
import { Box } from "./good";
test("module", () => { const box = new Box(); expect(box.parse(2, 3)).toBe(true); });
''', "typescript"),
    ])
    call = call_named(data, "box.parse")
    assert len(call["targets"]) == 1
    assert call["targets"][0]["function_id"].startswith("good.ts:")


def test_this_method_and_default_namespace_imports_are_resolved():
    data = extract_frontend([
        Source("box.ts", '''
export default class Box {
  parse(options: Options) { return this.inner(options); }
  private inner({mode = "write"}: Options) { return mode; }
}
''', "typescript"),
        Source("sample.test.ts", '''
import Container from "./box";
test("default", () => { const box = new Container(); expect(box.parse({mode: "write"})).toBe("write"); });
''', "typescript"),
    ])
    inner = next(c for c in data["production_calls"] if c["callee"] == "this.inner")
    assert inner["targets"][0]["reason"] == "source_this_receiver"
    assert len(data["field_defaults"][0]["caller_bindings"]) == 1
    namespace = extract_frontend([
        Source("box.ts", 'export class Box { parse(x: number) { return x < 3; } }', "typescript"),
        Source("sample.test.ts", 'import * as api from "./box"; test("ns", () => { const box = new api.Box(); expect(box.parse(2)).toBe(true); });', "typescript"),
    ])
    assert call_named(namespace, "box.parse")["targets"][0]["reason"] == "source_constructor_receiver"


def test_conditional_or_deferred_receiver_rebindings_do_not_claim_constructor_identity():
    for change in ['if (flag) box = unknown;', 'later(() => { box = unknown; });']:
        data = extract_frontend([
            Source("box.ts", 'export class Box { parse(x: number) { return x < 3; } }', "typescript"),
            Source("sample.test.ts", 'import { Box } from "./box"; test("uncertain", () => { let box = new Box(); '
                   + change + ' expect(box.parse(2)).toBe(true); });', "typescript"),
        ])
        assert not any(t["resolved"] for t in call_named(data, "box.parse")["targets"])


def test_explicit_tsconfig_paths_and_base_url_resolve_without_alias_guessing():
    sources = [
        Source("src/pkg/box.ts", 'export class Box { parse(value: number) { return value < 3; } }', "typescript"),
        Source("sample.test.ts", 'import { Box } from "~/pkg/box"; test("path", () => { const box = new Box(); expect(box.parse(2)).toBe(true); });', "typescript"),
    ]
    unknown = extract_frontend(sources)
    assert not any(t["reason"] == "source_constructor_receiver" for t in call_named(unknown, "box.parse")["targets"])
    resolved = extract_frontend(sources, module_aliases={"~/*": ["src/*"]})
    assert call_named(resolved, "box.parse")["targets"][0]["reason"] == "source_constructor_receiver"
    rooted = extract_frontend(sources, module_aliases={"~/*": ["*"]}, module_base_url="src")
    assert call_named(rooted, "box.parse")["targets"][0]["reason"] == "source_constructor_receiver"
    assert rooted["module_resolution"]["base_url"] == "src"


def test_module_alias_target_fallback_and_specific_pattern():
    sources = [
        Source("src/pkg/box.ts", 'export class Box { parse(value: number) { return value < 3; } }', "typescript"),
        Source("sample.test.ts", 'import { Box } from "alias/pkg/box"; test("paths", () => { const box = new Box(); expect(box.parse(2)).toBe(true); });', "typescript"),
    ]
    data = extract_frontend(sources, module_aliases={"alias/*": ["wrong/*"], "alias/pkg/*": ["missing/*", "src/pkg/*"]})
    assert call_named(data, "box.parse")["targets"][0]["reason"] == "source_constructor_receiver"


def test_python_imported_reexported_class_same_instance_method_resolution():
    data = extract_frontend([
        Source("pkg/core.py", '''
class Holder:
    def parse(self, value, limit=3):
        return self.inner(value, limit)
    def inner(self, value, limit):
        return value < limit
''', "python"),
        Source("pkg/__init__.py", "from .core import Holder as Container\n", "python"),
        Source("test_value.py", '''
from pkg import Container as Imported
def test_instance():
    original = Imported()
    alias = original
    assert alias.parse(2, 3)
''', "python"),
    ])
    call = call_named(data, "alias.parse")
    assert call["targets"][0]["function_id"] == "pkg/core.py:3:Holder.parse"
    assert call["targets"][0]["reason"] == "source_constructor_receiver"
    inner = next(c for c in data["production_calls"] if c["callee"] == "self.inner")
    assert inner["targets"][0]["reason"] == "source_this_receiver"
    assert data["comparisons"][0]["parameter_names"] == ["limit", "value"]


def test_python_module_namespace_constructor_and_duplicate_class_names():
    data = extract_frontend([
        Source("first.py", "class Box:\n    def parse(self, x):\n        return x < 3\n", "python"),
        Source("second.py", "class Box:\n    def parse(self, x):\n        return False\n", "python"),
        Source("test_value.py", "import first as api\ndef test_instance():\n    box = api.Box()\n    assert box.parse(2)\n", "python"),
    ])
    call = call_named(data, "box.parse")
    assert len(call["targets"]) == 1
    assert call["targets"][0]["function_id"].startswith("first.py:")


def test_go_testing_diagnostic_arguments_never_become_input_donors():
    data = frontend('''package sample
import "testing"
func TestValue(t *testing.T) {
    got := operation("payload")
    if got != 3 { t.Fatalf("timed out: %d", got) }
    t.Log("diagnostic only")
}
''', "go", "value_test.go")
    assert call_named(data, "t.Fatalf")["role"] == "diagnostic"
    assert call_named(data, "t.Log")["role"] == "diagnostic"
    corpus = to_emitter_corpus(data)
    assert not any("timed out" in donor["text"] or "diagnostic only" in donor["text"] for donor in corpus["donors"])
    assert any(donor["text"] == '"payload"' for donor in corpus["donors"])
    assert data["observations"][0]["observed"]["text"] == "got"


def test_python_assert_message_and_pytest_fail_arguments_are_diagnostics():
    data = frontend('''
import pytest
def test_value():
    value = operation("payload")
    assert value == 3, format_message("not an input")
    if False:
        pytest.fail("failure message")
''')
    assert call_named(data, "format_message")["role"] == "diagnostic"
    assert call_named(data, "pytest.fail")["role"] == "diagnostic"


def test_go_stateful_assertion_helper_exposes_only_source_operation_arguments():
    from relational_gap.structured_ports import carrier_ports
    code = '''package demo
import "testing"
type Store struct { text string }
func write(t *testing.T, s *Store, values map[string]string, expected string) {
    if len(values)==0 { t.Fatal("empty") }
    next := values["body"]
    s.text = next
    if s.text != expected { t.Fatal("mismatch") }
}
func check(t *testing.T, s *Store, expected string) {
    if s.text != expected { t.Fatal("wrong") }
}
func TestValue(t *testing.T) {
    s := &Store{}
    write(t,s,map[string]string{"body":"alpha\\nLEFT\\ngamma\\n"},"checked")
    check(t,s,"expected only")
    if s.text!="alpha\\nLEFT\\ngamma\\n" { t.Fatal("read mismatch") }
}
'''
    source = Source('value_test.go', code, 'go')
    data = extract_frontend([source])
    action = call_named(data, 'write')
    assert action['role'] == 'assertion'
    assert action['operation_eligible'] is True
    assert action['operation_argument_slots'] == [1, 2]
    assert action['operation_evidence'][0]['kind'] == 'source_parameter_access_write'
    assert not call_named(data, 'check').get('operation_eligible')
    assert any(q['predicate'] == 'assertion_helper' and q['observed']['text'].startswith('write(')
               for q in data['observations'])
    corpus = to_emitter_corpus(data)
    leaf = next(d for d in corpus['donors'] if d['text'] == '"alpha\\nLEFT\\ngamma\\n"' and not d['oracle_dependency'])
    assert leaf['call_context']['callee'] == 'write'
    assert leaf['call_context']['argument_slot'] == 2
    ports = carrier_ports(source, leaf, data)
    assert ports and ports[0]['structural_path'] == [{'kind': 'key', 'value': 'body'}]
    assert not leaf['oracle_dependency'] and leaf['role'] != 'expected'
    for text in ['"checked"', '"expected only"']:
        donor = next(d for d in corpus['donors'] if d['text'] == text)
        assert donor['call_context'] is None and not donor['input_slots']


def test_go_helper_standalone_source_operation_has_distinct_unknown_effect_evidence():
    data = frontend('''package demo
import "testing"
type Store struct { text string }
func (s *Store) Set(value string) { s.text = value }
func write(t *testing.T, s *Store, value string) {
    if value == "" { t.Fatal("empty") }
    s.Set(value)
}
func TestValue(t *testing.T) {
    s := &Store{}
    write(t,s,"payload")
    if s.text!="payload" { t.Fatal("wrong") }
}
''', language='go', path='value_test.go')
    call = call_named(data, 'write')
    assert call['operation_eligible']
    assert call['operation_argument_slots'] == [1, 2]
    assert {fact['kind'] for fact in call['operation_evidence']} == {'source_standalone_operation'}
    assert all(fact['effect_status'] == 'unknown_source_operation_only' for fact in call['operation_evidence'])


def test_go_framework_assertions_and_diagnostics_do_not_gain_operation_arguments():
    data = frontend('''package demo
import "testing"
import "github.com/stretchr/testify/assert"
func TestValue(t *testing.T) {
    actual := "same"
    assert.Equal(t,"expected",actual,"assertion message")
    t.Fatal("failure message")
}
''', language='go', path='value_test.go')
    assert not call_named(data, 'assert.Equal').get('operation_eligible')
    assert not call_named(data, 't.Fatal').get('operation_eligible')
    corpus = to_emitter_corpus(data)
    for donor in corpus['donors']:
        assert donor['call_context'] is None and not donor['input_slots']
    assert not any('failure message' in donor['text'] for donor in corpus['donors'])


def test_python_stateful_helper_retains_assertion_role_and_excludes_expected_argument():
    data = frontend('''class Box: pass
def update(box, value, expected):
    assert value
    box.value = value
    assert box.value == expected
def test_value():
    box = Box()
    update(box, 'payload', 'checked')
    assert box.value == 'payload'
''')
    action = call_named(data, 'update')
    assert action['role'] == 'assertion'
    assert action['operation_argument_slots'] == [0, 1]
    corpus = to_emitter_corpus(data)
    payload = next(d for d in corpus['donors'] if d['text'] == "'payload'" and not d['oracle_dependency'])
    assert payload['call_context']['callee'] == 'update'
    assert next(d for d in corpus['donors'] if d['text'] == "'checked'")['call_context'] is None
    corpus = to_emitter_corpus(data)
    assert not any("not an input" in donor["text"] or "failure message" in donor["text"] for donor in corpus["donors"])


def test_exception_context_arguments_are_not_subject_input_slots():
    data = frontend('''
import pytest
def test_value():
    with pytest.raises(ValueError, match="expected failure"):
        operation("payload")
''')
    assert call_named(data, "pytest.raises")["role"] == "assertion_context"
    corpus = to_emitter_corpus(data)
    match = next(d for d in corpus["donors"] if d["text"] == '"expected failure"')
    assert match["call_context"] is None
    assert not match["input_slots"]


def test_chained_comparisons_and_unsupported_ir_are_explicit():
    data = frontend('''
def bounded(value):
    if 1 < value < get_limit():
        return True
    return False

def test_bound():
    assert bounded(2)
''')
    assert len(data["comparisons"]) == 2
    assert data["comparisons"][0]["left_ir"]["kind"] == "literal"
    assert data["comparisons"][1]["right_ir"]["kind"] == "unknown"
    assert data["comparisons"][1]["right_ir"]["reason"] == "unsupported_expression"


def test_nested_uncalled_function_is_not_attributed_to_test():
    data = frontend('''
def test_scope():
    def helper():
        assert hidden(7) == 9
    assert visible(2) == 3
''')
    assert len(data["observations"]) == 1
    assert [c["callee"] for c in data["calls"]] == ["visible"]


def test_compact_serializable_deterministic_and_source_filterable():
    code = "def test_a():\n    assert f(2) == 3\n\ndef test_b():\n    assert f(4) == 5\n"
    data = frontend(code)
    serialized = json.dumps(data, sort_keys=True)
    assert serialized == json.dumps(frontend(code), sort_keys=True)
    assert '"ast":' not in serialized
    assert '"slice_nodes":' not in serialized
    assert len(serialized) < 35000
    selected = frontend(code, test_ids=[data["tests"][1]["id"]])
    assert [t["name"] for t in selected["tests"]] == ["test_b"]
    limited = frontend(code, max_tests=1)
    assert limited["stats"]["test_budget_exhausted"]
    with pytest.raises(ValueError):
        frontend(code, max_tests=-1)


def test_same_spelling_unresolved_receiver_is_not_resolved_evidence():
    data = extract_frontend([
        Source("main.py", "class Other:\n    def accepts(self, x):\n        return x < 3\n", "python"),
        Source("test_main.py", "def test_value(unknown):\n    assert unknown.accepts(2)\n", "python"),
    ])
    target = call_named(data, "unknown.accepts")["targets"][0]
    assert target["reason"] == "unique_name_candidate"
    assert not target["resolved"]
    assert not data["comparisons"][0]["relevance"][0]["resolved"]
