"""Documented option defaults constrain an executable metamorphic change."""
import copy
import json
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.documented_defaults import extract, generate


DOC = '''# Widget
## Methods
### `read(...)`

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `layout` | `stable` or `compact` | `stable` | Select the layout. |
| `enabled` | `boolean` | `true` | Enable conversion. |
'''
CODE = '''class Widget {
  read(options = {}) { return options.layout === 'stable' ? 7 : 0; }
}
test('known',()=>{
  const widget = new Widget();
  expect(widget.read({layout:'stable'})).toBe(7);
});
'''


def fixture(code=CODE, documents=None):
    frontend = extract_frontend([Source('sample.ts', code, 'typescript')])
    corpus = to_emitter_corpus(frontend)
    evidence = extract(documents or [dict(path='docs/widget.md', text=DOC)])
    return corpus, frontend, evidence


def test_documentation_default_survives_a_wrong_implementation_and_executes():
    corpus, frontend, evidence = fixture()
    result = generate(corpus, frontend, evidence)
    assert result['total_candidates'] == 2, result
    assert [c['edits'][0]['after'] for c in result['candidates']] == ['{}', '']
    material = emit(corpus, result['candidates'])
    assert material['unsupported'] == []
    if not shutil.which('node'):
        pytest.skip('Node is required for the independent execution')
    driver = '''const results=[];
function test(name,fn){try{fn();results.push([name,'pass'])}catch(e){results.push([name,'fail'])}}
function expect(value){return {toBe: other=>{if(value!==other)throw Error('mismatch')}}}
'''
    run = subprocess.run(['node', '-e', driver + material['files']['sample.ts']
                          + '\nconsole.log(JSON.stringify(results));'],
                         capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr
    statuses = dict(json.loads(run.stdout))
    assert statuses['known'] == 'pass'
    assert all(statuses[row['test_name']] == 'pass' for row in material['controls'])
    assert all(statuses[row['test_name']] == 'fail' for row in material['obligations'])
    assert all(not c['documented_default']['implementation_bodies_used_as_oracle']
               for c in result['candidates'])


def test_documented_field_must_equal_the_literal_input_and_match_method_scope():
    corpus, frontend, evidence = fixture(CODE.replace("layout:'stable'", "layout:'compact'"))
    assert not generate(corpus, frontend, evidence)['candidates']
    corpus, frontend, evidence = fixture(documents=[dict(path='docs/widget.md', text=DOC.replace('read(...)', 'write(...)'))])
    assert not generate(corpus, frontend, evidence)['candidates']


def test_each_field_omission_retains_other_literal_options_and_all_assertions():
    corpus, frontend, evidence = fixture(CODE.replace("layout:'stable'", "layout:'stable',enabled:true"))
    result = generate(corpus, frontend, evidence)
    assert {c['edits'][0]['after'] for c in result['candidates']} == {"{layout:'stable'}", '{enabled:true}'}
    assert all(c['operator'] == 'documented_default_field' for c in result['candidates'])
    material = emit(corpus, result['candidates'])
    assert material['files']['sample.ts'].count('.toBe(7)') == 4


@pytest.mark.parametrize('argument', [
    "{...defaults,layout:'stable'}", "{layout:'stable',layout:'stable'}",
    "{layout:'stable',value:sideEffect()}", "{[name]:'stable'}", "{__proto__:null,layout:'stable'}",
])
def test_dynamic_effectful_or_ambiguous_records_are_not_transformed(argument):
    corpus, frontend, evidence = fixture(CODE.replace("{layout:'stable'}", argument))
    assert not generate(corpus, frontend, evidence)['candidates']


def test_conflicting_defaults_disable_only_the_conflicting_field():
    evidence = extract([dict(path='docs/current.md', text=DOC),
                        dict(path='docs/old.md', text=DOC.replace('| `stable` | Select', '| `compact` | Select'))])
    assert [row['field'] for row in evidence['facts']] == ['enabled']
    assert evidence['conflicts'][0]['field'] == 'layout'


def test_no_default_authority_from_code_blocks_or_unscoped_tables():
    evidence = extract([dict(path='docs/unscoped.md', text='\n'.join(DOC.splitlines()[3:])),
                        dict(path='docs/code.md', text='```md\n' + DOC + '\n```')])
    assert evidence['facts'] == []


def test_argument_omission_requires_declared_empty_object_default():
    corpus, frontend, evidence = fixture(CODE.replace('options = {}', 'options'))
    candidates = generate(corpus, frontend, evidence)['candidates']
    assert len(candidates) == 1 and candidates[0]['edits'][0]['after'] == '{}'


def test_unknown_default_is_not_a_string_guess():
    evidence = extract([dict(path='docs/widget.md', text=DOC.replace('`stable` or `compact`', '`string`'))])
    assert [r['field'] for r in evidence['facts']] == ['enabled']
    assert evidence['rejected'][0]['reason'] == 'nonliteral_or_conditional_default'


def test_wrong_frontend_source_is_rejected():
    corpus, frontend, evidence = fixture()
    corpus = copy.deepcopy(corpus)
    corpus['sources']['sample.ts']['code'] += '\nconst extra=1;'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        generate(corpus, frontend, evidence)


def test_generation_ignores_candidate_labels_and_keeps_its_inputs_unchanged():
    corpus, frontend, evidence = fixture()
    before = copy.deepcopy((corpus, frontend, evidence))
    result = generate(corpus, frontend, evidence)
    assert (corpus, frontend, evidence) == before
    corpus['evaluation'] = {'preferred_case': 'anything', 'positive': False}
    assert result == generate(corpus, frontend, evidence)
