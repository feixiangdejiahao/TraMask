"""Structural counterexamples documenting the current priority's scope.

These tests execute generic local toys. A missing or spurious priority is
recorded as a heuristic boundary, not reclassified as a proved defect verdict.
"""
import ast
import sys
import types

import pytest

from experimental.assertion_write_origin import Module, analyze_assertion
from experimental.exception_write_priority import evidence


def example(subject, *, replacement=None, assertion='obj.amount == 20'):
    original = '    obj.apply(False)'
    replacement = replacement or '    with pytest.raises(ValueError):\n        obj.apply(True)'
    code = ('import pytest\nfrom ledger_subject import Ledger\n\ndef test_operation():\n'
            '    obj = Ledger()\n' + original + '\n    assert ' + assertion + '\n')
    module = Module('test_ledger.py', code, ast.parse(code))
    node = next(n for n in ast.walk(module.tree) if isinstance(n, ast.Assert))
    corpus = dict(language='python', sources={
        'ledger_subject.py': dict(code=subject), 'test_ledger.py': dict(code=code)})
    analysis = analyze_assertion(corpus['sources'], module.path, node.lineno)
    q = dict(span=module.span(node), analysis=analysis, test_ids=['generic-test'])
    start = code.index(original)
    candidate = dict(id='generic-candidate', base_test_id='generic-test', imports=[], edits=[
        dict(span=dict(path=module.path, start_byte=start, end_byte=start + len(original)),
             before=original, after=replacement)])
    return corpus, candidate, q, code.replace(original, replacement)


def run(monkeypatch, corpus, code):
    module = types.ModuleType('ledger_subject')
    exec(compile(corpus['sources']['ledger_subject.py']['code'], 'ledger_subject.py', 'exec'), module.__dict__)
    monkeypatch.setitem(sys.modules, 'ledger_subject', module)
    namespace = {}
    exec(compile(code, 'test_ledger.py', 'exec'), namespace)
    namespace['test_operation']()


DIRECT = '''class Ledger:
    def __init__(self):
        self.amount = 17
    def apply(self, fail):
        if fail:
            raise ValueError('interrupted')
        self.amount += 3
'''
DELEGATED = DIRECT.replace('        self.amount += 3',
    '        self.commit()\n    def commit(self):\n        self.amount += 3')


def test_numeric_augmented_write_is_supported_without_boolean_state_names(monkeypatch):
    corpus, candidate, q, generated = example(DELEGATED)
    rows = evidence(corpus, candidate, [q])
    assert rows and rows[0]['field'] == 'amount'
    assert any(w['kind'] == 'AugAssign' for w in q['analysis']['reads'][0]['writers'])
    run(monkeypatch, corpus, corpus['sources']['test_ledger.py']['code'])
    with pytest.raises(AssertionError):
        run(monkeypatch, corpus, generated)


def test_inlining_the_writer_preserves_runtime_failure_and_priority(monkeypatch):
    # Both programs have the same initialization, exceptional bypass and q.
    # The negative behavior is sealed at commit 0b8c556. The common may-exit
    # predicate now also covers the path's terminal write, without a call edge.
    results = []
    for subject in [DIRECT, DELEGATED]:
        corpus, candidate, q, generated = example(subject)
        run(monkeypatch, corpus, corpus['sources']['test_ledger.py']['code'])
        with pytest.raises(AssertionError):
            run(monkeypatch, corpus, generated)
        results.append(bool(evidence(corpus, candidate, [q])))
    assert results == [True, True]


@pytest.mark.parametrize('delegated', [False, True])
def test_direct_and_helper_finally_writers_are_not_bypassed_by_protected_raise(monkeypatch, delegated):
    final = 'self.commit()' if delegated else 'self.amount += 3'
    subject = '''class Ledger:
    def __init__(self):
        self.amount = 17
    def apply(self, fail):
        try:
            if fail:
                raise ValueError('interrupted')
        finally:
            FINAL
'''.replace('FINAL', final)
    if delegated:
        subject += '    def commit(self):\n        self.amount += 3\n'
    corpus, candidate, q, generated = example(subject)
    assert evidence(corpus, candidate, [q]) == []
    run(monkeypatch, corpus, corpus['sources']['test_ledger.py']['code'])
    run(monkeypatch, corpus, generated)


def test_equivalent_try_except_catch_is_outside_pytest_context_adapter(monkeypatch):
    replacement = ('    try:\n        obj.apply(True)\n'
                   '    except ValueError:\n        pass')
    corpus, candidate, q, generated = example(DELEGATED, replacement=replacement)
    assert q['analysis']['reads'][0]['status'] == 'statically_bound_partial_slice'
    assert evidence(corpus, candidate, [q]) == []
    run(monkeypatch, corpus, corpus['sources']['test_ledger.py']['code'])
    with pytest.raises(AssertionError):
        run(monkeypatch, corpus, generated)


def test_syntactically_prior_but_dead_raise_can_receive_priority_without_reaching_q(monkeypatch):
    subject = DELEGATED.replace('if fail:', 'if False:')
    corpus, candidate, q, generated = example(subject)
    rows = evidence(corpus, candidate, [q])
    assert rows and any(site['kind'] == 'explicit_raise' for site in rows[0]['possible_bypass_sites'])
    assert 'possible_call_exceptions_not_proven_feasible' in rows[0]['unknown']
    run(monkeypatch, corpus, corpus['sources']['test_ledger.py']['code'])
    # pytest rejects the expected exception before the source assertion runs.
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        run(monkeypatch, corpus, generated)


def test_object_method_override_is_not_a_proved_call_to_the_old_class_writer(monkeypatch):
    replacement = ('    def substitute(fail):\n        raise ValueError("replacement")\n'
                   '    obj.apply = substitute\n'
                   '    with pytest.raises(ValueError):\n        obj.apply(True)')
    corpus, candidate, q, generated = example(DELEGATED, replacement=replacement)
    rows = evidence(corpus, candidate, [q])
    assert rows and 'dynamic_dispatch_and_external_mutation_not_modeled' in rows[0]['unknown']
    run(monkeypatch, corpus, corpus['sources']['test_ledger.py']['code'])
    with pytest.raises(AssertionError):
        run(monkeypatch, corpus, generated)
    # The state does differ, but its executed operation is the replacement,
    # not the class method whose syntactic writer path supplied the priority.
