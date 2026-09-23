"""Small CSI input-domain adapter, not a correctness proof or output oracle.

``unsupported`` means this generator lacks a supported production domain for
the combination. It does not require receivers to reject that byte sequence.
Evidence is public protocol/producer documentation, never evaluation outcomes.
"""
from __future__ import annotations

import re

SPEC = "https://sw.kovidgoyal.net/kitty/keyboard-protocol/"
PRODUCER = "https://github.com/kovidgoyal/kitty/blob/master/kitty/key_encoding.c"
KEY = re.compile(r"([0-9]+)([u~ABCDEFHPQS])\Z")


def _scalar(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        return False
    try:
        number = int(value)
    except ValueError:
        return False
    return 0 <= number <= 0x10FFFF and not 0xD800 <= number <= 0xDFFF


def is_functional_key(key):
    match = KEY.fullmatch(key) if isinstance(key, str) else None
    if not match or not _scalar(match[1]):
        return False
    number = int(match[1])
    return match[2] != "u" or number in {9, 13, 27, 127} or 57344 <= number <= 63743


def input_applicability(packet):
    """Check basic wire ranges and the documented producer-domain boundary."""
    if not isinstance(packet, dict):
        return {"supported": False, "reasons": ["packet_not_mapping"]}
    reasons = []
    key = packet.get("key")
    match = KEY.fullmatch(key) if isinstance(key, str) else None
    if not match or not _scalar(match[1]):
        reasons.append("unsupported_key_form_or_scalar")
    elif match[2] not in {"u", "~"} and int(match[1]) != 1:
        reasons.append("letter_key_form_requires_one")
    elif match[2] != "u" and int(match[1]) == 0:
        reasons.append("nonunicode_key_form_requires_positive_number")
    phase = packet.get("phase", "1")
    if not isinstance(phase, str) or phase not in {"1", "2", "3"}:
        reasons.append("event_type_outside_protocol_range")
    modifiers = packet.get("modifiers", 1)
    if type(modifiers) is not int or not 1 <= modifiers <= 256:
        reasons.append("modifier_wire_value_outside_protocol_range")
    alternate = packet.get("alternate", [])
    if not isinstance(alternate, (list, tuple)) or len(alternate) > 2:
        reasons.append("invalid_alternate_structure")
    elif any(value != "" and not _scalar(value) for value in alternate):
        reasons.append("invalid_alternate_scalar")
    elif any(alternate) and is_functional_key(key):
        reasons.append("functional_alternates_outside_producer_domain")
    text = packet.get("text", [])
    if not isinstance(text, (list, tuple)) or any(not _scalar(value) for value in text):
        reasons.append("invalid_text_scalar")
    elif any(int(value) < 32 or 127 <= int(value) <= 159 for value in text):
        reasons.append("associated_text_contains_control_code")
    return {"supported": not reasons, "reasons": reasons}


def wire_semantics_evidence():
    """Public input facts suitable for a model request; no target assertions."""
    return [
        {"fact": "Event types 1/2/3 occupy a modifiers subfield. The producer's shared serializer emits it before u, tilde, or letter trailers; letter forms include KP_BEGIN with E.",
         "urls": [SPEC + "#event-types", SPEC + "#functional-key-definitions", PRODUCER + "#L63"]},
        {"fact": "The official encode_function_key producer sets add_alternates=false. Functional-key plus alternate values are outside this generator's supported producer domain; this is not a receiver rejection requirement.",
         "urls": [PRODUCER + "#L253"]},
        {"fact": "Associated text consists of Unicode scalar values without control codes. Code zero represents text without a known key. Functional-key plus text and code-zero plus modifiers are not categorically prohibited by this adapter.",
         "urls": [SPEC + "#text-as-code-points", PRODUCER + "#L48", PRODUCER + "#L425"]},
        {"fact": "Modifier wire values are one plus an eight-bit mask; phase values are 1, 2, and 3. Alternate values describe shifted/base-layout keys, rather than independent arbitrary numbers.",
         "urls": [SPEC + "#modifiers", SPEC + "#key-codes"]},
    ]
