import ast

from combination_testing.protocol import Fact, Packet
from combination_testing.relational import (RepresentationRole, derive_membership_obligations,
                                            infer_operator_bit, representation_roles)


def fact(sequence, field, expected, op="eq"):
    return Fact(sequence, field, op, expected, {"path": "example.py", "line": 1})


def role():
    return RepresentationRole("boosted_tag", "boost", "flags", "names", "/", "model.py", 9,
                              "boosted_tag: The tag produced when boost is applied.")


def facts():
    return [fact("\x1b[10;1u", "flags", []),
            fact("\x1b[10;2u", "flags", ["boost"]),
            fact("\x1b[10;4u", "flags", ["boost", "meta"]),
            fact("\x1b[10:20;5u", "boosted_tag", "BIG"),
            fact("\x1b[10:20;5u", "names", "control/BIG", "contains")]


def test_documented_representation_role_has_no_reserved_names():
    source = '''
class Message:
    """Args:
        boosted_tag: The tag produced when boost is applied.
    """
    def __init__(self):
        aliases = []
        word = "/".join(self.flags + (self.boosted_tag,))
        aliases.append(word)
        self.names = aliases
'''
    roles = representation_roles(ast.parse(source), "model.py")
    assert len(roles) == 1
    assert roles[0].operator == "boost"
    assert roles[0].modifier_field == "flags"
    assert roles[0].observation_field == "names"
    assert roles[0].separator == "/"


def test_does_not_invent_contract_from_similar_field_name():
    source = '''
class Message:
    """boosted_tag: An alternate tag."""
    def __init__(self):
        aliases = []
        word = "/".join(self.flags + (self.boosted_tag,))
        aliases.append(word)
        self.names = aliases
'''
    assert representation_roles(ast.parse(source), "model.py") == []


def test_membership_transports_only_asserted_representation():
    obligations, rejected = derive_membership_obligations(facts(), [role()])
    assert not rejected
    assert len(obligations) == 1
    result = obligations[0]
    assert Packet.parse(result["sequence"]).modifiers == 6
    assert result["expected"] == "control/BIG"
    assert result["relation"] == "documented_representation_absorption"
    assert result["contract"]["assumption"]


def test_absent_binding_does_not_get_membership_oracle():
    rows = [f for f in facts() if f.field != "boosted_tag"]
    assert derive_membership_obligations(rows, [role()])[0] == []


def test_confounded_bits_are_rejected():
    rows = [fact("\x1b[10;1u", "flags", []), fact("\x1b[10;4u", "flags", ["boost"])]
    bit, reason, _ = infer_operator_bit(role(), rows)
    assert bit is None
    assert reason == "ambiguous_operator_bit"


def test_unique_bit_role_follows_renamed_offset_position():
    rows = [fact("\x1b[10;1u", "flags", []), fact("\x1b[10;5u", "flags", ["boost"])]
    assert infer_operator_bit(role(), rows)[0] == 2


def test_existing_combination_is_not_regenerated():
    rows = facts() + [fact("\x1b[10:20;6u", "names", "control/BIG", "contains")]
    assert derive_membership_obligations(rows, [role()])[0] == []
