import ast

import pytest

from prototypes.assertion_write_origin import Module, analyze_assertion
from prototypes.exception_write_priority import evidence, prioritize


def example(*, operation='r.pump()', receiver='r', handler='pytest.raises(ValueError)',
            source_handler=False, finally_close=False, shadow='', q_edit=False):
    subject = '''class Stream:
    def __init__(self):
        self.closed = False
    def pump(self):
        maybe_fail()
        self.close()
    def close(self):
        self.closed = True
'''
    if finally_close:
        subject = subject.replace('        maybe_fail()\n        self.close()',
            '        try:\n            maybe_fail()\n        finally:\n            self.close()')
    statement = '    '+operation
    caught = '    with '+handler+':\n        '+operation
    old = caught if source_handler else statement
    code = ('import pytest\nfrom subject import Stream\n\ndef test_use():\n'
            '    r = Stream()\n    other = Stream()\n'+shadow+old+'\n'
            '    assert '+receiver+'.closed is True\n')
    corpus = dict(language='python', sources={'subject.py': {'code': subject}, 'test_stream.py': {'code': code}})
    module = Module('test_stream.py', code, ast.parse(code))
    q = next(n for n in ast.walk(module.tree) if isinstance(n, ast.Assert))
    analysis = analyze_assertion(corpus['sources'], module.path, q.lineno)
    assertion = dict(span=module.span(q), analysis=analysis, test_ids=['test'])
    at = code.index(old)
    after = caught if not source_handler else old.replace('ValueError', 'RuntimeError')
    edit = dict(span=dict(path=module.path, start_byte=at, end_byte=at+len(old.encode())), before=old, after=after)
    candidate = dict(id='edited', base_test_id='test', imports=[], edits=[edit])
    if q_edit:
        candidate['edits'].append(dict(span=module.span(q), before=module.text(q), after='assert r.closed is False'))
    return corpus, candidate, assertion


def test_new_exception_context_is_related_to_same_object_assertion_writer():
    corpus, candidate, q = example()
    rows = evidence(corpus, candidate, [q])
    assert len(rows) == 1
    assert rows[0]['field'] == 'closed' and rows[0]['writer_method'] == 'close'
    assert rows[0]['source_operation']['start_byte'] < q['span']['start_byte']
    assert rows[0]['possible_bypass_sites'][0]['expression'] == 'maybe_fail()'
    assert 'not_execution_or_oracle_proof' in rows[0]['status']


@pytest.mark.parametrize('options', [dict(receiver='other'), dict(operation='other.pump()'),
    dict(source_handler=True), dict(finally_close=True), dict(q_edit=True),
    dict(handler='unrelated.raises(ValueError)'), dict(shadow='    pytest = custom_handler\n'),
    dict(shadow='    import unrelated as pytest\n')])
def test_unrelated_or_unsupported_context_has_no_priority_evidence(options):
    corpus, candidate, q = example(**options)
    assert evidence(corpus, candidate, [q]) == []


def test_renaming_class_field_variable_preserves_source_evidence():
    corpus, candidate, q = example()
    for old, new in [('Stream', 'Object'), ('closed', 'state_'), ('r.', 'z.')]:
        # Equal-length renaming preserves the source edit offsets for this test.
        for row in corpus['sources'].values():
            row['code'] = row['code'].replace(old, new)
        for edit in candidate['edits']:
            edit['before'] = edit['before'].replace(old, new)
            edit['after'] = edit['after'].replace(old, new)
    corpus['sources']['test_stream.py']['code'] = corpus['sources']['test_stream.py']['code'].replace('    r =', '    z =')
    q['analysis'] = analyze_assertion(corpus['sources'], 'test_stream.py', q['span']['line'])
    assert evidence(corpus, candidate, [q])[0]['field'] == 'state_'


def test_ranking_keeps_all_candidates_and_preserves_order_within_tiers():
    corpus, edited, q = example()
    untouched = dict(edited, id='unchanged', edits=[])
    duplicate = dict(edited, id='same_material')
    result = prioritize(corpus, [untouched, edited, duplicate], {'assertions': [q]})
    assert [r['id'] for r in result['ranking']] == ['edited', 'same_material', 'unchanged']
    assert result['supported_candidates'] == 2
    assert {r['original_rank'] for r in result['ranking']} == {1, 2, 3}


def test_duplicate_calls_do_not_create_an_ambiguous_operation_match():
    corpus, candidate, q = example()
    candidate['edits'][0]['after'] += '\n        r.pump()'
    assert evidence(corpus, candidate, [q]) == []


def test_later_call_after_q_does_not_hide_a_unique_combination_before_q():
    corpus, candidate, q = example()
    corpus['sources']['test_stream.py']['code'] += '    r.pump()\n'
    assert len(evidence(corpus, candidate, [q])) == 1


@pytest.mark.parametrize('constructor', ['Stream()', 'Other()'])
def test_rebinding_same_spelled_receiver_does_not_reuse_old_allocation(constructor):
    corpus, candidate, q = example()
    corpus['sources']['subject.py']['code'] += '\nclass Other(Stream):\n    pass\n'
    # The constructor can even have the same class: allocation identity matters.
    candidate['edits'][0]['after'] = '    r = '+constructor+'\n'+candidate['edits'][0]['after']
    assert evidence(corpus, candidate, [q]) == []


def test_moving_q_into_handler_does_not_preserve_original_q_context():
    corpus, candidate, q = example()
    # A changed whole statement cannot be used as an unchanged source q.
    candidate['edits'].append(dict(span=q['span'], before='assert r.closed is True',
                                   after='    assert r.closed is True'))
    assert evidence(corpus, candidate, [q]) == []
