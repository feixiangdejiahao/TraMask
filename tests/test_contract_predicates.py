import pytest

from combination_testing.contracts import Predicate


def test_small_predicate_interpreted_without_exec():
    predicate = Predicate('''
def preserves(field, op, expected, source, followup):
    same = source['word'] == followup['word']
    if field == 'value' and same:
        return len(followup['parts']) >= 1
    return False
''')
    assert predicate.permits(field='value', op='eq', expected=1,
                             source={'word': 'x'}, followup={'word': 'x', 'parts': [2]})
    assert not predicate.permits(field='other', op='eq', expected=1,
                                 source={'word': 'x'}, followup={'word': 'x', 'parts': [2]})


def test_local_assignment_expression_obeys_short_circuit_and_does_not_mutate_input():
    predicate = Predicate('''
def preserves(field, op, expected, source, followup):
    value = 7
    if field == 'mask' and (value := int(followup['mask'])) & 2:
        return value == expected
    return value == 7
''')
    packet = {'mask': '3'}
    assert predicate.permits(field='mask', op='eq', expected=3, source={}, followup=packet)
    assert packet == {'mask': '3'}
    assert predicate.permits(field='other', op='eq', expected=None, source={}, followup={})


@pytest.mark.parametrize('body', ["return __import__('os')", "return source.__class__", 
                                 "source['x'] = 1\n    return True", "while True:\n        pass"])
def test_reject_executable_or_mutating_model_code(body):
    with pytest.raises(ValueError):
        Predicate('def preserves(field, op, expected, source, followup):\n    ' + body)
