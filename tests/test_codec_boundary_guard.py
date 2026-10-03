import copy

import pytest

from relation_search.codec_boundary_guard import analyze


def payload(before, after, imports=''):
    return dict(language='python', original_test='def test_case():\n    use(value)',
                modified_test='def test_case():\n    use(value)',
                input_edits=[dict(before=before, after=after, role='input')],
                source_analysis='Source imports\n```\n'+imports+'\n```')


@pytest.mark.parametrize('after,imports,identity', [
    ('__import__("shlex").quote(value)', '', 'shlex.quote'),
    ('shell.quote(value)', 'import shlex as shell', 'shlex.quote'),
    ('q(value)', 'from shlex import quote as q', 'shlex.quote'),
    ('json.dumps(value)', 'import json', 'json.dumps'),
    ('url.quote(value)', 'import urllib.parse as url', 'urllib.parse.quote'),
    ('urllib.parse.urlencode(value)', 'import urllib.parse', 'urllib.parse.urlencode'),
    ('loader("urllib.parse").quote_plus(value)', 'from importlib import import_module as loader', 'urllib.parse.quote_plus'),
])
def test_new_encoder_requires_a_separate_consumer_grammar_obligation(after, imports, identity):
    result = analyze(payload('value', after, imports))
    assert not result['allow_prior_gate']
    assert result['status'] == 'new_codec_adapter_unproved'
    assert result['additions'][0]['identities'] == [identity]


def test_codec_function_is_counted_inside_nested_formatting_expressions():
    result = analyze(payload('"run %s" % value', '"run %s" % __import__("shlex").quote(str(value))'))
    assert not result['allow_prior_gate']
    assert result['additions'][0]['identities'] == ['shlex.quote']


def test_existing_codec_and_changed_literals_keep_the_prior_semantic_obligation():
    assert analyze(payload('json.dumps(a)', 'json.dumps(b)', 'import json'))['allow_prior_gate']
    assert analyze(payload('"first"', '"second"'))['allow_prior_gate']
    assert not analyze(payload('json.dumps(a)', 'json.dumps(json.dumps(a))', 'import json'))['allow_prior_gate']


def test_an_encoder_elsewhere_does_not_establish_this_new_input_boundary():
    row = payload('value', 'shlex.quote(value)', 'import shlex')
    row['original_test'] = 'def test_case():\n    ignored = shlex.quote(other)\n    use(value)'
    assert not analyze(row)['allow_prior_gate']


def test_ambiguity_does_not_make_a_possible_new_codec_disappear():
    row = payload('value', 'encode(value)', 'from json import dumps as encode\nfrom other import encode')
    assert not analyze(row)['allow_prior_gate']


def test_labels_runtime_results_and_model_narrative_cannot_override_the_guard():
    row = payload('value', '__import__("shlex").quote(value)')
    original = copy.deepcopy(row)
    result = analyze(row)
    row.update(case='renamed', evaluation={'valid': True}, runtime='pass', rationale='valid shell quoting')
    assert result == analyze(row)
    assert original['input_edits'] == row['input_edits']


def test_unsupported_python_input_edit_syntax_abstains_and_other_languages_are_explicit():
    assert not analyze(payload('value', 'await ???'))['allow_prior_gate']
    row = payload('x', 'fn(x)')
    row['language'] = 'go'
    assert analyze(row)['status'] == 'outside_python_codec_scope'
