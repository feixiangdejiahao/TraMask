"""Execute composed oracle revisions through the real probe and clone pipeline."""
import copy
import json
import sys
import types

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.instrument import compose_neighbors, instrument_candidates
from relation_search.oracle import prepare_requests, validate
from relation_search.semantic_cache import apply_cache, program_key


def example(buggy, probe_at_assertion=False):
    code = ('def total(a, b):\n    return ' + ('3' if buggy else 'a + b') + '\n\n'
            'def test_total():\n    a = 1\n    b = 2\n    result = total(a, b)\n'
            '    assert result == 3, result\n')
    path = 'test_total.py'
    front = extract_frontend([Source(path, code, 'python')])
    corpus = to_emitter_corpus(front)
    base = next(iter(corpus['tests']))

    def span(text):
        start = code.index(text)
        return dict(path=path, start_byte=start, end_byte=start + len(text))

    def row(identifier, before, after):
        return dict(id=identifier, language='python', base_test_id=base,
                    source_test_ids=[], imports=[], kind='input',
                    edits=[dict(span=span(before), before=before, after=after, role='input')])

    left, right = row('left', 'a = 1', 'a = 3'), row('right', 'b = 2', 'b = 5')
    left['runtime_feedback'] = dict(candidate_id='left', status='runtime_observed',
                                    retained=True, measured_profiles=['recorded'])
    combined = compose_neighbors([left], [right])[0]
    combined['runtime_probes'] = [dict(phase='before_call',
        insert_before=span('assert result == 3, result' if probe_at_assertion else 'result = total(a, b)'),
        roles=[dict(name='a', expression='a'), dict(name='b', expression='b')])]
    return corpus, front, combined


@pytest.mark.parametrize('mode', ['fresh_validation', 'cache_replay'])
@pytest.mark.parametrize('buggy', [False, True])
@pytest.mark.parametrize('phase', ['before_instrumentation', 'after_instrumentation', 'assertion_boundary'])
def test_oracle_survives_composition_and_repeated_instrumentation(mode, buggy, phase, tmp_path, monkeypatch):
    corpus, front, candidate = example(buggy, probe_at_assertion=phase == 'assertion_boundary')
    if phase == 'after_instrumentation':
        candidate = next(row for row in instrument_candidates(corpus, [candidate])['candidates']
                         if row['id'] == candidate['id'])
    frozen = copy.deepcopy(candidate)
    contract = 'total returns the sum of its two arguments.'
    request = prepare_requests(corpus, front, [candidate], contract)[0]
    revision = validate(request, {'revisions': [{'candidate': 'C0', 'basis': '3 + 5 is 8',
        'updates': [{'assertion': 'A0', 'code': 'assert result == 8, result'}]}]}, corpus)['revisions'][0]
    if mode == 'cache_replay':
        cache = {'entries': [dict(program_key=program_key(corpus, candidate, contract),
                                  candidate=revision, request='frozen.json', completion='completed')]}
        revision = apply_cache(corpus, [candidate], cache, contract)['candidates'][1]
    result = instrument_candidates(corpus, [revision])
    twice = instrument_candidates(corpus, result['candidates'])
    assert result['candidates'] == twice['candidates']
    generated = next(row for row in result['candidates'] if row['id'] == revision['id'])
    assert {e['role'] for e in generated['program_edits']} == {'input', 'semantic_expected'}
    assert not any(e.get('instrumented_prefix') for e in generated['program_edits'])
    assert len([e for e in generated['program_edits'] if e.get('role') == 'semantic_expected']) == 1
    assert candidate == frozen
    for helper in result['helper_files']:
        module = types.ModuleType(helper['path'].removesuffix('.py'))
        exec(helper['code'], module.__dict__)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv('COMBINATION_REPORT_DIR', str(tmp_path))
    emitted = emit(corpus, result['candidates'])
    assert emitted['unsupported'] == []
    namespace = {}
    exec(compile(emitted['files']['test_total.py'], '<materialized>', 'exec'), namespace)
    for control in emitted['controls']:
        namespace[control['test_name']]()
    target = next(row for row in emitted['obligations'] if row['candidate_id'] == revision['id'])
    if buggy:
        with pytest.raises(AssertionError, match='3'):
            namespace[target['test_name']]()
    else:
        namespace[target['test_name']]()
    events = [json.loads(line) for line in (tmp_path/'relation_trace.jsonl').read_text().splitlines()]
    assert len(events) == 1  # Repeated instrumentation must not duplicate probes.
    assert events[0]['candidate_id'] == revision['id']
