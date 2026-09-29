import hashlib
import json

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.history import namespace_go_validation
from experimental.trajectory_ast_buckets import Buckets, rank_all


GO = '''package toy
import "testing"
var setting = 7
func helper() int { return setting }
func TestAlpha(t *testing.T) {
 value := helper()
 if value != 7 { t.Fatal(value) }
}
func TestOther(t *testing.T) { t.Log("old") }
'''


def fixture(versions):
    sources, files = [], {}
    for index, code in enumerate(versions):
        if index == 0:
            source = Source('unit_test.go', code, 'go')
            files[source.path] = {'kind': 'final_candidate_file', 'target_path': source.path}
        else:
            checksum = hashlib.sha256(code.encode()).hexdigest()
            path = 'unit_rh_'+checksum[:12]+'_test.go'
            source, names = namespace_go_validation(Source(path, code, 'go'), checksum[:12])
            files[path] = {'kind': 'historical_validation', 'original_target_path': 'unit_test.go',
                           'sha256': checksum, 'relocated_globals': names}
        sources.append(source)
    corpus = to_emitter_corpus(extract_frontend(sources))
    bucket = Buckets(corpus, {'files': files})
    ids = [next(test_id for test_id, test in corpus['tests'].items()
                if test['span']['path'] == source.path and test['name'].startswith('TestAlpha')) for source in sources]
    return bucket, ids


def candidate(test_id, identifier):
    return {'id': identifier, 'base_test_id': test_id, 'operator': 'same_operation', 'edits': [], 'imports': []}


def test_recorded_snapshots_and_unique_local_names_share_a_scheduling_bucket():
    changed = GO.replace('value', 'measurement').replace('"old"', '"later"')
    buckets, ids = fixture([GO, changed])
    assert buckets.seed(ids[0])['body'] != buckets.seed(ids[1])['body']
    assert buckets.seed(ids[0])['alpha'] == buckets.seed(ids[1])['alpha']
    assert buckets.candidate(candidate(ids[0], 'first')) == buckets.candidate(candidate(ids[1], 'second'))


def test_helper_global_import_and_literal_differences_are_preserved():
    variants = [GO, GO.replace('return setting', 'return setting + 1'),
                GO.replace('setting = 7', 'setting = 9'),
                GO.replace('"testing"', '"example.invalid/other_testing"'),
                GO.replace('value != 7', 'value != 9')]
    buckets, ids = fixture(variants)
    assert len({buckets.candidate(candidate(key, str(index))) for index, key in enumerate(ids)}) == len(ids)


def test_unrecorded_rh_suffixes_are_not_removed():
    code = GO.replace('helper', 'helper_rh_0123456789ab')
    buckets, ids = fixture([GO, code])
    # The actual source identifier already contained a suffix before history
    # relocation. Only the extra recorded relocation is reversible.
    assert buckets.candidate(candidate(ids[0], 'one')) != buckets.candidate(candidate(ids[1], 'two'))


def test_test_named_callback_helper_cannot_disappear_from_environment():
    before = GO.replace('helper', 'TestData').replace('value := TestData()', 'reader := TestData\n value := reader()')
    after = before.replace('return setting', 'return setting + 1')
    buckets, ids = fixture([before, after])
    # Do not rely on call resolution discovering a helper passed as a value.
    for test in buckets.corpus['tests'].values():
        test['support']['helpers'] = []
    assert buckets.candidate(candidate(ids[0], 'one')) != buckets.candidate(candidate(ids[1], 'two'))


def test_relative_imports_point_to_actual_distinct_source_locations_and_hashes():
    corpus = {'language': 'typescript', 'sources': {
        'left/api.ts': {'code': 'export function read() { return 1; }'},
        'right/api.ts': {'code': 'export function read() { return 1; }'},
    }, 'tests': {}}
    buckets = Buckets(corpus, {})
    left = json.loads(buckets.imported('left/test.ts', './api.js', 'read')[0])
    right = json.loads(buckets.imported('right/test.ts', './api.js', 'read')[0])
    assert left['resolution'] == right['resolution'] == 'supplied_source'
    assert left['source_declarations'][0][0] == 'left/api.ts'
    assert right['source_declarations'][0][0] == 'right/api.ts'
    assert left != right
    assert left['source_declarations'][0][1] == hashlib.sha256(corpus['sources']['left/api.ts']['code'].encode()).hexdigest()


def test_identical_test_bodies_in_different_classes_do_not_share_context():
    source = Source('test_classes.py', '''class TestOne:
    def test_read(self):
        assert self.read() == 1
class TestTwo:
    def test_read(self):
        assert self.read() == 1
''', 'python')
    corpus = to_emitter_corpus(extract_frontend([source]))
    buckets = Buckets(corpus, {})
    ids = list(corpus['tests'])
    assert len(ids) == 2
    assert buckets.candidate(candidate(ids[0], 'one')) != buckets.candidate(candidate(ids[1], 'two'))


def test_bucket_scheduling_is_a_permutation_and_serves_another_bucket_before_copy():
    rows = [candidate('one', 'copy_one'), candidate('two', 'copy_two'), candidate('three', 'different')]
    keys = {'copy_one': 'shared', 'copy_two': 'shared', 'different': 'distinct'}
    ranked = rank_all(rows, keys)
    assert [row['id'] for row in ranked] == ['copy_one', 'different', 'copy_two']
    assert {id(row) for row in rows} == {id(row) for row in ranked}


def test_python_fixture_parameters_and_global_writes_are_not_alpha_locals():
    source = Source('test_resources.py', '''left = 1
right = 2
def test_left(left_fixture):
    left_fixture = 3
    assert left_fixture == 3
def test_right(right_fixture):
    right_fixture = 3
    assert right_fixture == 3
def test_global_left():
    global left
    left = 3
    assert left == 3
def test_global_right():
    global right
    right = 3
    assert right == 3
''', 'python')
    corpus = to_emitter_corpus(extract_frontend([source]))
    buckets = Buckets(corpus, {})
    assert len({buckets.candidate(candidate(key, key)) for key in corpus['tests']}) == 4
