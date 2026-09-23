"""Regressions for the separately staged keyword-binding patch (v1.1)."""
import pytest

from generic_composition.corpus import build_corpus


def corpus_for(tmp_path, invocation):
    (tmp_path / 'test_binding.py').write_text('''def check(actual, wanted):
    assert actual == wanted
def test_binding():
    payload = "input:1"
    expected = "want:1"
    positional = (parse(payload), expected)
    keywords = {"actual": parse(payload), "wanted": expected}
    ''' + invocation + '\n')
    corpus = build_corpus(tmp_path, 'python')
    capsule = corpus['capsules'][0]
    return corpus, capsule, capsule['helper_assertions'][0]


@pytest.mark.parametrize('invocation, actual_slot, expected_slot', [
    ('check(actual=parse(payload), wanted=expected)', 0, 1),
    ('check(wanted=expected, actual=parse(payload))', 1, 0),
    ('check(parse(payload), wanted=expected)', 0, 1),
    ('check(parse(payload), expected)', 0, 1),
])
def test_actual_and_expected_share_name_aware_binding(tmp_path, invocation, actual_slot, expected_slot):
    corpus, _, helper = corpus_for(tmp_path, invocation)
    assert helper['binding_status'] == 'resolved'
    assert helper['binding_unknowns'] == []
    actual = helper['observed_parameter_origins'][0]
    expected = helper['expected_parameter_origins'][0]
    assert actual['parameter'] == 'actual' and actual['slot'] == actual_slot
    assert actual['actual']['text'] == 'parse(payload)'
    assert expected['parameter'] == 'wanted' and expected['slot'] == expected_slot
    assert expected['actual']['text'] == 'expected'
    assert helper['caller_expected']['text'] == 'expected'
    payload = next(d for d in corpus['donors'] if d.get('text') == '"input:1"')
    wanted = next(d for d in corpus['donors'] if d.get('text') == '"want:1"')
    assert payload['observation_dependency'] and not payload['oracle_dependency']
    assert wanted['oracle_dependency'] and not wanted['observation_dependency']


@pytest.mark.parametrize('invocation', [
    'check(*positional)',
    'check(**keywords)',
    'check(parse(payload), **keywords)',
    'check(*positional, wanted=expected)',
])
def test_spread_arguments_are_unknown_and_never_positionally_guessed(tmp_path, invocation):
    _, capsule, helper = corpus_for(tmp_path, invocation)
    assert helper['binding_status'] == 'unknown'
    assert helper['status'] == 'unsupported_argument_binding'
    assert helper['binding_unknowns'] == ['spread_arguments_not_resolved']
    assert helper['argument_bindings'] == []
    assert helper['observed_parameter_origins'] == []
    assert helper['expected_parameter_origins'] == []
    assert helper['caller_expected'] is None
    assert 'helper_argument_binding_unknown' in capsule['unknowns']


@pytest.mark.parametrize('invocation', [
    'check(parse(payload), actual=parse(payload), wanted=expected)',
    'check(actual=parse(payload), incorrect=expected)',
])
def test_invalid_argument_bindings_also_have_no_partial_oracle_mapping(tmp_path, invocation):
    _, _, helper = corpus_for(tmp_path, invocation)
    assert helper['binding_status'] == 'unknown'
    assert helper['argument_bindings'] == []
    assert helper['caller_expected'] is None
