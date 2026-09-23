import pytest

from combination_testing.protocol_inputs import input_applicability, is_functional_key, wire_semantics_evidence


def packet(key="120u", **changes):
    return {"key": key, "alternate": [], "modifiers": 1, "phase": "1", "text": [], **changes}


@pytest.mark.parametrize("key", ["13u", "57359u", "63743u", "17~", "1E"])
def test_functional_alternates_are_unsupported_producer_domain(key):
    assert is_functional_key(key)
    result = input_applicability(packet(key, alternate=["88"]))
    assert result == {"supported": False, "reasons": ["functional_alternates_outside_producer_domain"]}


def test_printable_alternates_and_base_layout_hole_are_supported():
    assert input_applicability(packet(alternate=["88", "121"], modifiers=2))["supported"]
    assert input_applicability(packet(alternate=["", "121"]))["supported"]
    assert input_applicability(packet("57359u", alternate=["", ""]))["supported"]


def test_no_unjustified_functional_text_or_zero_modifier_ban():
    assert input_applicability(packet("57359u", text=["937"]))["supported"]
    assert input_applicability(packet("0u", text=["937"], modifiers=7))["supported"]


@pytest.mark.parametrize("key", ["1A", "1B", "1C", "1D", "1E", "1F", "1H", "17~", "120u"])
@pytest.mark.parametrize("phase", ["1", "2", "3"])
def test_event_types_apply_to_all_documented_key_forms(key, phase):
    assert input_applicability(packet(key, phase=phase))["supported"]


@pytest.mark.parametrize("changes", [
    {"key": "55296u"}, {"key": "1114112u"}, {"key": "2A"},
    {"phase": "0"}, {"phase": "4"}, {"modifiers": 0}, {"modifiers": 257},
    {"modifiers": True}, {"alternate": ["55296"]}, {"alternate": ["1", "2", "3"]},
    {"text": ["31"]}, {"text": ["127"]}, {"text": ["159"]}, {"text": ["55296"]},
])
def test_invalid_basic_wire_ranges(changes):
    assert not input_applicability(packet(**changes))["supported"]


def test_unicode_supplementary_scalar_and_full_modifier_mask():
    assert input_applicability(packet("128512u", modifiers=256, text=["128512"]))["supported"]
    assert not is_functional_key("0u")
    assert not is_functional_key("120u")


def test_evidence_has_public_sources_and_no_output_oracle():
    evidence = wire_semantics_evidence()
    assert all(entry["fact"] and entry["urls"] for entry in evidence)
    assert all(url.startswith("https://") for entry in evidence for url in entry["urls"])
    assert all("expected" not in entry for entry in evidence)
