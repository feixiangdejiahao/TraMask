import copy

import pytest

from relational_gap.frontend import extract_frontend, to_emitter_corpus
from anchor_retrieval.syntax import Source
from relation_search import negative_exception_template as template


CODE = '''import json
import pytest as pt
from example import validate as inspect_input, Invalid

@pt.mark.parametrize("payload", [{"quota": "α"}, {"quota": "β"}])
def test_rejection(tmp_path, payload):
    file = tmp_path / "input.json"
    file.write_text(json.dumps(payload))
    with pt.raises(Invalid):
        inspect_input(file)
'''


def fixture(code=CODE):
    frontend = extract_frontend([Source('test_subject.py', code, 'python', 'repository')])
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus['tests']))
    start = code.encode().index('"α"'.encode())
    candidate = dict(base_test_id=test_id, edits=[dict(role='input', before='"α"', after='None',
        span=dict(path='test_subject.py', start_byte=start, end_byte=start+len('"α"'.encode())))])
    return corpus, candidate


def test_aliased_exception_template_classifies_without_claiming_field_validity():
    corpus, candidate = fixture()
    before = copy.deepcopy((corpus, candidate))
    result = template.classify(corpus, candidate)
    assert result['status'] == 'eligible'
    assert result['operation_binding'] == ['example', 'validate']
    assert result['semantic_validity_established'] is False
    assert (corpus, candidate) == before


@pytest.mark.parametrize('old,new', [
    ('with pt.raises(Invalid):\n        inspect_input(file)', 'assert inspect_input(file) is None'),
    ('with pt.raises(Invalid):', 'if payload:\n        with pt.raises(Invalid):'),
    ('        inspect_input(file)', '        inspect_input(file)\n        inspect_input(file)'),
    ('        inspect_input(file)', '        assert inspect_input(file)'),
    ('        inspect_input(file)', '        helper(file)'),
    ('with pt.raises(Invalid):', 'with pt.raises(Invalid) as error:'),
    ('with pt.raises(Invalid):', 'with pt.raises(Invalid), another():'),
    ('with pt.raises(Invalid):', 'with pt.raises(Invalid, lambda: inspect_input(file)):'),
    ('file.write_text(json.dumps(payload))', 'file.write_text(json.dumps(payload))\n    assert file.exists()'),
])
def test_positive_mixed_or_indirect_templates_are_withheld(old, new):
    code = CODE.replace(old, new)
    if new.startswith('if payload:'):
        code = code.replace('        inspect_input(file)', '            inspect_input(file)')
    corpus, candidate = fixture(code)
    assert template.classify(corpus, candidate)['status'] != 'eligible'


@pytest.mark.parametrize('change', [
    lambda c: c.replace('def test_rejection(tmp_path, payload):', 'def test_rejection(tmp_path, payload, pt):'),
    lambda c: c.replace('    file =', '    pt = replacement\n    file ='),
    lambda c: c.replace('import pytest as pt', 'import pytest as pt\npt = replacement'),
    lambda c: c.replace('from example import validate as inspect_input, Invalid', 'from example import validate as inspect_input, Invalid\ninspect_input = replacement'),
    lambda c: 'from other import *\n'+c,
])
def test_shadowed_adapter_or_operation_never_establishes_template(change):
    corpus, candidate = fixture(change(CODE))
    assert template.classify(corpus, candidate)['status'] != 'eligible'


def test_expected_exception_edit_is_not_an_input_template_edit():
    corpus, candidate = fixture()
    code = corpus['sources']['test_subject.py']['code'].encode()
    start = code.index(b'Invalid):')
    candidate['edits'][0].update(before='Invalid', span=dict(path='test_subject.py', start_byte=start, end_byte=start+7))
    assert template.classify(corpus, candidate)['reason'] == 'exception_expectation_edited'


def test_stale_utf8_edit_or_nonrepository_source_is_unknown():
    corpus, candidate = fixture()
    candidate['edits'][0]['span']['end_byte'] -= 2
    # A partial multibyte edit is a receipt mismatch, not a classifier crash.
    assert template.classify(corpus, candidate)['status'] == 'unknown'
    corpus, candidate = fixture()
    corpus['sources']['test_subject.py']['origin'] = 'trajectory'
    assert template.classify(corpus, candidate)['status'] == 'unknown'


def test_namespace_renaming_does_not_change_template_eligibility():
    code = CODE.replace('test_rejection', 'test_alternative').replace('quota', 'amount').replace('file', 'resource')
    corpus, candidate = fixture(code)
    assert template.classify(corpus, candidate)['status'] == 'eligible'


@pytest.mark.parametrize('source', [
    CODE.replace('import pytest as pt', 'import pytest as pt\npt.raises = replacement'),
    CODE.replace('    file =', '    pt.raises = replacement\n    file ='),
    CODE.replace('    file =', '    del pt.raises\n    file ='),
    CODE.replace('from example import validate as inspect_input, Invalid',
                 'from example import Invalid\nimport example as api\napi.validate = replacement')
        .replace('inspect_input(file)', 'api.validate(file)'),
])
def test_direct_attribute_rewrites_invalidate_imported_call_binding(source):
    corpus, candidate = fixture(source)
    assert template.classify(corpus, candidate)['reason'] == 'imported_adapter_or_operation_attribute_written'
