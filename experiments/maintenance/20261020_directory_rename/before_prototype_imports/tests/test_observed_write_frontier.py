import json

import pytest

from experimental.observed_write_frontier import Frontier, canonical, fingerprint, project, scalar


def event():
    row = dict(kind='assertion_read', status='observed_within_instrumented_code',
               class_id='subject.Resource', field='_value', observed_field='value',
               value=dict(status='observed', type='bool', value=True), object_token=1)
    for name, begin in [('q', 50), ('allocation', 20), ('last_observed_writer', 10)]:
        row[span_key(name)] = dict(path='subject.py', start_byte=begin, end_byte=begin + 5)
        row['source_' + name + '_sha256'] = 'a' * 64
    return row


def span_key(name):
    return 'source_' + name + ('' if name == 'last_observed_writer' else '_span')


def test_runtime_tokens_metadata_and_dictionary_order_do_not_create_new_states():
    first = event()
    other = dict(reversed(list(first.items())))
    other.update(object_token=999, sequence=500, phase='after_expected_exception',
                 candidate_id='different', source_assertion_edited=True)
    assert canonical(project(first)) == canonical(project(other))
    frontier = Frontier()
    assert frontier.observe(first, 'control')['new']
    observed = frontier.observe(other, 'generated')
    assert not observed['new'] and not observed['retained']
    assert list(frontier.states.values())[0]['representatives'] == ['control']


@pytest.mark.parametrize('component', ['q', 'allocation', 'last_observed_writer'])
def test_each_bound_source_position_and_file_hash_participates_in_identity(component):
    a, b = event(), event()
    b[span_key(component)]['start_byte'] += 1
    assert fingerprint(project(a)) != fingerprint(project(b))
    b = event()
    b['source_' + component + '_sha256'] = 'b' * 64
    assert fingerprint(project(a)) != fingerprint(project(b))


def test_scalar_encoding_distinguishes_bool_int_float_signed_zero_and_bytes():
    values = [dict(status='observed', type=type(value).__name__, value=value)
              for value in [True, 1, 1.0, 0.0, -0.0, None, '1']]
    values += [dict(status='observed', type='bytes', hex='31')]
    keys = {canonical(scalar(value)) for value in values}
    assert len(keys) == len(values)
    assert scalar(dict(status='observed', type='bytes', hex='Ab'))['hex'] == 'ab'
    assert json.loads(canonical(scalar(values[4])))['hex'] == '-0x0.0p+0'


@pytest.mark.parametrize('encoded', [
    dict(status='observed', type='float', value=float('nan')),
    dict(status='observed', type='float', value=float('inf')),
    dict(status='observed', type='float', value=-float('inf')),
    dict(status='observed', type='int', value=True),
    dict(status='observed', type='bool', value=1),
    dict(status='observed', type='bytes', hex='xyz'),
    dict(status='unknown', reason='non_scalar_storage_value'),
])
def test_nonfinite_unknown_and_wrongly_typed_values_never_enter_frontier(encoded):
    row = event()
    row['value'] = encoded
    frontier = Frontier()
    assert frontier.observe(row, 'candidate')['status'] == 'unknown_or_unmapped'
    assert frontier.states == {}


def test_missing_mapping_and_unknown_write_are_not_states():
    for name in ['source_q_span', 'source_allocation_sha256', 'source_last_observed_writer']:
        row = event()
        del row[name]
        assert project(row) is None
    row = event()
    row['status'] = 'unknown'
    assert project(row) is None


def test_new_writer_same_value_is_new_state_and_checkpoint_replay_is_idempotent():
    a, b = event(), event()
    b['source_last_observed_writer']['start_byte'] += 1
    frontier = Frontier(representatives=2)
    frontier.observe(a, 'control')
    assert frontier.observe(b, 'generated_first')['new']
    assert frontier.observe(b, 'generated_second')['retained']
    assert not frontier.observe(b, 'generated_third')['retained']
    snapshot = frontier.snapshot()
    restored = Frontier.restore(snapshot)
    assert not restored.observe(b, 'generated_second')['retained']
    assert restored.snapshot() == snapshot
    snapshot['states'].clear()
    assert len(frontier.states) == 2
    with pytest.raises(ValueError):
        Frontier.restore(snapshot)
