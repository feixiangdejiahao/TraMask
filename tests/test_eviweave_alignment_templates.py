from eviweave.alignment import TermIndex
from eviweave.alignment_templates import TemplateProjection, callee_members, term_template, typed_reporting_values
from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.relational_alignment import RelationalAlignmentIndex


def compare(left, right, name='use'):
    sources = {}
    for source, text in [('a', left), ('b', right)]:
        graph = SourceGraph({'id': source, 'path': 'test.py', 'raw': text.encode()})
        assert not graph.issues
        sources[source] = graph, BehaviorIndex(graph)
    index = RelationalAlignmentIndex(sources, {s: set(range(len(g.nodes))) for s, (g, _) in sources.items()})
    keys = [next(k for k, o in index.operations.items() if k[0] == s and o['name'] == name) for s in sources]
    profiles = [index.profile(k) for k in keys]
    projection = TemplateProjection(index)
    return index, [projection.profile(p['components'], 'numbers') for p in profiles]


def test_numeric_values_share_comparison_without_erasing_literal_bindings():
    _, profiles = compare('use(10,10)\n', 'use(20,20)\n')
    assert profiles[0] == profiles[1]
    _, profiles = compare('use(10,10)\n', 'use(20,30)\n')
    assert profiles[0] != profiles[1]


def test_object_identity_and_operator_changes_are_not_numeric_parameters():
    _, profiles = compare('a=[]\nuse(a,a)\n', 'a=[]\nb=[]\nuse(a,b)\n')
    assert profiles[0] != profiles[1]
    _, profiles = compare('if x>10:\n use(x)\n', 'if x<20:\n use(x)\n')
    assert profiles[0] != profiles[1]


def test_field_keys_survive_aggressive_string_parameterisation():
    def key(text):
        graph = SourceGraph({'id': 's', 'path': 'test.py', 'raw': text.encode()})
        return term_template(TermIndex(graph).term([0, len(text)]), strings=True)[0]
    assert key("{'a': 'hello'}") == key("{'a': 'world'}")
    assert key("{'a': 'hello'}") != key("{'b': 'hello'}")


def test_opaque_program_string_collision_is_exposed_by_the_ablation():
    def key(text, strings):
        graph = SourceGraph({'id': 's', 'path': 'test.py', 'raw': text.encode()})
        return term_template(TermIndex(graph).term([0, len(text)]), strings=strings)[0]
    a, b = '"x = 1"', '"raise Error()"'
    assert key(a, False) != key(b, False)
    assert key(a, True) == key(b, True)


def test_direct_method_access_is_attached_but_standalone_read_remains():
    index, _ = compare('x=[]\nx.append(1)\nf=x.append\n', 'y=[]\ny.append(2)\n', name='append')
    aliases = callee_members(index)
    assert len(aliases) == 2
    assert all(index.operations[a]['kind'] == 'member_read' and index.operations[b]['kind'] == 'call' for a, b in aliases.items())
    assert len([k for k, o in index.operations.items() if o['kind'] == 'member_read' and k not in aliases]) == 1


def test_short_expression_queries_do_not_change_enclosing_terms():
    raw = b'package p\nfunc f(){r:=int64(-2);use(r)}\n'
    graph = SourceGraph({'id': 's', 'path': 'test.go', 'raw': raw})
    start = raw.index(b'int64(-2)')
    negative = raw.index(b'-2')
    whole = TermIndex(graph).term([start, start+9])
    parts_first = TermIndex(graph)
    assert parts_first.term([negative, negative+2]).kind == 'unary_expression'
    assert parts_first.term([start, start+9]) == whole
    # Non-AST source intervals also have a separate cache from parsed nodes.
    parts_first.term([start+1, start+9])
    assert parts_first.term([start, start+9]) == whole


def test_test_handle_is_not_a_subject_value_connection():
    text='''package p
import tt "testing"
func TestX(t *tt.T) {
  expectRun(t, "a=1", 1)
  expectRun(t, "b=2", 2)
}
'''
    graph=SourceGraph({'id':'s','path':'test.go','raw':text.encode()})
    sources={'s':(graph,BehaviorIndex(graph))}
    reporting=typed_reporting_values(sources)
    assert len(reporting)==1
    index=RelationalAlignmentIndex(sources,{'s':set(range(len(graph.nodes)))})
    key=next(k for k,o in index.operations.items() if o['name']=='expectRun')
    original=index.profile(key);projected=index.profile(key,reporting_values=reporting)
    assert original['neighbors']
    assert not projected['neighbors']
    assert projected['ports']==original['ports']
    other=SourceGraph({'id':'s','path':'test.go','raw':text.replace('"testing"','"example/testing"').encode()})
    assert not typed_reporting_values({'s':(other,BehaviorIndex(other))})
