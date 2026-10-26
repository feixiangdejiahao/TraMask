import copy

import pytest

from anchor_retrieval.syntax import Source
from prototypes.finite_oracle_templates import build_catalogue, expand, source_size_summary
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.oracle import preview, program_candidate


PROGRAMS = [
    ('python', 'test_seed.py', '''def test_seed():
    label = "你好"
    value = 11
    other = 22
    assert value == 11
    assert other == 22
'''),
    ('go', 'seed_test.go', '''package seed
import "testing"
func TestSeed(t *testing.T) {
    label := "你好"
    _ = label
    value := 11
    other := 22
    if value != 11 { t.Fatal(value) }
    if other != 22 { t.Fatal(other) }
}
'''),
    ('typescript', 'seed.test.ts', '''test('seed', () => {
    const label = "你好";
    const value = 11;
    const other = 22;
    expect(value).toBe(11);
    expect(other).toBe(22);
});
'''),
]


def fixture(language='python'):
    language, path, code = next(row for row in PROGRAMS if row[0] == language)
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    base = next(iter(corpus['tests']))
    start = code.encode().index(b'11', corpus['tests'][base]['span']['start_byte'])
    edit = dict(span=dict(path=path, start_byte=start, end_byte=start+2), before='11', after='19', role='input')
    candidate = dict(id='one', base_test_id=base, edits=[edit], imports=[], source_test_ids=[], source_contexts=[])
    return corpus, frontend, candidate


@pytest.mark.parametrize('language', ['python', 'go', 'typescript'])
def test_roundtrip_keeps_utf8_original_and_assertion_positions(language):
    corpus, frontend, first = fixture(language)
    second = copy.deepcopy(first)
    second.update(id='two', kind='unrelated_operator', search_shape='different_shape')
    second['edits'][0].update(after='10001', role='different_role')
    original = copy.deepcopy([first, second])
    result = build_catalogue(corpus, frontend, [first, second])
    assert [first, second] == original
    assert len(result['families']) == 1
    family = result['families'][0]
    assert family['status'] == 'factorized'
    for candidate, variant in zip([first, second], family['variants']):
        code = expand(family, variant)
        assert code == preview(corpus, program_candidate(candidate))
        assert '你好' in code
        assert len(variant['assertions']) == 2
        for assertion in variant['assertions']:
            assert assertion['original_span'] == assertion['span']
            assert assertion['modified_location_status'] == 'exact_unchanged_assertion'
            span, owner = assertion['modified_span'], family['owner_span']
            assert code.encode()[span['start_byte']-owner['start_byte']:span['end_byte']-owner['start_byte']].decode() == assertion['code']
    # Byte location shift is local to each complete member, not inherited from
    # the first variant or derived from character lengths.
    first_assert = family['variants'][0]['assertions'][0]
    second_assert = family['variants'][1]['assertions'][0]
    assert second_assert['modified_span']['start_byte'] - first_assert['modified_span']['start_byte'] == 3


def test_whole_multiline_replacements_and_insertions_keep_joint_tuples():
    corpus, frontend, first = fixture()
    path = first['edits'][0]['span']['path']
    data = corpus['sources'][path]['code'].encode()
    insertion = data.index(b'    assert value')
    first['edits'].append(dict(span=dict(path=path, start_byte=insertion, end_byte=insertion),
                               before='', after='    value += 2\n    other += 1\n', role='action'))
    second = copy.deepcopy(first)
    second['id'] = 'two'
    second['edits'][0]['after'] = '29'
    second['edits'][1]['after'] = '    value += 7\n    other += 3\n'
    result = build_catalogue(corpus, frontend, [first, second])
    family = result['families'][0]
    assert len(family['variants']) == 2 and len(family['holes']) == 2
    assert [v['replacements'] for v in family['variants']] == [
        [{'hole_id': 'H0', 'after': '19'}, {'hole_id': 'H1', 'after': '    value += 2\n    other += 1\n'}],
        [{'hole_id': 'H0', 'after': '29'}, {'hole_id': 'H1', 'after': '    value += 7\n    other += 3\n'}],
    ]
    assert all(expand(family, v) == preview(corpus, program_candidate(c)) for v, c in zip(family['variants'], [first, second]))


def test_imports_donor_premises_and_unknown_metadata_stay_per_variant():
    corpus, frontend, first = fixture()
    second = copy.deepcopy(first)
    second.update(id='two', imports=[{'name':'donor', 'module':'.helper', 'imported_name':'f'}],
                  source_test_ids=['different_control'], source_contexts=[{'code':'def f(): return 3'}],
                  donor_premise={'object':'shared_receiver', 'phase':'after_second_call'})
    result = build_catalogue(corpus, frontend, [first, second])
    assert result['family_count'] == 1
    a, b = result['families'][0]['variants']
    assert a['imports'] == [] and b['imports'] == second['imports']
    assert b['source_test_ids'] == second['source_test_ids']
    assert b['source_contexts'] == second['source_contexts']
    assert b['context']['donor_premise'] == second['donor_premise']
    assert expand(result['families'][0], a) == expand(result['families'][0], b)
    # Byte equality does not erase premise distinctions or prove equal oracle.
    assert a != b


def test_probes_removed_and_uneditable_assertions_not_dropped():
    corpus, frontend, candidate = fixture()
    source_edits = copy.deepcopy(candidate['edits'])
    candidate.update(program_edits=source_edits, instrumentation={'status':'instrumented'},
                     runtime_probes=[{'expression':'value'}])
    candidate['edits'][0]['after'] = 'log_probe(); 19'
    result = build_catalogue(corpus, frontend, [candidate])
    family, = result['families']
    variant, = family['variants']
    assert variant['program_edits'] == source_edits
    assert 'log_probe' not in expand(family, variant)
    assert variant['context']['runtime_probes'] == candidate['runtime_probes']
    assert len(variant['assertions']) == 2


@pytest.mark.parametrize('problem', ['overlap', 'duplicate_insertions', 'before_mismatch', 'foreign_path'])
def test_unsupported_candidates_kept_as_unknown_singletons_with_exact_preview(problem):
    corpus, frontend, first = fixture()
    edit = first['edits'][0]
    if problem == 'overlap':
        first['edits'].append(dict(span={**edit['span'], 'start_byte':edit['span']['start_byte']+1}, before='1', after='3'))
    elif problem == 'duplicate_insertions':
        first['edits'] = [dict(span={**edit['span'], 'end_byte':edit['span']['start_byte']}, before='', after=x) for x in ['2','3']]
    elif problem == 'before_mismatch':
        edit['before'] = 'wrong'
    else:
        edit['span']['path'] = 'different_file.py'
    second = {**copy.deepcopy(first), 'id':'two'}
    result = build_catalogue(corpus, frontend, [first, second])
    assert result['family_count'] == 2
    assert list(result['candidate_info']) == ['one', 'two']
    for family, candidate in zip(result['families'], [first, second]):
        assert family['status'] == 'unknown' and len(family['variants']) == 1
        assert expand(family, family['variants'][0]) == preview(corpus, program_candidate(candidate))


def test_preview_unavailable_does_not_discard_candidate_or_assertions():
    corpus, frontend, candidate = fixture()
    candidate['edits'][0]['span']['end_byte'] = corpus['tests'][candidate['base_test_id']]['span']['end_byte']+1
    result = build_catalogue(corpus, frontend, [candidate])
    family, = result['families']
    variant, = family['variants']
    assert len(result['candidate_info']) == 1 and family['status'] == 'unknown'
    assert len(variant['assertions']) == 2
    assert not result['candidate_info']['one']['preview_available']
    with pytest.raises(ValueError, match='edit outside selected test'):
        expand(family, variant)


def test_coordinate_set_and_base_test_define_family_not_just_modified_text():
    corpus, frontend, first = fixture()
    second = copy.deepcopy(first)
    second['id'] = 'two'
    start = second['edits'][0]['span']['start_byte']
    second['edits'] = [dict(span={**first['edits'][0]['span'],'end_byte':start+1}, before='1', after='1'),
                       dict(span={**first['edits'][0]['span'],'start_byte':start+1}, before='1', after='9')]
    result = build_catalogue(corpus, frontend, [first, second])
    assert result['family_count'] == 2
    assert expand(result['families'][0], result['families'][0]['variants'][0]) == expand(result['families'][1], result['families'][1]['variants'][0])


def test_no_edits_and_empty_catalogue_are_lossless():
    corpus, frontend, candidate = fixture()
    candidate['edits'] = []
    result = build_catalogue(corpus, frontend, [candidate])
    family, = result['families']
    assert family['holes'] == []
    assert expand(family, family['variants'][0]) == preview(corpus, candidate)
    assert build_catalogue(corpus, frontend, [])['families'] == []
    assert source_size_summary(result)['expanded_source_json_bytes'] > 0


def test_duplicate_ids_and_incomplete_expansion_raise_explicitly():
    corpus, frontend, candidate = fixture()
    with pytest.raises(ValueError, match='duplicate_candidate_id'):
        build_catalogue(corpus, frontend, [candidate, candidate])
    result = build_catalogue(corpus, frontend, [candidate])
    family, = result['families']
    variant = copy.deepcopy(family['variants'][0])
    variant['replacements'] = []
    with pytest.raises(ValueError, match='incomplete_template_variant'):
        expand(family, variant)


def test_catalogue_and_member_identities_are_stable_under_input_reordering():
    corpus, frontend, first = fixture()
    second = copy.deepcopy(first)
    second['id'] = 'two'
    second['edits'][0]['after'] = '10001'
    third = copy.deepcopy(first)
    third['id'] = 'three'
    third['edits'][0]['before'] = 'unknown'
    a = build_catalogue(corpus, frontend, [first, second, third])
    b = build_catalogue(corpus, frontend, [third, second, first])
    assert a == b
    assert all(len(family['id']) == 65 for family in a['families'])
    assert len({variant['id'] for family in a['families'] for variant in family['variants']}) == 3
    for cid, info in a['candidate_info'].items():
        family = next(row for row in a['families'] if row['id'] == info['family_id'])
        assert family['variants'][info['variant_index']]['candidate_id'] == cid


def test_family_identity_includes_source_and_keeps_member_span_details_locally():
    corpus, frontend, first = fixture()
    second = copy.deepcopy(first)
    second['id'] = 'two'
    second['edits'][0]['span']['non_identity_annotation'] = 'second_member_only'
    original = build_catalogue(corpus, frontend, [first, second])
    reordered = build_catalogue(corpus, frontend, [second, first])
    assert original == reordered and original['family_count'] == 1
    variant = original['families'][0]['variants'][1]
    assert variant['program_edits'][0]['span']['non_identity_annotation'] == 'second_member_only'
    changed_source = copy.deepcopy(corpus)
    path = first['edits'][0]['span']['path']
    changed_source['sources'][path]['code'] += '\n# different repository source\n'
    changed = build_catalogue(changed_source, frontend, [first])
    assert changed['families'][0]['id'] != original['families'][0]['id']
