"""Source operators are exercised on independent, executable tiny programs."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from experimental.relation_search_go_ts import (
    _guest_factories, emit_neighbors, enrich, propose_neighbors, routing_templates,
)


def ts(code, path="tests/sample.test.ts"):
    return Source(path, code, "typescript")


def test_receiver_route_uses_factory_owner_not_variable_spelling():
    donor = ts('''import { make } from '../lib';
it('donor', () => { const depot=make(); const object=depot.obtain();
depot.pending.write(object, {n:1}); });''')
    target = ts('''import { make as start } from '../lib';
it('target', () => { const pool=start(); const handle=pool.obtain();
handle.write({a:4,b:5}); expect(handle.read()).toEqual({a:4,b:5}); });''', "tests/other.test.ts")
    rows = propose_neighbors(target, [donor], operators=["receiver_route"])
    assert len(rows) == 1
    assert rows[0]["edits"][0]["after"] == "pool.pending.write(handle, {a:4,b:5})"
    code, emitted = emit_neighbors(target, rows)
    assert code.count("it('target'") == 1
    assert "expect(handle.read()).toEqual({a:4,b:5})" in code
    assert rows[0]["oracle_status"].endswith("require_contract_review")


def test_unrelated_factory_and_shadowed_owner_do_not_supply_route():
    donor = ts('''import { make } from '../lib';
it('donor', () => { const w=make(); const v=w.obtain(); w.pending.write(v, 1); });''')
    other = ts('''import { make } from '../unrelated';
it('target', () => { const w=make(); const v=w.obtain(); v.write(1); });''')
    assert not propose_neighbors(other, [donor], operators=["receiver_route"])
    shadow = ts('''import { make, different } from '../lib';
it('target', () => { const w=make(); {const w=different(); const v=w.obtain(); v.write(1);} });''')
    assert not propose_neighbors(shadow, [donor], operators=["receiver_route"])


def test_record_edits_leave_expected_object_untouched():
    source = ts("it('t',()=>{ expect(run({mode:'fast'})).toEqual({mode:'fast'}); });")
    rows = propose_neighbors(source, operators=["record_delete", "argument_omit"])
    assert len(rows) == 2
    assert {row["edits"][0]["after"] for row in rows} == {"{}", "run()"}
    code, _ = emit_neighbors(source, rows)
    assert code.count("toEqual({mode:'fast'})") == 3


def test_computed_and_spread_keys_are_not_silently_deleted():
    source = ts("it('t',()=>{ run({[key]:1}); run({...defaults, x:1}); });")
    assert not propose_neighbors(source, operators=["record_delete"])


def test_numeric_rebinding_requires_lexical_binding_at_target():
    source = Source("sample_test.go", '''package sample
func TestX(t *testing.T) {
 n:=value()
 consume(n)
 if n+2 > 10 { t.Fatal("bad") }
 { later:=9; _=later+8 }
}
''', "go")
    rows = propose_neighbors(source, operators=["expression_rebind"])
    edits = [row["edits"][0] for row in rows]
    assert any(edit["before"] == "n" and edit["after"] == "n+2" for edit in edits)
    assert all("later" not in edit["after"] for edit in edits)


def test_go_record_field_delete_is_valid_go_syntax():
    source = Source("sample_test.go", '''package sample
func TestX(t *testing.T) { run(Config{Speed:2, Size:4}) }
''', "go")
    rows = propose_neighbors(source, operators=["record_delete"])
    assert {row["edits"][0]["after"] for row in rows} == {"Config{Size:4}", "Config{Speed:2}"}
    code, _ = emit_neighbors(source, rows)
    assert not Source(source.path, code, source.language).root.has_error


@pytest.mark.skipif(shutil.which("node") is None, reason="Node required")
def test_emitted_routed_test_exposes_partial_record_while_control_passes(tmp_path):
    # An intentionally incomplete buffer; ordinary write merges keys, pending
    # write returns its partial argument. The expected record is pre-existing.
    prelude = '''let failures=[]; let executed=[];
function it(name, f) {executed.push(name); try{f()}catch(e){failures.push(name)}}
function expect(value){return {toEqual(expected){if(JSON.stringify(value)!==JSON.stringify(expected))throw Error('different')}}}
function create(){return {get(){return {state:{a:0,b:0},write(v){Object.assign(this.state,v)},read(){return this.state}}},
 pending:{write(x,v){x.state=v}}}}
'''
    donor = ts(prelude + "it('shape',()=>{const s=create();const x=s.get();s.pending.write(x,{a:4});});")
    target = ts(prelude + "it('control',()=>{const s=create();const x=s.get();x.write({a:4});expect(x.read()).toEqual({a:4,b:0});});")
    rows = propose_neighbors(target, [donor], operators=["receiver_route"])
    assert len(rows) == 1
    code, emitted = emit_neighbors(target, rows)
    path = tmp_path / "test.js"
    path.write_text(code + "\nconsole.log(JSON.stringify({failures,executed}));")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["executed"] == ["control", emitted[0]["test_name"]]
    assert report["failures"] == [emitted[0]["test_name"]]


def test_emitter_rejects_source_change_and_keeps_anchor_identity():
    source = ts("it('t',()=>{run({x:1});});")
    rows = propose_neighbors(source, operators=["record_delete"])
    assert rows == propose_neighbors(source, operators=["record_delete"])
    with pytest.raises(ValueError, match="Frozen source"):
        emit_neighbors(ts(source.code + "\n"), rows)


def test_enrich_returns_existing_emitter_contract_without_mutating_corpus():
    source = ts("it('t',()=>{run({x:1});});")
    from anchor_retrieval.syntax import units
    unit = next(unit for unit in units(source)[0] if unit.test)
    span = {"path": source.path, "start_byte": unit.node.start_byte, "end_byte": unit.node.end_byte}
    corpus = {"language": "typescript", "sources": {source.path: {"code": source.code}},
              "tests": {"test-id": {"name": "t", "span": span}}}
    frozen = json.dumps(corpus, sort_keys=True)
    rows = enrich(corpus, budget=1)
    assert len(rows) == 1 and rows[0]["base_test_id"] == "test-id"
    assert rows[0]["edits"][0]["role"] == "input"
    assert json.dumps(corpus, sort_keys=True) == frozen


def test_constructor_wrap_transports_type_only_context_and_imports():
    donor = ts('''import { base, wrap, change } from '../lib';
test('types',()=>{const v=wrap(base(),change((argument)=>argument.length));});''', "tests/types.test-d.ts")
    target = ts('''import { base as create } from '../lib';
test('runtime',()=>{const x=create(); expect(run(x,'abcd')).toEqual('abcd');});''')
    rows = propose_neighbors(target, [donor], operators=["constructor_wrap"])
    assert len(rows) == 1
    assert rows[0]["relation_target"]["source_type_only"] is True
    assert rows[0]["edits"][0]["after"] == "wrap(create(),change((argument)=>argument.length))"
    assert {i["name"] for i in rows[0]["imports"]} == {"wrap", "change"}
    code, _ = emit_neighbors(target, rows)
    assert 'import { change } from "../lib";' in code
    assert code.count("toEqual('abcd')") == 2


def test_constructor_wrap_rejects_unbound_local_and_handles_import_alias():
    donor = ts('''import { base, wrap } from '../lib';
test('types',()=>{const external=5;const v=wrap(base(),external);});''')
    target = ts("import {base} from '../lib';test('runtime',()=>{const x=base();});")
    assert not propose_neighbors(target, [donor], operators=["constructor_wrap"])
    donor = ts("import {base,wrap} from '../lib';test('types',()=>{const v=wrap(base(),7);});")
    target = ts("import {base,wrap as decorate} from '../lib';test('runtime',()=>{const x=base();});")
    row, = propose_neighbors(target, [donor], operators=["constructor_wrap"])
    assert row["edits"][0]["after"] == "decorate(base(),7)" and row["imports"] == []


def test_unary_constructor_context_lifts_through_matching_record_field():
    donor = ts("""import { scalar, wrap, change } from '../lib';
test('types',()=>{const x=wrap(scalar(),change((v)=>v.length));});""", "tests/types.test-d.ts")
    target = ts("""import { scalar, record, other } from '../lib';
test('runtime',()=>{const x=record({word:scalar(), count:other()});});""")
    row, = propose_neighbors(target, [donor], operators=["constructor_field_lift"])
    assert row["edits"][0]["after"] == 'wrap(record({word:scalar(), count:other()}),change((v)=>({...v, "word": v["word"].length})))'
    assert row["relation_target"]["field"] == "word"
    assert row["evidence"]["rule"] == "unary_callback_lift_through_matching_record_field"
    assert "count" not in row["evidence"]["lifted_callback_body"]


def test_field_lifting_rejects_callback_calls_and_unrelated_scalar_factory():
    donor = ts("""import { scalar, wrap, change } from '../lib';
test('types',()=>{const x=wrap(scalar(),change((v)=>v.trim()));});""")
    target = ts("import {scalar,record} from '../lib';test('t',()=>{record({word:scalar()});});")
    assert not propose_neighbors(target, [donor], operators=["constructor_field_lift"])
    donor = ts("""import { scalar, wrap, change, validate } from '../lib';
test('types',()=>{const x=wrap(scalar(),validate(5),change((v)=>v.length));});""")
    assert not propose_neighbors(target, [donor], operators=["constructor_field_lift"])


def test_guest_factory_fragment_ignores_quoted_delimiters_and_rejects_variadic():
    code = 'build := func(seed) { marker := "}"; value := seed; return func(x) { return value+x } }'
    row, = _guest_factories(code)
    assert row["name"] == "build" and row["parameters"] == ["seed"]
    assert code[row["return_start"]:row["return_end"]] == 'func(x) { return value+x }'
    assert not _guest_factories('build := func(...x) { return func(){return 1} }')


def test_guest_result_container_clones_producer_and_reuses_source_host_view():
    source = Source("sample_test.go", '''package sample_test
import ("example.org/guest"; "testing")
func TestCalls(t *testing.T) {
 c := run(`build := func(seed) { n:=seed; return func(x){n+=x;return n} }`)
 result, err := c.Lookup("build").Object().Invoke(integer(3))
 assertNoError(t, err)
 check(t, 4, invoke(result,integer(1)))
 holder := c.Lookup("list").Object().(*guest.Vector)
 _=holder.Elements[0]
}
''', "go")
    rows = propose_neighbors(source, operators=["guest_result_container"])
    assert {row["relation_target"]["member"] for row in rows} == {0, 1}
    row = next(row for row in rows if row["relation_target"]["member"] == 0)
    code, _ = emit_neighbors(source, [row])
    assert 'return [func(x){n+=x;return n}]' in code
    assert '(result).(*guest.Vector).Elements[0]' in code
    assert 'check(t, 4,' in code
    assert row["evidence"]["host_view"]["suffix"] == '.(*guest.Vector).Elements[0]'


def test_alias_transport_uses_helper_and_container_bindings_not_api_names():
    source = Source("sample_test.go", '''package sample_test
import ("example.org/guest"; "testing")
func callable(t *testing.T, owner *guest.State, label string) *guest.Function {
 item:=owner.Lookup(label).Value()
 fn,ok:=item.(*guest.Function)
 assert.True(t,ok)
 return fn
}
func TestTransfer(t *testing.T) {
 a:=run(`build:=func(){n:=0;return func(){n++;return n}}; next:=build()`)
 old:=callable(t,a,"next")
 v,_:=old.Invoke(); assert.Equal(t,1,v)
 b:=run(`target:=undefined`)
 b.Assign("target",a.Lookup("next").Value())
 moved:=callable(t,b,"target")
 v,_=moved.Invoke(); assert.Equal(t,2,v)
 v,_=old.Invoke(); assert.Equal(t,2,v)
}
func TestContainer(t *testing.T) {
 bag:=value.(*guest.Vector)
 _=bag.Elements[0]
}
''', "go")
    row, = propose_neighbors(source, operators=["guest_alias_route"])
    replacements = [edit["after"] for edit in row["edits"]]
    assert any("[next, next]" in replacement for replacement in replacements)
    assert 'b.Lookup("target").Value().(*guest.Vector).Elements[0].(*guest.Function)' in replacements
    assert 'b.Lookup("target").Value().(*guest.Vector).Elements[1].(*guest.Function)' in replacements
    code, _ = emit_neighbors(source, [row])
    assert code.count("assert.Equal(t,2,v)") == 4
    assert row["oracle_status"].endswith("require_contract_review")


@pytest.mark.skipif(shutil.which("go") is None, reason="Go required")
def test_owner_prefix_keeps_state_setup_and_rebinds_observed_arithmetic(tmp_path):
    source = Source("sample_test.go", '''package sample
import "testing"
type store struct { end int }
type batch struct { start, count int }
func openStore() *store { return &store{} }
func (s *store) Batch() *batch { return &batch{start:s.end} }
func (b *batch) Add() { b.count++ }
func (s *store) Apply(b *batch) { s.end=b.start+b.count }
func (b *batch) Start() int { return b.start }
func (s *store) Ready(target int) bool { return target<=s.end }
func TestSource(t *testing.T) {
 d:=openStore()
 b:=d.Batch(); b.Add(); b.Add(); d.Apply(b)
 start:=b.Start()
 if start+2!=2 { t.Fatal(start+2) }
}
func TestTarget(t *testing.T) {
 d:=openStore()
 if d.Ready(999) { t.Fatal("future position reported ready") }
}
''', "go")
    rows = propose_neighbors(source, operators=["owner_prefix_rebind"])
    row, = [row for row in rows if row["test_name"] == "TestTarget" and "+2" in row["edits"][-1]["after"]]
    assert ".Apply(" in row["edits"][0]["after"]
    code, emitted = emit_neighbors(source, [row])
    (tmp_path / "sample_test.go").write_text(code)
    env = {**os.environ, "GO111MODULE": "off", "GOCACHE": str(tmp_path / "cache")}
    control = subprocess.run(["go", "test", "-run", "^Test(Source|Target)$"], cwd=tmp_path,
                             env=env, capture_output=True, text=True, timeout=60)
    assert control.returncode == 0, control.stdout + control.stderr
    generated = subprocess.run(["go", "test", "-run", "^" + emitted[0]["test_name"] + "$"],
                               cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert generated.returncode == 1
    assert "future position reported ready" in generated.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node required")
def test_sequence_endpoint_extension_preserves_payload_and_exposes_partial_overlap(tmp_path):
    prelude = '''let failures=[], active=[];
function it(name,body){active=[];try{body()}catch(e){failures.push(name)}}
function save(record){active.push(record.doc.split('\\n').filter(Boolean))}
function conflict(){const [base,a,b]=active;
 const first=(v)=>base.findIndex((x,i)=>x!==v[i]);
 return first(a)===first(b)}
function expect(value){return{toBe(other){if(value!==other)throw Error('wrong')}}}
'''
    source = ts(prelude + '''it('control',()=>{
save({doc:"a\\nb\\nc\\n"});
save({doc:"a\\nleft\\nc\\n"});
save({doc:"a\\nright\\nc\\n"});
expect(conflict()).toBe(true);
});''')
    rows = propose_neighbors(source, operators=["sequence_interval_extend"])
    row, = [row for row in rows if row["relation_target"]["intervals"] == [[0, 2], [1, 3]]]
    assert {edit["after"] for edit in row["edits"]} == {'"left\\nc\\n"', '"a\\nright\\n"'}
    assert row["evidence"]["runtime_relation_confirmed"] is False
    code, emitted = emit_neighbors(source, [row])
    path = tmp_path / "run.js"
    path.write_text(code + "\nconsole.log(JSON.stringify(failures));")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [emitted[0]["test_name"]]


def test_structured_route_supports_json_paths_and_preserves_existing_assertion():
    source = ts('''it('target',()=>{
const ancestor=parse('{"item":{"n":0}}');
const first=parse('{"item":{"n":0},"left":null}');
const second=parse('{"item":{"n":0},"right":true}');
expect(join(ancestor,first,second).conflicts).toHaveLength(0);
});
it('donor',()=>{parse('{"item":{"n":1}}');});''')
    rows = propose_neighbors(source, operators=["structured_literal_route"])
    assert len(rows) == 2
    assert all(row["relation_target"]["grammar"] == "json" for row in rows)
    assert all(row["relation_target"]["path_relations"] == ["disjoint"] for row in rows)
    code, _ = emit_neighbors(source, rows)
    assert code.count("toHaveLength(0)") == 3
    assert all(row["edits"][0]["after"] == '\'{"item":{"n":1}}\'' for row in rows)


def test_structured_route_keeps_xml_root_and_constructor_identity():
    source = ts('''it('target',()=>{
const a=load('<doc><item/></doc>');
const b=load('<doc><item/><left/></doc>');
const c=load('<doc><item/><right/></doc>');
expect(join(a,b,c)).toBe(true);
});
it('donor',()=>{load('<doc><item>text</item></doc>');
other('<doc><item attr="x"/></doc>');load('<unrelated><item/></unrelated>');});''')
    rows = propose_neighbors(source, operators=["structured_literal_route"])
    assert len(rows) == 2
    assert all(row["relation_target"]["path_relations"] == ["disjoint"] for row in rows)
    assert all(row["relation_target"]["change_kinds"] == [("change", "#text")] for row in rows)
    assert all("unrelated" not in row["edits"][0]["after"] and "attr" not in row["edits"][0]["after"] for row in rows)


def test_numeric_choices_align_from_typed_options_without_inventing_constants():
    source = Source("sample_test.go", '''package example
func TestDonor(t *testing.T) { s.Render(50, Settings{}); other.Render(900, Other{}) }
func TestTarget(t *testing.T) { got:=engine.Render("value",3,Settings{Flag:true}); check(t,got,"old") }
''', "go")
    rows = propose_neighbors(source, operators=["numeric_context_route"])
    target, = [row for row in rows if row["test_name"] == "TestTarget"]
    assert target["edits"][0]["before"] == "3"
    assert target["edits"][0]["after"] == "50"
    code, _ = emit_neighbors(source, [target])
    assert code.count('check(t,got,"old")') == 2
    assert all(row["relation_target"]["to"] != 900 for row in rows)


def test_history_dedup_requires_equal_non_test_definitions():
    from anchor_retrieval.syntax import units
    def corpus(helper_second):
        output = {"language": "go", "sources": {}, "tests": {}}
        for i, (suffix, body) in enumerate((("abcdef123456", "return 1"), ("fedcba654321", helper_second))):
            path = "sample_rh_" + suffix + "_test.go"
            code = ('package sample\nfunc helper_rh_' + suffix + '() int {' + body + '}\n'
                    'func TestInput_rh_' + suffix + '(t *testing.T) {consume(Config{Size:helper_rh_' + suffix + '(), Flag:true})}')
            source = Source(path, code, "go", "trajectory")
            unit = next(unit for unit in units(source)[0] if unit.test)
            output["sources"][path] = {"code": code, "origin": "trajectory", "written_path": "sample_test.go"}
            output["tests"][str(i)] = {"name": unit.name, "retrieval_rank": i,
                "span": {"path": path, "start_byte": unit.node.start_byte, "end_byte": unit.node.end_byte}}
        return output
    identical = enrich(corpus("return 1"), budget=100)
    changed = enrich(corpus("return 2"), budget=100)
    assert len(changed) == 2 * len(identical)
    assert all(len(row.get("equivalent_candidates", [])) == 1 for row in identical)


def test_local_oracle_accepts_go_expected_guard_without_changing_observer_or_body():
    from relation_search.oracle import _valid_assertion
    old = 'if got != want {\n t.Errorf("got %q want %q", got, want)\n}'
    fixed = 'if got != "complete result" {\n t.Errorf("got %q want %q", got, want)\n}'
    assert _valid_assertion(fixed, old, "got", "go")
    assert not _valid_assertion(fixed.replace('got !=', 'got =='), old, "got", "go")
    assert not _valid_assertion(fixed.replace('t.Errorf', 't.Skipf'), old, "got", "go")
    assert not _valid_assertion(fixed + '\nsideEffect()', old, "got", "go")
    assert not _valid_assertion(old.replace('want {', 'compute() {'), old, "got", "go")
    assert not _valid_assertion(old.replace('got != want', 'got != got'), old, "got", "go")


@pytest.mark.parametrize("name,offset", [("construct", 0), ("assemble", 37)])
def test_nested_expected_calls_and_their_private_definitions_are_frozen(name, offset):
    source = ts(f'''it('observation',()=>{{
const expected={name}({{n:{1+offset},flag:true}});
const shared={name}({{n:{2+offset},flag:true}});
expect(run(shared)).toEqual(expected);
expect(run(shared)).toEqual({name}({{n:{3+offset},flag:true}}));
expect(run(shared)).toEqual(shared);
}});''')
    rows = propose_neighbors(source, operators=["record_delete", "argument_omit"])
    assert rows
    expected_start = source.code.index("const expected=")
    expected_end = source.code.index(";", expected_start)
    nested_start = source.code.index("toEqual(" + name)
    nested_end = source.code.index(";", nested_start)
    for row in rows:
        for edit in row["edits"]:
            position = edit["span"]["start_byte"]
            assert not expected_start <= position < expected_end
            assert not nested_start <= position < nested_end
    assert any(edit["before"].startswith("{n:") for row in rows for edit in row["edits"])


def test_frontend_expected_role_freezes_go_comparison_initializer():
    source = Source("sample_test.go", '''package sample
func TestState(t *testing.T) {
 want:=build(Config{N:3,Flag:true})
 got:=build(Config{N:4,Flag:true})
 if got != want { t.Errorf("got %v want %v", got, want) }
}
''', "go")
    position = source.code.index("want {")
    observations = [{"kind": "print", "expected": None}, {"kind": "assertion", "expected": {"span": {
        "path": source.path, "start_byte": position, "end_byte": position+4}}}]
    rows = propose_neighbors(source, operators=["record_delete"], _observations=observations)
    assert len(rows) == 2
    assert all(row["edits"][0]["span"]["start_byte"] > source.code.index("got:=") for row in rows)


def test_enrich_forwards_cross_file_guest_container_donors():
    from anchor_retrieval.syntax import units
    target = Source("calls_test.go", '''package sample_test
import ("example.org/guest"; "testing")
func TestCalls(t *testing.T) {
 c:=run(`makeFn:=func(seed){n:=seed;return func(x){n+=x;return n}}`)
 result,err:=c.Lookup("makeFn").Object().Invoke(integer(3))
 assert.NoError(t,err); check(t,4,invoke(result,integer(1)))
}
''', "go")
    donor = Source("container_test.go", '''package sample_test
import "example.org/guest"
func TestView(t *testing.T) { bag:=value.(*guest.Vector); _=bag.Elements[0] }
''', "go")
    corpus = {"language": "go", "sources": {}, "tests": {}}
    for source in (target, donor):
        corpus["sources"][source.path] = {"code": source.code}
        unit = next(unit for unit in units(source)[0] if unit.test)
        corpus["tests"][unit.name] = {"name": unit.name, "span": {
            "path": source.path, "start_byte": unit.node.start_byte, "end_byte": unit.node.end_byte}}
    rows = enrich(corpus, budget=128)
    assert any(row["operator"] == "guest_result_container" and row["base_test_id"] == "TestCalls" for row in rows)


@pytest.mark.parametrize("name,offset", [("Position", 0), ("Index", 41)])
def test_owner_prefix_prunes_proved_named_scalar_mismatch(name, offset):
    from anchor_retrieval.syntax import units, walk, child, CALLS
    from experimental.relation_search_go_ts import _go_call_type_facts
    source = Source("sample_test.go", f'''package sample
type {name} uint64
type Alias = int
type state struct{{}}
func open() *state {{return &state{{}}}}
func (s *state) Value() {name} {{return {2+offset}}}
func (s *state) Pair() ({name}, int) {{return {2+offset}, {4+offset}}}
func (s *state) Good(x {name}) {{}}
func (s *state) Bad(x int) {{}}
func (s *state) Opaque(x any) {{}}
func TestProducer(t *testing.T) {{ s:=open(); n:=s.Value(); assert.Equal(t,{2+offset},n); assert.Equal(t,{4+offset},n+2) }}
func TestPair(t *testing.T) {{ s:=open(); _,n:=s.Pair(); assert.Equal(t,{6+offset},n+2) }}
func TestConsumer(t *testing.T) {{ s:=open(); s.Good({900+offset}); s.Bad({900+offset}); s.Opaque({900+offset}) }}
''', "go")
    corpus = {"language": "go", "sources": {source.path: {"code": source.code}},
              "tests": {"t": {"span": {"path": source.path}}}}
    frontend = {"functions": [], "calls": []}
    for unit in units(source)[0]:
        frontend["functions"].append({"id": unit.name, "span": {"path": source.path,
            "start_byte": unit.node.start_byte, "end_byte": unit.node.end_byte},
            "parameters": [{"index": i, "type": unit.param_types.get(p)} for i,p in enumerate(unit.params)]})
    for node in walk(source.root):
        if node.type not in CALLS:
            continue
        text = source.text(node)
        method = next((m for m in ("Value", "Pair", "Good", "Bad", "Opaque") if text.startswith("s."+m+"(")), None)
        if method:
            frontend["calls"].append({"span": {"path": source.path, "start_byte": node.start_byte,
                "end_byte": node.end_byte}, "targets": [{"function_id": method, "resolved": True}]})
    facts = _go_call_type_facts(corpus, frontend)
    all_rows = propose_neighbors(source, operators=["owner_prefix_rebind"], _call_types=facts)
    rows = [row for row in all_rows if row["evidence"]["source_test"] == "TestProducer"]
    good = source.code.index("s.Good(")
    bad = source.code.index("s.Bad(")
    opaque = source.code.index("s.Opaque(")
    assert rows
    assert any(row["edits"][0]["span"]["start_byte"] == good for row in rows)
    assert not any(row["edits"][0]["span"]["start_byte"] == bad for row in rows)
    assert any(row["edits"][0]["span"]["start_byte"] == opaque for row in rows)
    assert {row["evidence"]["type_check"]["status"] for row in rows} == {"known_compatible", "compiler_required"}
    pair_rows = [row for row in all_rows if row["evidence"]["source_test"] == "TestPair"]
    assert any(row["edits"][0]["span"]["start_byte"] == bad and
               row["evidence"]["type_check"]["status"] == "compiler_required" for row in pair_rows)


@pytest.mark.parametrize("key,prefix", [("doc", "a"), ("renamed", "shifted")])
def test_shape_schedule_reaches_distinct_orders_before_repeated_source_contexts(key, prefix):
    sources = []
    for index in range(12):
        lines = [prefix + str(index+j) for j in range(3)]
        base = "\\n".join(lines)+"\\n"
        left = "\\n".join([lines[0], "left", lines[2]])+"\\n"
        right = "\\n".join([lines[0], "right", lines[2]])+"\\n"
        sources.append(f'''it('trial{index}',()=>{{
save({{{key}:"{base}"}});save({{{key}:"{left}"}});save({{{key}:"{right}"}});
expect(compare()).toBe(true);
}});''')
    source = ts("\n".join(sources))
    rows = propose_neighbors(source, operators=["sequence_interval_extend"], budget=8)
    profiles = [tuple(row["relation_target"]["profile"]) for row in rows]
    assert len(set(profiles[:4])) == 4
    assert (-1, -1, 1, -1) in profiles  # strict partial, independent of payload/key spelling
    all_rows = propose_neighbors(source, operators=["sequence_interval_extend"], budget=1000)
    assert len(all_rows) > len(rows)  # Diversity schedules; it does not discard distinct contexts.


def test_typescript_history_dedup_preserves_enclosing_hooks_and_local_fixtures():
    from anchor_retrieval.syntax import units
    def build(second_hook):
        corpus = {"language": "typescript", "sources": {}, "tests": {}}
        for index, value in enumerate((1, second_hook)):
            path = f"tests/rh_{index}_sample.test.ts"
            code = f'''describe('scope',()=>{{
let fixture; beforeEach(()=>{{fixture={value}}});
it('exercise',()=>{{ run({{n:4,flag:true}},fixture); }});
}});'''
            source = ts(code, path)
            unit = next(unit for unit in units(source)[0] if unit.test)
            corpus["sources"][path] = {"code": code, "origin": "trajectory", "written_path": "tests/sample.test.ts"}
            corpus["tests"][str(index)] = {"name": unit.name, "retrieval_rank": index, "span": {
                "path": path, "start_byte": unit.node.start_byte, "end_byte": unit.node.end_byte}}
        return corpus
    same = enrich(build(1), budget=128)
    different = enrich(build(2), budget=128)
    assert same and len(different) == len(same)*2
    assert all(len(row["equivalent_candidates"]) == 1 for row in same)


@pytest.mark.parametrize("fields,offset", [(('a','b'),0), (('renamed','other'),50)])
def test_receiver_schedule_preserves_definition_invocation_key_relations(fields, offset):
    a,b = fields
    donor = ts("import {make} from '../lib';it('donor',()=>{const owner=make();const item=owner.obtain();owner.pending.write(item,1)});")
    bodies = [("absent","Options"),("empty","Options({})"),
              ("equal",f"Options({{{a}:{1+offset},{b}:true}})"),
              ("strict_subset",f"Options({{{a}:{2+offset}}})")]
    source = ts("import {make,shape} from '../lib';" +
        f"const Options=shape({{{a}:{offset},{b}:false}});" +
        "\n".join(f"it('{kind}',()=>{{const owner=make();const item=owner.obtain();item.write({argument});}});"
                  for kind,argument in bodies))
    rows = propose_neighbors(source,[donor],operators=["receiver_route"],budget=4)
    assert {row["relation_target"]["profile"][0][-1] for row in rows} == {kind for kind,_ in bodies}
    assert all(row["evidence"]["bound_record_relations"][0]["definition_keys"] == sorted(fields) for row in rows)
    subset = next(row for row in rows if row["relation_target"]["profile"][0][-1] == "strict_subset")
    assert subset["evidence"]["bound_record_relations"][0]["invocation_keys"] == [a]
