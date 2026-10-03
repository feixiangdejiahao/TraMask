from relation_search.import_provenance_repair import repair, verify_bindings


def inputs(module='./index.ts', member='wrap'):
    corpus = {'language': 'typescript', 'tests': {'base': {'span': {'path': 'lib/wrap/case.test.ts'}}},
              'sources': {'lib/parse/case.test.ts': {'code': "import { wrap } from '../wrap/index.ts';\n"}}}
    candidate = {'id': 'opaque', 'base_test_id': 'base', 'edits': [], 'imports': [
        {'name': 'fresh', 'module': module, 'imported_name': member,
         'source_path': 'lib/parse/case.test.ts', 'source_binding': 'wrap'}]}
    return corpus, candidate


def test_recover_donor_module_before_the_emitter_rebases_again():
    corpus, candidate = inputs()
    result = repair(corpus, candidate)
    assert result['status'] == 'repaired'
    assert result['candidate']['imports'][0]['module'] == '../wrap/index.ts'
    assert candidate['imports'][0]['module'] == './index.ts'
    assert result['changes'][0]['previous_emitted_module'] == 'lib/parse/index.ts'
    assert result['changes'][0]['intended_module'] == 'lib/wrap/index.ts'


def test_already_origin_relative_import_stays_unchanged():
    corpus, candidate = inputs('../wrap/index.ts')
    assert repair(corpus, candidate)['candidate'] == candidate


def test_unexplained_module_or_member_change_is_not_repaired():
    for args in [('./unrelated.ts', 'wrap'), ('./index.ts', 'other')]:
        corpus, candidate = inputs(*args)
        result = repair(corpus, candidate)
        assert not result['changes'] and result['unresolved']
        assert result['candidate'] == candidate


def test_same_body_with_wrong_import_module_fails_binding_transport():
    corpus, candidate = inputs('../wrap/index.ts')
    bad = "import { wrap as fresh } from '../parse/index.ts'; test('x', () => fresh(1));"
    good = "import { wrap as fresh } from './index.ts'; test('x', () => fresh(1));"
    assert verify_bindings(corpus, candidate, 'lib/wrap/case.test.ts', bad)['status'] == 'mismatch'
    assert verify_bindings(corpus, candidate, 'lib/wrap/case.test.ts', good)['status'] == 'matched'
