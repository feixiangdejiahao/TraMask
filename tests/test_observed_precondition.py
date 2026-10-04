import copy
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source, child, walk
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import observed_precondition as relation


ISSUE = ('Observe returns a committed version with no error. AwaitContext on a committed '
         'version of the same store succeeds without changing the store.')
CODE = '''package sample
import (
 "context"
 "errors"
 "testing"
 "time"
 "github.com/stretchr/testify/require"
)
type Store struct { ready int }
func NewStore() *Store { return &Store{ready: 3} }
func (s *Store) Observe() (int, error) { return s.ready, nil }
func (s *Store) AwaitContext(ctx context.Context, version int) error {
 if version > s.ready { return errors.New("not committed") }; return nil
}
func TestObserve(t *testing.T) {
 s := NewStore()
 value, err := s.Observe()
 require.NoError(t, err)
 if value < 3 { t.Fatal("source observation failed") }
 t.Log("original suffix")
}
func TestWait(t *testing.T) {
 s := NewStore()
 ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
 defer cancel()
 require.NoError(t, s.AwaitContext(ctx, 3))
}
'''


def fixture(code=CODE, *, origin='repository'):
    source = Source('sample_test.go', code, 'go', origin)
    frontend = extract_frontend([source])
    corpus = to_emitter_corpus(frontend)
    methods = {source.text(child(n, 'name')): n for n in walk(source.root) if n.type == 'method_declaration'}
    def decl(name):
        node = methods[name]
        return relation.receipt(source.path, code, node.start_byte, node.end_byte)
    ir = {'version': relation.IR_VERSION, 'relations': [{
        'id': 'r1', 'law': relation.LAW, 'same_receiver': True,
        'evidence': [relation.receipt('issue.md', ISSUE, 0, len(ISSUE.encode()))],
        'producer': {'declaration': decl('Observe'), 'value_result': 0, 'error_result': 1},
        'consumer': {'declaration': decl('AwaitContext'), 'arguments': [
            {'kind': 'bounded_context'}, {'kind': 'observed_value'}]},
        'semantic_status': 'hypothesis_pending_independent_audit'}]}
    return source, corpus, frontend, ir


def generated(code=CODE):
    source, corpus, frontend, ir = fixture(code)
    return source, corpus, relation.generate(corpus, frontend, ISSUE, ir)


def test_observed_value_flows_to_same_owner_after_fatal_guard_and_preserves_suffix():
    source, corpus, frontend, ir = fixture()
    before = copy.deepcopy((corpus, frontend, ir))
    result = relation.generate(corpus, frontend, ISSUE, ir)
    assert result['total_candidates'] == 1, result
    candidate = result['candidates'][0]
    edit = candidate['edits'][0]
    assert edit['before'] == 'require.NoError(t, err)'
    assert 's.AwaitContext(_observedCtx_' in edit['after']
    assert ', value))' in edit['after']
    assert len(candidate['source_test_ids']) == 2
    material = emit(corpus, [candidate])
    assert not material['unsupported']
    code = material['files'][source.path]
    assert code.count('t.Log("original suffix")') == 3  # original, source control, candidate
    assert not Source(source.path, code, 'go').root.has_error
    assert (corpus, frontend, ir) == before


@pytest.mark.parametrize('replacement', [
    ' s = NewStore()\n require.NoError(t, err)',
    ' s.Mutate()\n require.NoError(t, err)',
    ' value = 7\n require.NoError(t, err)',
    ' other := NewStore()\n require.NoError(t, err)',
    ' require.Error(t, err)',
    ' if err != nil { t.Fatal(err) }',
])
def test_intervening_operations_and_unsupported_error_guards_abstain(replacement):
    _, _, result = generated(CODE.replace(' require.NoError(t, err)', replacement))
    assert not result['candidates'], result


@pytest.mark.parametrize('addition', ['\n go s.Observe()', '\n observe := func(){ s.Observe() }; _=observe'])
def test_concurrent_or_captured_owner_abstains(addition):
    _, _, result = generated(CODE.replace(' t.Log("original suffix")', addition+'\n t.Log("original suffix")'))
    assert not result['candidates']


def test_import_aliases_are_resolved_and_renamed_context_scaffold_is_valid():
    code = CODE.replace('"context"', 'ctxlib "context"').replace('"time"', 'clocklib "time"')
    code = code.replace('context.', 'ctxlib.').replace('time.', 'clocklib.')
    _, _, result = generated(code)
    assert len(result['candidates']) == 1, result
    after = result['candidates'][0]['edits'][0]['after']
    assert 'ctxlib.WithTimeout(ctxlib.Background(), 5 * clocklib.Second)' in after


def test_source_method_type_mismatch_and_missing_consumer_donor_abstain():
    _, _, result = generated(CODE.replace('version int)', 'version string)'))
    assert result['rejected_relations'][0]['reason'] == 'observed_value_type_mismatch'
    _, _, result = generated(CODE.replace('require.NoError(t, s.AwaitContext(ctx, 3))', '_=ctx'))
    assert result['rejected_relations'][0]['reason'] == 'consumer_has_no_typed_original_test_donor'


@pytest.mark.parametrize('path', ['evidence', 'producer', 'consumer'])
def test_modified_receipts_are_rejected(path):
    _, corpus, frontend, ir = fixture()
    record = ir['relations'][0]
    receipt = record['evidence'][0] if path == 'evidence' else record[path]['declaration']
    receipt['source_sha256'] = '0'*64
    result = relation.generate(corpus, frontend, ISSUE, ir)
    assert not result['candidates']
    assert result['rejected_relations'][0]['reason'] == 'receipt_source_mismatch'


def test_history_sources_cannot_supply_relation_or_candidate():
    _, corpus, frontend, ir = fixture(origin='history')
    result = relation.generate(corpus, frontend, ISSUE, ir)
    assert not result['candidates']
    assert result['rejected_relations'][0]['reason'] == 'receipt_is_not_repository_source'


def test_input_byte_mismatch_is_not_silently_reparsed_and_labels_have_no_effect():
    _, corpus, frontend, ir = fixture()
    expected = relation.generate(corpus, frontend, ISSUE, ir)
    corpus['evaluation'] = {'preferred_task': 'other', 'valid': False}
    assert relation.generate(corpus, frontend, ISSUE, ir) == expected
    corpus = copy.deepcopy(corpus)
    corpus['sources']['sample_test.go']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(corpus, frontend, ISSUE, ir)


def test_renaming_all_domain_apis_does_not_change_generation():
    code = CODE.replace('Store', 'Mailbox').replace('Observe', 'DeliveredThrough').replace('AwaitContext', 'AwaitDelivered')
    source = Source('renamed_test.go', code, 'go')
    frontend = extract_frontend([source]); corpus = to_emitter_corpus(frontend)
    _, _, _, ir = fixture()
    methods = {source.text(child(n, 'name')): n for n in walk(source.root) if n.type == 'method_declaration'}
    for role, name in [('producer', 'DeliveredThrough'), ('consumer', 'AwaitDelivered')]:
        node = methods[name]
        ir['relations'][0][role]['declaration'] = relation.receipt(source.path, code, node.start_byte, node.end_byte)
    assert relation.generate(corpus, frontend, ISSUE, ir)['total_candidates'] == 1


def test_native_source_control_passes_but_inconsistent_observation_fails(tmp_path):
    if not shutil.which('go'):
        pytest.skip('Go required for native validation')
    require = tmp_path/'require'; require.mkdir()
    (require/'go.mod').write_text('module github.com/stretchr/testify/require\n\ngo 1.20\n')
    (require/'require.go').write_text('''package require
import "testing"
func NoError(t *testing.T, err error) {t.Helper();if err!=nil {t.Fatalf("unexpected error: %v",err)}}
''')
    (tmp_path/'go.mod').write_text('''module example.org/sample
go 1.20
require github.com/stretchr/testify/require v0.0.0
replace github.com/stretchr/testify/require => ./require
''')
    env = dict(os.environ, GOWORK='off', GOPROXY='off', GOSUMDB='off')
    for inconsistent in [False, True]:
        code = CODE.replace('return s.ready, nil', 'return s.ready+1, nil') if inconsistent else CODE
        source, corpus, result = generated(code)
        assert len(result['candidates']) == 1
        material = emit(corpus, result['candidates'])
        (tmp_path/source.path).write_text(material['files'][source.path])
        for label, entries in [('controls', material['controls']), ('obligations', material['obligations'])]:
            names = '|'.join(row['test_name'] for row in entries)
            run = subprocess.run(['go','test','-count=1','-run',f'^({names})$','.'], cwd=tmp_path,
                                 env=env, capture_output=True, text=True, timeout=45)
            assert (run.returncode != 0) == (inconsistent and label == 'obligations'), run.stdout+run.stderr
