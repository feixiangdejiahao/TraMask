"""Formatted numeric source strings must not crash generic lexical learning."""
import pytest

from generic_composition.edits import learn_literal_edits


@pytest.mark.parametrize('before,after', [
    ('[x=01]', '[x=02]'),
    ('[x=1]', '[x=002]'),
    ('v1.03', 'v1.04'),
    ('[left=000;right=9]', '[left=001;right=10]'),
])
def test_formatted_numeric_fragments_keep_exact_rule_and_discard_nonreplaying_offset(before, after):
    rules = learn_literal_edits(before, after)
    assert rules
    assert all(rule.apply(before) == after for rule in rules)
    assert all(rule.mode == 'literal' for rule in rules)


def test_plain_numeric_offset_rule_is_still_available():
    rules = learn_literal_edits('[x=1]', '[x=2]')
    assert {rule.mode for rule in rules} == {'literal', 'offset'}
    offset = next(rule for rule in rules if rule.mode == 'offset')
    assert offset.apply('[x=8]') == '[x=9]'
