"""Independent v3 order/occurrence audit; all programs below are invented.

The small execution probe uses only functions defined in this test. It checks
statement occurrence counts and order, and never executes a subject repository
or computes an oracle for generation.
"""
from anchor_retrieval.syntax import Source
from prototypes.statement_aligned_test_analogy_v03.alignment import align_analogy
from generic_composition.terms import from_source, render


def term(code):
    return from_source(Source('invented.py', code, 'python'))


def align(A, B, C, **kwargs):
    return align_analogy(*(term(code) for code in (A, B, C)), **kwargs)


A = 'value = make(1)\nassert read(value) == 2\n'
B = 'value = make(1)\ncheckpoint(value)\nassert read(value) == 2\n'


def test_effectful_target_setup_is_preserved_once_before_the_new_operation():
    C = 'arg = prepare()\nvalue = make(arg)\nassert read(value) == 6\n'
    result = align(A, B, C)
    assert result.status == 'hypothesis'
    code = render(result.output)
    assert code.count('prepare()') == 1
    assert code.count('checkpoint(value)') == 1
    assert code.index('prepare()') < code.index('make(arg)') < code.index('checkpoint(value)') < code.index('assert read(value)')
    assert '== 6' in code
    events = []

    def prepare():
        events.append('prepare')
        return 3

    def make(value):
        events.append('make')
        return 2 * value

    def checkpoint(value):
        events.append('checkpoint')

    def read(value):
        events.append('read')
        return value

    exec(compile(code, '<invented-alignment-test>', 'exec'),
         dict(prepare=prepare, make=make, checkpoint=checkpoint, read=read))
    assert events == ['prepare', 'make', 'checkpoint', 'read']


def test_both_sides_inserting_effects_preserve_each_source_order_in_both_merges():
    C = 'value = make(3)\naudit()\nassert read(value) == 6\n'
    outputs = []
    for order in ('residual_first', 'edit_first'):
        result = align(A, B, C, order=order)
        assert result.status == 'hypothesis'
        code = render(result.output)
        assert code.count('audit()') == code.count('checkpoint(value)') == 1
        assert code.index('make(3)') < code.index('audit()') < code.index('assert read(value)')
        assert code.index('make(3)') < code.index('checkpoint(value)') < code.index('assert read(value)')
        assert 'effects' in result.provenance['unproved']
        if order == 'residual_first':
            assert code.index('audit()') < code.index('checkpoint(value)')
        else:
            assert code.index('checkpoint(value)') < code.index('audit()')
        outputs.append(code)
    assert len(set(outputs)) == 2


def test_reassignment_interleavings_do_not_claim_binding_preservation():
    C = 'value = make(3)\nvalue = reload(value)\nassert read(value) == 8\n'
    for order in ('residual_first', 'edit_first'):
        result = align(A, B, C, order=order)
        assert result.status == 'hypothesis'
        code = render(result.output)
        assert code.count('reload(value)') == code.count('checkpoint(value)') == 1
        assert code.index('make(3)') < code.index('reload(value)') < code.index('assert read(value)')
        assert 'bindings_and_capture' in result.provenance['unproved']
        if order == 'residual_first':
            assert code.index('reload(value)') < code.index('checkpoint(value)')
        else:
            assert code.index('checkpoint(value)') < code.index('reload(value)')


def test_repeated_anchor_occurrences_are_not_matched_greedily():
    before = 'ping()\nassert ready()\n'
    edit = 'ping()\ncheckpoint()\nassert ready()\n'
    target = 'ping()\nping()\nassert ready()\n'
    assert align(before, edit, target).status == 'unsupported'


def test_target_branch_is_not_flattened_into_the_outer_statement_sequence():
    C = 'if enabled:\n    value = make(3)\n    assert read(value) == 6\n'
    assert align(A, B, C).status == 'unsupported'


def test_distinct_existing_operations_cannot_be_aligned_in_reverse_order():
    before = 'open_resource()\nclose_resource()\nassert state() == 1\n'
    edit = 'open_resource()\ncheckpoint()\nclose_resource()\nassert state() == 1\n'
    target = 'close_resource()\nopen_resource()\nassert state() == 2\n'
    assert align(before, edit, target).status == 'unsupported'


def test_statement_witness_does_not_prove_inline_expression_effect_linearity():
    # Residual statements have an exact-once witness. A substituted expression
    # can still be copied when B contains several occurrences of the same source
    # value. This hypothesis therefore requires a separate effects admission.
    edit = 'value = make(1)\ncheckpoint(1)\nassert read(value) == 2\n'
    target = 'value = make(prepare())\nassert read(value) == 6\n'
    result = align(A, edit, target)
    assert result.status == 'hypothesis'
    assert render(result.output).count('prepare()') == 2
    assert 'effects' in result.provenance['unproved']
