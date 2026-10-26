"""Lossless transport normalization for independently serialized test edits.

Two append operations on one path are one test file, not two files. Preserve
each fragment and its order. Do not repair code, expected values or test names.
"""
import copy
import json

from augmentation.validation_evolution import validate as base_validate


def parse_completion(text):
    decoder = json.JSONDecoder()
    at, objects = 0, []
    while at < len(text):
        while at < len(text) and text[at].isspace(): at += 1
        if at == len(text): break
        obj, at = decoder.raw_decode(text, at)
        if not isinstance(obj, dict): raise ValueError("response_not_object")
        objects.append(obj)
    if not objects: raise ValueError("empty_completion")
    value = objects[0]
    for other in objects[1:]:
        for key, item in other.items():
            if key in value and value[key] != item:
                raise ValueError("conflicting_serialized_objects")
            value[key] = item
    if len(objects) > 1:
        value["object_transport_normalization"] = "merged_disjoint_top_level_objects"
    return value


def merge_appends(tests):
    if not isinstance(tests, list): return tests, []
    result, events = [], []
    for edit in tests:
        if not isinstance(edit, dict):
            result.append(edit); continue
        previous = next((r for r in result if isinstance(r, dict) and r.get("path") == edit.get("path")), None)
        if (previous is not None and previous.get("mode") == edit.get("mode") == "append"
                and isinstance(previous.get("code"), str) and isinstance(edit.get("code"), str)):
            previous["code"] += "\n\n"+edit["code"]
            events.append({"path": edit.get("path"), "operation": "append_fragments_joined_in_order"})
        else:
            result.append(copy.deepcopy(edit))
    return result, events


def validate(value, stage):
    value = copy.deepcopy(value)
    events = []
    if isinstance(value, dict):
        rows = value.get("hypotheses", []) if stage == 2 else value.get("targets", []) if stage >= 3 else []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict): continue
                owner = row.get("probe", {}) if stage == 2 else row
                if isinstance(owner, dict) and "tests" in owner:
                    owner["tests"], changes = merge_appends(owner["tests"])
                    events.extend({"id": row.get("id"), **e} for e in changes)
    value = base_validate(value, stage)
    if events: value["append_transport_normalization"] = events
    return value
