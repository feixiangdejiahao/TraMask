"""Input consumption, domain association and intentional-negative boundaries."""
import copy

import pytest

from relation_search.csi_input_domain_guard import analyze, _wire

API = '''class Reader:
    def feed(self, data):
        """Decode Kitty keyboard protocol CSI sequences into key events."""
        return []
'''
FIXTURE = '''import pytest
from wire import Reader as Decoder
@pytest.fixture
def parser():
    return Decoder()
'''
HELPER = '''def collect(reader, data):
    items = []
    for item in reader.feed(data):
        items.append(item)
    for item in reader.feed(""):
        items.append(item)
    return [item for item in items if isinstance(item, Key)]
'''


def context(body, *, api=API, helpers='', issue='Support the Kitty keyboard protocol.', decorators=''):
    code = decorators + 'def test_decode(parser):\n' + '\n'.join('    ' + line for line in body.splitlines())
    payload = dict(language='python', original_test=code, modified_test=code, issue=issue)
    graph = {'sources': {'S0': {'path': 'test_wire.py', 'code': FIXTURE + '\n' + helpers}}}
    sources = {'wire.py': api, 'test_wire.py': FIXTURE + '\n' + helpers}
    return payload, dict(analysis=graph, sources=sources)


def inspect(body, **kwargs):
    payload, extra = context(body, **kwargs)
    return analyze(payload, **extra)


def test_consumed_invalid_primary_has_exact_source_binding_and_positive_result():
    result = inspect('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "alt+shift+a"')
    assert result['decision'] == 'reject'
    check = result['checks'][0]
    assert check['violations'] == ['ascii_uppercase_primary_is_not_unshifted']
    assert check['domain_binding']['consumer'] == 'wire.Reader.feed'
    assert check['domain_binding']['public_documentation']['text'].startswith('"""Decode Kitty')
    assert check['call_receipt']['text'] == 'parser.feed("\\x1b[65;4u")'
    assert result['whole_test_semantics'] == 'unconfirmed'


@pytest.mark.parametrize('sequence', ['\x1b[97:65;2u', '\x1b[97;2;65u', '\x1b[1040;2u', '\x1b[65~'])
def test_uppercase_rule_is_only_ascii_primary_in_unicode_form(sequence):
    packet, violations, unknown = _wire(sequence)
    assert packet and 'ascii_uppercase_primary_is_not_unshifted' not in violations
    assert not unknown


def test_expected_printed_and_unused_helper_literals_do_not_become_inputs():
    result = inspect('def unused():\n    parser.feed("\\x1b[65;4u")\n'
                     '[event] = parser.feed("\\x1b[97;4u")\n'
                     'print("\\x1b[65;4u")\nassert event.key == "\\x1b[65;4u"')
    assert result['decision'] == 'allow'
    assert [x['value'] for x in result['checks']] == ['\x1b[97;4u']


def test_bound_helper_transmits_the_consumed_argument_and_retains_original_domain_errors():
    payload, extra = context('[event] = collect(parser, "\\x1b[65;4;97u")\nassert event.character is None', helpers=HELPER)
    payload['original_test'] = payload['modified_test'].replace('65;4;97', '65;4')
    result = analyze(payload, **extra)
    assert result['decision'] == 'reject'
    assert result['checks'][0]['binding_chain'][0]['arguments'][1]['formal'] == 'data'


def test_invalid_original_example_cannot_reject_a_valid_modified_input():
    payload, extra = context('[event] = parser.feed("\\x1b[97;4u")\nassert event.key == "alt+shift+a"')
    payload['original_test'] = payload['modified_test'].replace('[97;', '[65;')
    payload['source_controls'] = [{'code': 'parser.feed("\\x1b[65;4u")'}]
    assert analyze(payload, **extra)['decision'] == 'allow'


@pytest.mark.parametrize('body', [
    'with pytest.raises(ValueError):\n    [event] = parser.feed("\\x1b[65;4u")\n    assert event.key == "a"',
    'events = parser.feed("\\x1b[65;4u")\nassert list(events) == []',
    'try:\n    [event] = parser.feed("\\x1b[65;4u")\n    assert event.key == "a"\nexcept ValueError:\n    pass',
])
def test_intentional_negative_or_exception_test_is_never_rejected(body):
    assert inspect(body)['decision'] != 'reject'


def test_other_object_or_unbound_receiver_does_not_establish_positive_input_result():
    result = inspect('[event] = parser.feed("\\x1b[65;4u")\nassert other.key == "a"')
    assert result['decision'] == 'unknown'
    result = inspect('[event] = another.feed("\\x1b[65;4u")\nassert event.key == "a"')
    assert result['decision'] == 'unknown'


def test_prior_false_assertion_prevents_consumption():
    result = inspect('assert False\n[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"')
    assert not result['checks'] and result['decision'] == 'allow'


@pytest.mark.parametrize('api,issue', [
    ('# Kitty keyboard protocol CSI\nclass Reader:\n    def feed(self, data):\n        return []\n', 'Support the Kitty keyboard protocol.'),
    (API, 'Return events from the stream.'),
    ('class Reader:\n    def feed(self, data):\n        return []\n    def unrelated(self, data):\n        """Decode Kitty keyboard protocol CSI."""\n        return []\n', 'Support the Kitty keyboard protocol.'),
])
def test_domain_needs_issue_and_connected_class_documentation(api, issue):
    assert inspect('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"', api=api, issue=issue)['decision'] == 'unknown'


def test_renamed_class_and_source_call_path_bind_without_api_whitelist():
    api = '''class Reader:
    def feed(self, data):
        return self.convert(data)
    def convert(self, data):
        """Decode Kitty keyboard protocol CSI into key events."""
        return []
'''
    result = inspect('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"', api=api)
    assert result['decision'] == 'reject'
    assert len(result['checks'][0]['domain_binding']['structural_call_path']) == 1


def test_parameter_rows_expand_field_positions_without_treating_text_as_phase():
    decorator = '@pytest.mark.parametrize("phase", ["1", "2", "3"])\n'
    result = inspect('[event] = parser.feed(f"\\x1b[0;1;{phase}u")\nassert event.key == "a"', decorators=decorator)
    assert result['decision'] == 'reject' and len(result['checks']) == 3
    assert all(x['violations'] == ['associated_text_contains_control_code'] for x in result['checks'])


def test_xfail_or_unresolved_parameterization_abstains():
    for decorator in ['@pytest.mark.xfail\n', '@pytest.mark.parametrize("phase", unknown_rows)\n']:
        assert inspect('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"', decorators=decorator)['decision'] == 'unknown'


@pytest.mark.parametrize('prefix,sequence', [
    ('parser.feed("\\x1b[200~")\n', '\x1b[65;4u'),
    ('', '\x1b[65;'),
    ('', '\x1b[65;4u\x1b[97u'),
])
def test_prior_state_fragments_and_multiple_packets_abstain(prefix, sequence):
    result = inspect(prefix + '[event] = parser.feed(' + repr(sequence) + ')\nassert event.key == "a"')
    assert result['decision'] == 'unknown'


def test_generator_support_boundary_is_unknown_not_protocol_contradiction():
    result = inspect('[event] = parser.feed("\\x1b[13:65;2u")\nassert event.key == "enter"')
    assert result['decision'] == 'unknown'
    assert not result['checks'][0]['violations']


@pytest.mark.parametrize('prefix', ['parser = other\n', 'parser.feed = other\n'])
def test_receiver_rebinding_removes_the_old_fixture_certificate(prefix):
    assert inspect(prefix + '[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"')['decision'] == 'unknown'


def test_helper_shadowing_or_output_replacement_cannot_lend_a_positive_oracle():
    result = inspect('def collect(*args):\n    return [other]\n[event] = collect(parser, "\\x1b[65;4u")\nassert event.key == "a"', helpers=HELPER)
    assert result['decision'] == 'unknown'
    helper = 'def collect(reader, data):\n    reader.feed(data)\n    return [other]\n'
    assert inspect('[event] = collect(parser, "\\x1b[65;4u")\nassert event.key == "a"', helpers=helper)['decision'] == 'unknown'


def test_bad_syntax_and_missing_source_are_unknown_and_labels_have_no_effect():
    payload, extra = context('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"')
    expected = analyze(payload, **extra)
    before = copy.deepcopy(payload)
    payload.update(case='renamed', candidate_id='unused', provider_decision='supported', native='pass', audit='valid')
    assert analyze(payload, **extra) == expected
    assert analyze(before, analysis=extra['analysis'])['decision'] == 'unknown'
    payload['modified_test'] = 'not valid Python ???'
    assert analyze(payload, **extra)['decision'] == 'unknown'


@pytest.mark.parametrize('middle', ['event = other', 'mutate(event)'])
def test_result_replacement_or_mutation_breaks_positive_observation_chain(middle):
    result = inspect('[event] = parser.feed("\\x1b[65;4u")\n' + middle + '\nassert event.key == "a"')
    assert result['decision'] == 'unknown'


def test_unknown_prior_assertion_does_not_make_a_later_consumer_disappear():
    result = inspect('assert ready\n[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"')
    assert result['decision'] == 'unknown'
    assert 'prior_assertion_reachability_unresolved' in result['unknowns']


@pytest.mark.parametrize('prefix', [
    'if flag:\n    parser.feed("\\x1b[200~")',
    'mutate(parser)',
    'setattr(parser, "feed", other)',
])
def test_uncertain_prior_state_or_receiver_mutation_prevents_later_rejection(prefix):
    result = inspect(prefix + '\n[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"')
    assert result['decision'] == 'unknown'


def test_parametrized_argument_shadows_same_name_fixture():
    result = inspect('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"',
        decorators='@pytest.mark.parametrize("parser", ["not a fixture"])\n')
    assert result['decision'] == 'unknown'


def test_unsupported_consumer_wrapper_cannot_silently_pass():
    result = inspect('[event] = list(parser.feed("\\x1b[65;4u"))\nassert event.key == "a"')
    assert result['decision'] == 'unknown'
    assert 'wrapped_consumer_flow_unresolved' in result['unknowns']


@pytest.mark.parametrize('bridge', [
    'def unused():\n            self.convert(data)',
    'if False:\n            self.convert(data)',
])
def test_unexecuted_nested_definition_cannot_create_a_protocol_binding(bridge):
    api = 'class Reader:\n    def feed(self, data):\n        ' + bridge + '\n        return []\n    def convert(self, data):\n        """Decode Kitty keyboard protocol CSI into keys."""\n        return []\n'
    assert inspect('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"', api=api)['decision'] == 'unknown'


def test_overwritten_constructor_import_cannot_certify_the_old_class():
    payload, extra = context('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"')
    extra['sources']['test_wire.py'] += '\nDecoder = Other\n'
    assert analyze(payload, **extra)['decision'] == 'unknown'


def test_unverified_source_fragment_or_other_module_helper_is_unknown():
    payload, extra = context('[event] = collect(parser, "\\x1b[65;4u")\nassert event.key == "a"', helpers=HELPER)
    extra['sources']['test_wire.py'] = FIXTURE
    assert analyze(payload, **extra)['decision'] == 'unknown'


def test_indirect_parameterization_requires_fixture_value_analysis():
    assert inspect('[event] = parser.feed("\\x1b[65;4u")\nassert event.key == "a"',
        decorators='@pytest.mark.parametrize("parser", [1], indirect=True)\n')['decision'] == 'unknown'


def test_short_circuited_field_is_not_a_proven_positive_result_use():
    result = inspect('[event] = parser.feed("\\x1b[65;4u")\nassert ready or event.key == "a"')
    assert result['decision'] == 'unknown'
