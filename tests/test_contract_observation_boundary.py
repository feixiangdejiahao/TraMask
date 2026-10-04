import copy

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import contract_observation_boundary as relation


ISSUE = ('Children created by a local owner report the same presence before and after '
         'the owner commits queued changes. Presence reads are repeatable and do not change state.')
CODE = '''import { expect, it } from 'vitest';
import { createOwner, token } from './api';
const Flag = token();
it('committed presence', () => {
    const owner = createOwner();
    const entity = owner.spawn();
    owner.add(entity, Flag);
    owner.queue.commit();
    expect(entity.has(Flag)).toBe(true);
    expect(entity.has(Flag)).toBe(true);
});
'''


def fixture(code=CODE, *, origin='repository'):
    source = Source('example.test.ts', code, 'typescript', origin)
    frontend = extract_frontend([source]); corpus = to_emitter_corpus(frontend)
    catalog = relation.catalog(corpus, frontend)
    return source, corpus, frontend, catalog


def ir_for(catalog):
    evidence = [relation.receipt('issue.md', ISSUE, 0, len(ISSUE.encode()))]
    return dict(version=relation.IR_VERSION, relations=[
        relation.relation_template(catalog['opportunities'][0], evidence)])


def test_constructs_same_bound_receiver_observation_and_preserves_entire_test():
    source, corpus, frontend, catalog = fixture()
    assert catalog['total_opportunities'] == 1, catalog
    pattern = catalog['opportunities'][0]['pattern']
    assert pattern['owner_relation'] == {'kind': 'created_by_owner', 'creator_path': ['spawn']}
    ir = ir_for(catalog); before = copy.deepcopy((corpus, frontend, ir))
    result = relation.generate(corpus, frontend, ISSUE, ir)
    assert result['total_candidates'] == 1
    candidate = result['candidates'][0]
    changed = candidate['edits'][0]['after']
    assert changed.startswith('const _boundaryObservation_')
    assert changed.count('entity.has(Flag)') == 3
    assert changed.index('const ') < changed.index('owner.queue.commit()')
    assert 'typeof _boundaryObservation_' in changed and '=== "boolean"' in changed
    material = emit(corpus, [candidate])
    assert not material['unsupported']
    generated = material['files'][source.path]
    assert not Source(source.path, generated, 'typescript').root.has_error
    assert generated.count('expect(entity.has(Flag)).toBe(true)') == 6
    assert (corpus, frontend, ir) == before


def test_same_binding_is_distinct_from_child_receiver_relation():
    _, corpus, frontend, catalog = fixture(CODE.replace('entity.has(Flag)', 'owner.has(Flag)'))
    assert catalog['total_opportunities'] == 1, catalog
    assert catalog['opportunities'][0]['pattern']['owner_relation']['kind'] == 'same_binding'
    result = relation.generate(corpus, frontend, ISSUE, ir_for(catalog))
    assert len(result['candidates']) == 1


@pytest.mark.parametrize('extra', [
    'const alias = entity;',
    'const alias = { entity };',
    'unknown(entity);',
    'entity = owner.spawn();',
    'const later = () => entity.has(Flag);',
])
def test_aliases_rebindings_unknown_escapes_and_callbacks_are_rejected(extra):
    _, _, _, catalog = fixture(CODE.replace('    owner.queue.commit();', '    '+extra+'\n    owner.queue.commit();'))
    assert not catalog['opportunities'], catalog


def test_same_method_name_on_another_owner_does_not_establish_identity():
    code = CODE.replace('const entity = owner.spawn();', 'const other = createOwner();\n    const entity = other.spawn();')
    _, _, _, catalog = fixture(code)
    assert not catalog['opportunities']
    assert catalog['rejection_counts'].get('observer_receiver_belongs_to_different_owner')


@pytest.mark.parametrize('replacement', [
    'expect(entity.get(Flag)!.value).toBe(1);',
    'expect(entity.has(token())).toBe(true);',
    'expect(entity.has(Flag)).toEqual(true);',
    'expect(entity.targets(Flag)).toBe([]);',
])
def test_unknown_snapshot_domain_field_projection_and_effectful_arguments_are_refused(replacement):
    _, _, _, catalog = fixture(CODE.replace('expect(entity.has(Flag)).toBe(true);', replacement))
    assert not catalog['opportunities'], catalog


def test_entry_binding_must_exist_before_boundary_not_only_at_observation():
    code = CODE.replace('    owner.queue.commit();', '    owner.queue.commit();\n    const Later = token();')
    code = code.replace('entity.has(Flag)', 'entity.has(Later)')
    _, _, _, catalog = fixture(code)
    assert not catalog['opportunities']  # not an adjacent call/assertion pair


def test_block_shadowing_uses_nearest_declaration_instead_of_name_matching():
    code = CODE.replace('    owner.queue.commit();', '    { const entity = other.spawn(); owner.queue.commit(); expect(entity.has(Flag)).toBe(true); }')
    _, _, _, catalog = fixture(code)
    assert not catalog['opportunities']  # nested statement blocks are unsupported


def test_relative_factory_identity_is_part_of_the_relation_pattern():
    _, corpus, frontend, catalog = fixture()
    ir = ir_for(catalog)
    other_source, other_corpus, other_frontend, other_catalog = fixture(CODE.replace("'./api'", "'./unrelated'"))
    record = copy.deepcopy(ir['relations'][0])
    record['examples'] = other_catalog['opportunities'][0]['examples']
    result = relation.generate(other_corpus, other_frontend, ISSUE, dict(version=relation.IR_VERSION, relations=[record]))
    assert not result['candidates']
    assert result['rejected_relations'][0]['reason'] == 'relation_examples_do_not_match_one_checked_source_opportunity'


def test_method_and_variable_renaming_preserves_construction_capability():
    code = CODE.replace('owner', 'session').replace('entity', 'item').replace('spawn', 'allocate').replace('commit', 'finish').replace('.has(', '.contains(')
    _, corpus, frontend, catalog = fixture(code)
    assert catalog['total_opportunities'] == 1
    assert relation.generate(corpus, frontend, ISSUE, ir_for(catalog))['total_candidates'] == 1


def test_false_contract_condition_or_changed_receipt_does_not_admit_relation():
    _, corpus, frontend, catalog = fixture(); ir = ir_for(catalog)
    ir['relations'][0]['conditions']['observation_is_repeatable_and_read_only'] = False
    result = relation.generate(corpus, frontend, ISSUE, ir)
    assert not result['candidates']
    ir = ir_for(catalog); ir['relations'][0]['evidence'][0]['source_sha256'] = '0'*64
    result = relation.generate(corpus, frontend, ISSUE, ir)
    assert result['rejected_relations'][0]['reason'] == 'receipt_source_mismatch'


def test_nonrepository_sources_and_evaluation_labels_do_not_supply_opportunities():
    _, _, _, history = fixture(origin='history')
    assert not history['opportunities']
    _, corpus, frontend, expected = fixture()
    corpus['evaluation'] = {'prefer': 'any', 'is_valid': False}
    assert relation.catalog(corpus, frontend) == expected
    corpus = copy.deepcopy(corpus)
    corpus['sources']['example.test.ts']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.catalog(corpus, frontend)


def test_python_is_explicitly_unsupported():
    assert relation.catalog({'language': 'python'}, {})['status'] == 'language_unsupported'
