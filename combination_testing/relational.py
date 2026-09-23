"""Compile a documented representation relation into a membership transport.

This is a CONTRACT-ASSISTED experiment, not inference from a lone assertion.
The accepted documentation form is ``r: ... produced when m is applied``.
Together with an idempotent bit-set context, it supplies the semantic premise
that r already represents m. An existing alias membership whose terminal is r
can therefore survive adding/removing that represented context bit.

No operator names, field names, modifier-bit positions, output literals, pilot
IDs, or reference implementations are built into the compiler. Source is used
only to identify representation/word wiring; bit roles and oracle values come
from existing assertions. The semantic premise remains an explicit assumption
and is recorded in every generated obligation.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, asdict
import hashlib
from pathlib import Path
import re

from combination_testing.protocol import (Fact, Packet, canonical, discover_adapter,
                                           extract_facts, _module_file, render_probe)


@dataclass(frozen=True)
class RepresentationRole:
    field: str
    operator: str
    modifier_field: str
    observation_field: str
    separator: str
    source: str
    line: int
    declaration: str


ROLE_DECLARATION = re.compile(
    r"^[ \t]*(\w+)[ \t]*:[ \t]*.*?\bproduced when[ \t]+(\w+)[ \t]+is applied\b", re.MULTILINE)


def _self_attribute(node):
    return node.attr if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                         and node.value.id == "self") else None


def representation_roles(tree: ast.Module, source: str) -> list[RepresentationRole]:
    """Find a declared applied-value field flowing into a delimited alias word."""
    roles = []
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        doc = ast.get_docstring(cls) or ""
        for match in ROLE_DECLARATION.finditer(doc):
            field_name, operator = match.groups()
            for assignment in ast.walk(cls):
                if not isinstance(assignment, (ast.Assign, ast.AnnAssign)):
                    continue
                value = assignment.value
                if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                        and value.func.attr == "join" and isinstance(value.func.value, ast.Constant)
                        and isinstance(value.func.value.value, str) and value.func.value.value
                        and len(value.args) == 1):
                    continue
                argument = value.args[0]
                if not (isinstance(argument, ast.BinOp) and isinstance(argument.op, ast.Add)
                        and isinstance(argument.right, (ast.Tuple, ast.List))
                        and len(argument.right.elts) == 1
                        and _self_attribute(argument.right.elts[0]) == field_name):
                    continue
                modifier_field = _self_attribute(argument.left)
                targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
                word_names = {target.id for target in targets if isinstance(target, ast.Name)}
                if not modifier_field or not word_names:
                    continue
                containers = {node.func.value.id for node in ast.walk(cls)
                              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                              and node.func.attr == "append" and isinstance(node.func.value, ast.Name)
                              and len(node.args) == 1 and isinstance(node.args[0], ast.Name)
                              and node.args[0].id in word_names}
                for storage in ast.walk(cls):
                    if not isinstance(storage, (ast.Assign, ast.AnnAssign)):
                        continue
                    if not (isinstance(storage.value, ast.Name) and storage.value.id in containers):
                        continue
                    stored = storage.targets if isinstance(storage, ast.Assign) else [storage.target]
                    for target in stored:
                        observation_field = _self_attribute(target)
                        if observation_field:
                            roles.append(RepresentationRole(field_name, operator, modifier_field,
                                                            observation_field, value.func.value.value,
                                                            source, value.lineno, match[0].strip()))
    return sorted(set(roles), key=lambda role: (role.source, role.line, role.field))


def infer_operator_bit(role: RepresentationRole, facts: list[Fact]):
    """Infer a unique bit from asserted modifier membership, with both outcomes."""
    rows = []
    for fact in facts:
        packet = Packet.parse(fact.sequence)
        if (packet and fact.field == role.modifier_field and fact.op == "eq"
                and isinstance(fact.expected, (tuple, list))
                and all(isinstance(value, str) for value in fact.expected)):
            rows.append((packet.modifiers - 1, role.operator in fact.expected, fact.source))
    if {value for _, value, _ in rows} != {False, True}:
        return None, "missing_operator_contrast", []
    width = max(mask.bit_length() for mask, _, _ in rows)
    bits = [bit for bit in range(width)
            if all(bool(mask & (1 << bit)) == present for mask, present, _ in rows)]
    if len(bits) != 1:
        return None, "ambiguous_operator_bit", [source for _, _, source in rows]
    return bits[0], "unique_asserted_bit_role", [source for _, _, source in rows]


def derive_membership_obligations(facts: list[Fact], roles: list[RepresentationRole]):
    facts_by_sequence = defaultdict(list)
    for fact in facts:
        facts_by_sequence[fact.sequence].append(fact)
    obligations, rejected = [], []
    existing = {(Packet.parse(f.sequence), f.field, f.op, canonical(f.expected)) for f in facts}
    for role in roles:
        bit, reason, bit_support = infer_operator_bit(role, facts)
        if bit is None:
            rejected.append({"role": asdict(role), "reason": reason})
            continue
        for member in facts:
            if (member.field != role.observation_field or member.op != "contains"
                    or not isinstance(member.expected, str)):
                continue
            words = member.expected.split(role.separator)
            # A represented operator must already be consumed in the seed oracle.
            if role.operator in words[:-1]:
                rejected.append({"source": member.source, "reason": "seed_retains_represented_operator"})
                continue
            representations = [fact for fact in facts_by_sequence[member.sequence]
                               if fact.field == role.field and fact.op == "eq"
                               and fact.expected == words[-1]]
            if not representations:
                continue
            packet = Packet.parse(member.sequence)
            changed = Packet(packet.key, packet.alternate,
                             1 + ((packet.modifiers - 1) ^ (1 << bit)), packet.phase, packet.text)
            if (changed, member.field, member.op, canonical(member.expected)) in existing:
                continue
            obligation = {"sequence": changed.encode(), "field": member.field, "op": member.op,
                          "expected": member.expected, "seed": member.sequence,
                          "relation": "documented_representation_absorption",
                          "changed_coordinate": f"modifier_bit_{bit}",
                          "contract": {"role": asdict(role),
                                       "assumption": "a representation of an idempotent context operator absorbs that operator in alias normal form"},
                          "support": [member.source, *[fact.source for fact in representations]],
                          "bit_support": bit_support}
            obligation["id"] = "rel_" + hashlib.sha256(canonical(obligation).encode()).hexdigest()[:16]
            obligations.append(obligation)
    unique = {obligation["id"]: obligation for obligation in obligations}
    return sorted(unique.values(), key=lambda row: row["id"]), rejected


def _reachable_import_files(repository: Path, adapter: dict) -> list[Path]:
    source = repository / adapter["source"]
    paths = {source}
    tree = ast.parse(source.read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            parent = _module_file(repository, node.module)
            if parent:
                paths.add(parent)
            for alias in node.names:
                child = _module_file(repository, node.module + "." + alias.name)
                if child:
                    paths.add(child)
    return sorted(paths)


def generate_relational(repository, selection, *, top_k=10):
    """Produce a separate experimental artifact, with no empirical FD oracles."""
    repository = Path(repository)
    anchors = {anchor["id"]: anchor for anchor in selection["anchors"]}
    selected = [anchors[uid] for uid in selection["rankings"]["full"][:top_k]]
    tests = defaultdict(set)
    for anchor in selected:
        if anchor.get("origin") == "repository":
            tests[anchor["path"]].add(anchor["name"])
    facts, trees, input_hashes = [], [], {}
    for relative, names in sorted(tests.items()):
        if Path(relative).suffix != ".py":
            continue
        path = repository / relative
        extracted, tree = extract_facts(path, relative, names)
        facts.extend(extracted)
        trees.append(tree)
        input_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    adapter = discover_adapter(repository, trees)
    if not adapter:
        return {"files": {}, "obligations": [], "controls": [],
                "skipped": [{"reason": "no_parser_adapter"}], "metadata": {"algorithm": "representation_absorption"}}
    roles = []
    for path in _reachable_import_files(repository, adapter):
        relative = str(path.relative_to(repository))
        roles.extend(representation_roles(ast.parse(path.read_text()), relative))
        input_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    obligations, rejected = derive_membership_obligations(facts, roles)
    controls = []
    for fact in facts:
        control = fact.as_dict()
        control["id"] = "relation_seed_" + hashlib.sha256(canonical(control).encode()).hexdigest()[:16]
        controls.append(control)
    for obligation in obligations:
        support = {canonical(source) for source in obligation["support"] + obligation["bit_support"]}
        obligation["controls"] = [control["id"] for control in controls
                                  if canonical(control["source"]) in support]
    metadata = {"algorithm": "documented_representation_absorption", "top_k": top_k,
                "contract_assisted": True, "oracle_status": "conditional_on_representation_contract",
                "roles": [asdict(role) for role in roles], "input_hashes": input_hashes,
                "model_calls": 0, "generated_obligations": len(obligations)}
    return {"files": {"tests/test_generated_relational.py": render_probe(adapter, controls + obligations)},
            "obligations": obligations, "controls": controls, "skipped": rejected,
            "metadata": metadata,
            "command": "python -m pytest -q tests/test_generated_relational.py --junitxml=/combination-logs/junit.xml",
            "report_format": "pytest-junit", "report_path": "junit.xml"}
