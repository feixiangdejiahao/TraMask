"""Parsed source-data toys only; none of the miniature subjects are executed."""
import copy
import difflib

import pytest

from anchor_retrieval.syntax import Source
from prototypes.patch_observation_priority import select as v1_select
from prototypes.patch_observation_priority_v2 import Analyzer, select
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture(old='def compute(value):\n    return value * 2\n', *, body=None,
            imports='compute', language='python', test=None):
    new = old.replace('* 2', '* 3')
    if language == 'python':
        path = 'library.py'; test_path = 'test_source.py'
        body = body or 'value=11\nresult=compute(value)\nassert result==22'
        text = test or ('from library import ' + imports + '\ndef test_case():\n'
                        + ''.join('    '+line+'\n' for line in body.splitlines()))
    elif language == 'go':
        path = 'library.go'; test_path = 'source_test.go'; text = test
    else:
        path = 'library.ts'; test_path = 'source.test.ts'; text = test
    patch = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile='a/'+path, tofile='b/'+path, n=0))
    front = extract_frontend([Source(path, new, language), Source(test_path, text, language)], patch=patch)
    return to_emitter_corpus(front), front, patch


def candidate(corpus, before='11', after='19', identifier='input'):
    base = next(iter(corpus['tests'])); extent = corpus['tests'][base]['span']
    raw = corpus['sources'][extent['path']]['code'].encode()
    start = raw.index(before.encode(), extent['start_byte'])
    return dict(id=identifier, base_test_id=base, operator='input', imports=[], edits=[dict(
        span=dict(path=extent['path'], start_byte=start, end_byte=start+len(before.encode())),
        before=before, after=after, role='input')])


def facts(c, f, p, row, **kwargs):
    return select(c, f, [row], p, **kwargs)['ranking'][0]['evidence']


@pytest.mark.parametrize('mode', ['strict', 'may'])
@pytest.mark.parametrize('old,body,imports', [
    ('def compute(value):\n    return value * 2\n', None, 'compute'),
    ('def compute(value):\n    return value * 2\n', 'value=11\nfor label in [0]:\n    pass\nresult=compute(value)\nassert result==22', 'compute'),
    ('def compute(value):\n    return value * 2\n', 'value=11\nif value:\n    unused=0\nresult=compute(value)\nassert result==22', 'compute'),
    ('def compute(value):\n    return opaque(value) * 2\n', None, 'compute'),
    ('def compute(value,extra=1):\n    return value * 2\n', None, 'compute'),
    ('def compute(value):\n    return value * 2\n', 'value=11\nresult=compute(value=value)\nassert result==22', 'compute'),
    ('class Box:\n    def compute(self,value):\n        return value * 2\n', 'box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22', 'Box'),
    ('def compute(value):\n    return value * 2\ndef neutral(value):\n    return value\n', 'value=11\ncompute=neutral\nresult=compute(value)\nassert result==22', 'compute,neutral'),
    ('def compute(value): note="old"; return value * 2\n', None, 'compute'),
])
def test_cache_only_preserves_complete_v1_ranking_and_evidence(mode, old, body, imports):
    c, f, p = fixture(old, body=body, imports=imports)
    rows = [candidate(c, after=after, identifier='c'+str(i)) for i, after in enumerate(['19', '200', '3'])]
    untouched = copy.deepcopy((c, f, rows))
    one = v1_select(c, f, rows, p, budget=2, mode=mode)
    two = select(c, f, rows, p, budget=2, mode=mode, disable_receiver_fix=True)
    assert {k: v for k, v in one.items() if k not in {'policy', 'policy_sha256'}} == {
        k: v for k, v in two.items() if k not in {'policy', 'policy_sha256'}}
    assert (c, f, rows) == untouched


@pytest.mark.parametrize('language,old,text', [
    ('go', 'package sample\nfunc compute(value int) int {return value * 2}\n',
     'package sample\nimport "testing"\nfunc TestCase(t *testing.T){value:=11;result:=compute(value);if result!=22{t.Error(result)}}\n'),
    ('typescript', 'export function compute(value:number):number{return value * 2;}\n',
     'import {compute} from "./library";test("case",()=>{let value=11;let result=compute(value);expect(result).toBe(22);});\n'),
])
def test_cache_only_keeps_other_language_interfaces(language, old, text):
    c, f, p = fixture(old, language=language, test=text)
    row = candidate(c)
    assert select(c, f, [row], p, disable_receiver_fix=True)['ranking'] == v1_select(c, f, [row], p)['ranking']


@pytest.mark.parametrize('first', ['self', 'cls', 'owner'])
def test_proved_instance_binding_uses_position_and_preserves_receiver(first):
    old = f'class Box:\n    def compute({first},value):\n        return value * 2\n'
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22')
    row = candidate(c)
    assert not facts(c, f, p, row, disable_receiver_fix=True)['strong_priority']
    result = facts(c, f, p, row)
    assert result['strong_priority'] and result['may_priority']
    assert result['witnesses'][0]['call_chain'][0]['resolution'] == 'source_constructor_receiver'


@pytest.mark.parametrize('first', ['self', 'owner'])
def test_reading_actual_receiver_remains_unknown(first):
    old = f'class Box:\n    def compute({first},value):\n        return {first}.scale * value * 2\n'
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22')
    result = facts(c, f, p, candidate(c))
    assert not result['strong_priority']
    assert any(reason.startswith('heap_or_unknown_dependency:') for reason in result['unknowns'])


def test_implicit_receiver_does_not_turn_keyword_only_formal_into_positional():
    old = 'class Box:\n    def compute(owner,*,value):\n        return value * 2\n'
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22')
    result = facts(c, f, p, candidate(c))
    assert not result['strong_priority']
    assert 'non_exact_argument_binding' in result['unknowns']


def test_staticmethod_keeps_all_explicit_arguments():
    old = 'class Box:\n    @staticmethod\n    def compute(value):\n        return value * 2\n'
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22')
    assert facts(c, f, p, candidate(c))['strong_priority']


def test_classmethod_binds_receiver_and_explicit_value_separately():
    old = 'class Box:\n    @classmethod\n    def compute(cls,value):\n        return value * 2\n'
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22')
    assert facts(c, f, p, candidate(c))['strong_priority']


def test_unknown_descriptor_does_not_claim_bound_method():
    old = 'class Box:\n    @custom\n    def compute(owner,value):\n        return value * 2\n'
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22')
    result = facts(c, f, p, candidate(c))
    assert not result['strong_priority']
    assert 'decorator_binding_unknown' in result['unknowns']


@pytest.mark.parametrize('decorator', ['classmethod', 'staticmethod'])
def test_class_namespace_shadow_is_not_a_builtin_descriptor(decorator):
    old = (f'class Box:\n    {decorator}=custom\n    @{decorator}\n'
           '    def compute(owner,value):\n        return value * 2\n')
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22')
    result = facts(c, f, p, candidate(c))
    assert not result['strong_priority']
    assert 'decorator_binding_unknown' in result['unknowns']


def test_explicit_unbound_call_does_not_delete_first_formal():
    old = 'class Box:\n    def compute(owner,value):\n        return value * 2\n'
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=Box.compute(box,value)\nassert result==22')
    result = facts(c, f, p, candidate(c))
    assert result['strong_priority']
    assert result['witnesses'][0]['call_chain'][0]['resolution'] == 'import_symbol'


def test_equal_length_call_replacement_cannot_reuse_previous_candidate_binding():
    old = ('class Box:\n    def compute(self,value):\n        return value * 2\n'
           '    def neutral(self,value):\n        return value\n')
    c, f, p = fixture(old, imports='Box', body='box=Box()\nvalue=11\nresult=box.compute(value)\nassert result==22')
    analyzer = Analyzer(c, f, p)
    first = candidate(c)
    changed = candidate(c, 'compute', 'neutral', 'changed_callee')
    assert analyzer.evidence(first)['strong_priority']
    assert not analyzer.evidence(changed)['may_priority']
    assert analyzer.evidence(first)['strong_priority']


def test_many_observations_reuse_one_call_binding_per_mode(monkeypatch):
    import prototypes.patch_observation_priority_v2 as module
    original = module._resolved_targets; count = []
    def counted(*args, **kwargs):
        count.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, '_resolved_targets', counted)
    c, f, p = fixture(body='value=11\nresult=compute(value)\n'+'\n'.join(['assert result==22']*32))
    result = facts(c, f, p, candidate(c), disable_receiver_fix=True)
    assert result['strong_priority']
    assert len(result['witnesses']) == 32
    # Exact and may bindings are separate; no resolution repeats for each q.
    assert len(count) == 2
