"""Synthetic extraction checks; no model, repository execution or case labels."""
from copy import deepcopy
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from research_tools.automatic_augmentation_extract import extract, prepare_case


def fixture(files, language='python'):
    frontend = extract_frontend([Source(path, text, language) for path, text in files.items()])
    return to_emitter_corpus(frontend), frontend


def patch(path, first=1, last=20):
    return '\n'.join(['--- a/' + path, '+++ b/' + path, '@@ -1,1 +%d,%d @@' % (first, last)] + ['+x'] * last)


def run(files=None, trajectory=None, language='python', change=None):
    files = files or {'lib.py': 'def scale(x):\n    return x * 2\n',
                      'test_lib.py': 'from lib import scale\ndef test_scale():\n    value = scale(2)\n    assert value == 4\n'}
    corpus, frontend = fixture(files, language)
    return extract(corpus, frontend, 'Public contract.', trajectory or {'steps': []},
                   change or patch(next(iter(files))))


def test_selected_by_bound_patch_not_by_manual_or_history_and_full_utf8():
    files = {'lib.py': 'def scale(x):\n    return x * 2\n',
             'test_lib.py': 'from lib import scale\ndef test_scale():\n    label = "界🙂"\n    assert scale(2) == 4\n',
             'test_other.py': 'def test_other():\n    assert 1 == 1\n'}
    first = run(files)
    second = run(files, {'steps': [{'step_id': 1, 'message': 'test_other should be selected',
                                  'reasoning_content': 'secret', 'manual_label': 'test_other'}],
                         'final_metrics': {'missed_test': 'test_other'}})
    assert first['source_payload'] == second['source_payload']
    assert len(first['candidates']) == 1
    seed = first['candidates'][0]
    assert seed['original_test'].endswith('assert scale(2) == 4')
    assert '界🙂' in seed['original_test']
    assert seed['original_test_sha256'] == hashlib.sha256(seed['original_test'].encode()).hexdigest()
    assert seed['selection_facts'][0]['kind'] == 'resolved_call_graph_reaches_changed_declaration'
    assert next(x for x in first['source_payload']['original_source_files'] if x['path'] == 'test_lib.py')['text'] == files['test_lib.py']


def test_complete_public_step_retained_and_private_fields_never_exposed():
    observation = {'results': [{'content': 'complete stdout with assertions and diagnostics\n' * 30}]}
    tr = {'steps': [{'step_id': 17, 'message': 'Inspect scale and test_lib.py.',
                     'reasoning_content': 'PRIVATE_MARKER', 'observation': observation,
                     'tool_calls': [{'function_name': 'bash', 'arguments': {'command': 'pytest test_lib.py'}}]}],
          'final_metrics': {'PRIVATE_SCORE_MARKER': 99}}
    result = run(trajectory=tr)
    history = result['history_payload']['trajectory_evidence']
    public = history['steps'][0]['public_step']
    assert public['observation'] == observation
    assert public['tool_calls'] == tr['steps'][0]['tool_calls']
    assert 'reasoning_content' not in public
    assert 'PRIVATE_MARKER' not in json.dumps(result)
    assert 'PRIVATE_SCORE_MARKER' not in json.dumps(result)
    assert history['events'][0]['run_token']
    assert history['seed_associations'][0]['step_evidence_ids'] == [history['steps'][0]['evidence_id']]
    without_history = dict(result['history_payload']); del without_history['trajectory_evidence']
    assert without_history == result['source_payload']


def test_discarded_go_tuple_channel_is_distinct_from_error_assertion():
    result = run({'lib.go': 'package demo\nfunc Pick() (int, error) { return 7, nil }\n',
                  'lib_test.go': 'package demo\nimport "testing"\nfunc TestPick(t *testing.T) { _, err := Pick(); if err != nil { t.Fatal(err) } }\n'},
                 language='go')
    channels = [f for f in result['candidates'][0]['source_facts']['result_channels'] if f['kind'] == 'assigned_call_channels']
    assert channels
    row = channels[0]['channels']
    assert row[0]['target'] == '_' and row[0]['discard']
    assert row[1]['target'] == 'err' and not row[1]['discard']
    assert row[1]['assertion_identifier_mentions']
    assert channels[0]['slot_semantics'].endswith('not_proved')


def test_shadowing_and_rebinding_are_not_proved_def_use():
    result = run({'lib.py': 'def scale(x):\n    return x * 2\n',
                  'test_lib.py': 'from lib import scale\ndef test_scale():\n    value = scale(2)\n    value = 9\n    assert value == 9\n'})
    row = result['candidates'][0]['source_facts']['result_channels'][0]['channels'][0]
    assert row['assertion_identifier_mentions']
    assert row['status'] == 'lexical_only_alias_shadow_control_flow_unknown'


def test_unresolved_leaf_name_match_is_explicitly_weak():
    result = run({'lib.py': 'def scale(x):\n    return x * 2\n',
                  'test_lib.py': 'def test_scale(obj):\n    assert obj.scale(2) == 4\n'})
    assert len(result['candidates']) == 1
    reason = result['candidates'][0]['selection_facts'][0]
    assert reason['kind'] == 'unresolved_call_name_matches_changed_declaration'
    assert reason['status'] == 'lexical_weak_not_binding_proof'


def test_no_top_k_and_stable_source_order():
    tests = 'from lib import scale\n' + '\n'.join('def test_%03d():\n    assert scale(2) == 4\n' % n for n in range(110))
    result = run({'lib.py': 'def scale(x):\n    return x * 2\n', 'test_lib.py': tests})
    assert len(result['candidates']) == 110
    assert len(set(c['seed_alias'] for c in result['candidates'])) == 110
    assert [c['span']['start_byte'] for c in result['candidates']] == sorted(c['span']['start_byte'] for c in result['candidates'])


def test_original_import_catalog_not_hand_selected_and_type_only_explicit():
    result = run({'lib.ts': 'export function transform(fn) { return fn(2); }',
                  'lib.test-d.ts': "import {transform as map} from './lib'; test('types', () => { expectTypeOf(map(x => x + 1)).toBeNumber(); });",
                  'other.ts': "import {transform} from './lib';"}, language='typescript')
    assert not result['candidates']  # Existing frontend excludes type-only tests from native IDs.
    assert any(t['type_only'] and t['mapped_original_test_id'] is None for t in result['inventory'])
    assert any(i['name'] == 'map' and i['imported_name'] == 'transform' and i['source_path'] == 'lib.test-d.ts' for i in result['imports'])
    assert any(i['name'] == 'transform' and i['source_path'] == 'other.ts' for i in result['imports'])


def test_original_source_bytes_must_match_frontend():
    corpus, frontend = fixture({'test_lib.py': 'def test_x():\n    assert True\n'})
    corpus = deepcopy(corpus)
    corpus['sources']['test_lib.py']['code'] += '# changed\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        extract(corpus, frontend, '', {'steps': []}, patch('test_lib.py'))


def test_trajectory_version_does_not_replace_final_source():
    command = "cat > /tmp/test_probe.py <<'PY'\nfrom lib import scale\nprint(scale(900))\nPY"
    result = run(trajectory={'steps': [{'step_id': 7, 'tool_calls': [{'arguments': {'command': command}}]}]})
    versions = result['history_payload']['trajectory_evidence']['recovered_source_versions']
    assert versions and any('scale(900)' in v['text'] for v in versions)
    assert all('900' not in c['original_test'] for c in result['candidates'])
    assert all(v['status'].endswith('not_verified_executed_on_final_source') for v in versions)


def test_prepare_case_uses_only_declared_original_inputs(tmp_path):
    corpus, frontend = fixture({'lib.py': 'def scale(x):\n    return x * 2\n',
                                'test_lib.py': 'from lib import scale\ndef test_scale():\n    assert scale(2) == 4\n'})
    for name, value in [('corpus.json', corpus), ('frontend.json', frontend), ('trajectory.json', {'steps': []})]:
        (tmp_path / name).write_text(json.dumps(value))
    (tmp_path / 'issue.md').write_text('Public contract.')
    (tmp_path / 'model.patch').write_text(patch('lib.py'))
    (tmp_path / 'manual_labels.json').write_text('{"secret":"must not be read"}')
    (tmp_path / 'case.json').write_text(json.dumps({'trajectory': str(tmp_path / 'trajectory.json'),
        'candidate_patch': str(tmp_path / 'model.patch'), 'repository': '/original/repository'}))
    result = prepare_case('fixture', tmp_path, output=tmp_path / 'out')
    assert result['repository'] == '/original/repository'
    assert len(result['input_receipts']) == 6
    assert result['algorithm']['path'].endswith('research_tools/automatic_augmentation_extract.py')
    assert len(result['algorithm']['sha256']) == 64
    assert 'must not be read' not in json.dumps(result)
    assert (tmp_path / 'out' / 'source_payload.json').is_file()


def test_batches_keep_each_candidate_once_and_have_identical_source_prefix():
    tests = 'from lib import scale\n' + '\n'.join('def test_%03d():\n    assert scale(2) == 4\n' % n for n in range(110))
    result = run({'lib.py': 'def scale(x):\n    return x * 2\n', 'test_lib.py': tests})
    assigned = [c['seed_alias'] for b in result['batches'] for c in b['candidates']]
    assert assigned == [c['seed_alias'] for c in result['candidates']]
    assert len(assigned) == len(set(assigned))
    assert all(len(b['candidates']) <= 80 for b in result['batches'])
    for b in result['batches']:
        without = dict(b['history_payload']); del without['trajectory_evidence']
        assert without == b['source_payload']
        assert {x['kind'] for x in b['source_payload']['evidence_catalog']} == {'public_issue', 'submitted_patch'}
