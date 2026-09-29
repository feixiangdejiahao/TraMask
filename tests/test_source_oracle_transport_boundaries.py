"""Invented counterexamples for source-anchored oracle reuse, no pilot data."""
from anchor_retrieval.syntax import Source, walk
from generic_composition.corpus import build_corpus, expected_atoms
from experimental.semantic_transport import oracle
from experimental.semantic_transport.proposals import generate
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.oracle_evidence import build_evidence


def test_exact_frame_source_examples_do_not_prove_a_new_input_relation(tmp_path):
    code = '''def render(text):
    return "SPECIAL" if text == "b!;" else text
def test_plain():
    assert render("a;") == "a;"
def test_marked():
    assert render("a!;") == "a!;"
def test_other():
    assert render("b;") == "b;"
'''
    (tmp_path/'test_source.py').write_text(code)
    proposed = generate(build_corpus(tmp_path,'python'))
    candidate = next(c for c in proposed['candidates'] if ("render('b!;')" in c['preview_body'] or 'render("b!;")' in c['preview_body'])
                     and c.get('witnesses') and not c.get('projection'))
    check = oracle.validate_completions({'completions':[dict(candidate_id=candidate['id'],observe=0,
        expected='arg[0]',guard=None)]},[candidate])
    assert check['accepted'] and check['accepted'][0]['witnesses_checked']==1
    namespace = {}
    exec(compile(code,'invented source','exec'),namespace)
    for test in ('test_plain','test_marked','test_other'):
        namespace[test]()
    assert namespace['render']('b!;')=='SPECIAL'
    assert check['accepted'][0]['literal']=="'b!;'"
    # Accepted means source-consistent hypothesis, not a new-input oracle proof.


def test_complete_prefix_matching_rejects_even_unused_literal_setup(tmp_path):
    code = '''def render(text): return text
def test_plain():
    assert render("a;") == "a;"
def test_marked():
    unused = 0
    assert render("a!;") == "a!;"
def test_other():
    assert render("b;") == "b;"
'''
    (tmp_path/'test_source.py').write_text(code)
    proposed = generate(build_corpus(tmp_path,'python'))
    assert proposed['candidates']
    assert proposed['source_witnesses']['attached']==0
    # This motivates a supported observation prefix, not unrestricted oracle reuse.


def test_aggregate_expected_projection_is_not_entailment_for_unknown_value_types():
    source=Source('test_source.py', "def test_case():\n    assert result == {'count': 7}\n", 'python')
    expected=next(n for n in walk(source.root) if n.type=='dictionary')
    atoms=expected_atoms(source,expected)
    assert len(atoms)==1 and atoms[0]['projection']==['count']
    assert atoms[0]['expected']['text']=='7'

    class Result:
        def __eq__(self,other): return other=={'count':7}
        def __getitem__(self,key): return 99

    result=Result()
    assert result=={'count':7}
    assert result['count']!=7
    # Source syntax decomposition is useful evidence, not an automatic field oracle.


def test_equal_callee_arguments_and_projection_can_have_different_object_history():
    class Counter:
        def __init__(self): self.count=0
        def step(self): self.count+=1
        def read(self): return {'count':self.count}
    donor=Counter()
    donor.step()
    assert donor.read()['count']==1
    left,right=Counter(),Counter()
    left.step()
    assert right.read()['count']==0
    assert Counter.read==type(donor).read==type(right).read
    # Both calls have no explicit args and use the same count projection.
    # Matching those fields alone loses receiver identity and prior writes.
    before=left.read()['count']
    left.step()
    after=left.read()['count']
    assert (before,after)==(1,2)


def test_current_source_control_retrieval_is_evidence_not_full_argument_alignment():
    code='''def render(text, mode): return text + str(mode)
def test_base():
    assert render("a", 0) == "a0"
def test_source():
    assert render("b", 1) == "b1"
'''
    source=Source('test_source.py',code,'python')
    frontend=extract_frontend([source]);corpus=to_emitter_corpus(frontend)
    test_id=next(k for k,v in corpus['tests'].items() if v['name']=='test_base')
    start=code.index('"a"',corpus['tests'][test_id]['span']['start_byte'])
    candidate=dict(id='invented',base_test_id=test_id,imports=[],source_test_ids=[],edits=[dict(
        span=dict(path=source.path,start_byte=start,end_byte=start+3),before='"a"',after='"b"')])
    evidence=build_evidence(corpus,frontend,candidate)
    assert any(c['test_id'].endswith(':test_source') for c in evidence['controls'])
    assert 'render("b", 1)' in evidence['rendered']
    namespace={};exec(compile(code,'invented source','exec'),namespace)
    assert namespace['render']('b',0)=='b0'
    assert namespace['render']('b',0)!='b1'
