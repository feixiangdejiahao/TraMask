"""Projection completion for structured protocol examples.

The core is a finite relation: input coordinates -> one observed output field.
We enumerate all *minimum-cardinality* functional dependencies consistent with
the examples. A new row gets an oracle only when every such dependency can look
up a value and the values agree. This is empirical inference, not a proof of
independence: unseen interactions can invalidate it.

The CSI adapter knows the public wire grammar, including the offset bit mask.
It has no case identifiers, test names, expected phases, character policy, or
shifted-alias normalization rule. In particular, it cannot infer a membership
law from a single positive alias assertion.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import itertools
import json
from pathlib import Path
import re


CSI = re.compile(r"\x1b\[([0-9:;]*)([A-Za-z~])\Z")
SUFFIX = re.compile(r"[0-9]+[A-Za-z~]\Z")
UNKNOWN = object()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def evaluate(node, env):
    """Small constant interpreter; never imports or executes subject code."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [evaluate(n, env) for n in node.elts]
    if isinstance(node, ast.Dict):
        return {evaluate(k, env): evaluate(v, env) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.JoinedStr):
        pieces = []
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                value = evaluate(part.value, env)
                if part.conversion != -1:
                    value = {ord("s"): str, ord("r"): repr, ord("a"): ascii}[part.conversion](value)
                pieces.append(format(value, evaluate(part.format_spec, env) if part.format_spec else ""))
            else:
                pieces.append(str(part.value))
        return "".join(pieces)
    if isinstance(node, ast.BinOp):
        a, b = evaluate(node.left, env), evaluate(node.right, env)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.BitOr):
            return a | b
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        a, b = evaluate(node.left, env), evaluate(node.comparators[0], env)
        if isinstance(node.ops[0], (ast.Eq, ast.Is)):
            return a == b
        if isinstance(node.ops[0], (ast.NotEq, ast.IsNot)):
            return a != b
    if isinstance(node, ast.UnaryOp):
        value = evaluate(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = [evaluate(a, env) for a in node.args]
        safe = {"range": lambda *a: list(range(*a)), "str": str, "ord": ord,
                "chr": chr, "int": int, "list": list, "tuple": list}
        if node.func.id in safe:
            return safe[node.func.id](*args)
    raise ValueError("nonconstant expression")


def constant(node, env):
    try:
        return evaluate(node, env)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return UNKNOWN


@dataclass(frozen=True)
class Packet:
    key: str
    alternate: tuple[str, ...] = ()
    modifiers: int = 1
    phase: str = "1"
    text: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value):
        if not isinstance(value, str) or not (match := CSI.fullmatch(value)):
            return None
        groups = match[1].split(";")
        if len(groups) > 3:
            return None
        key = groups[0].split(":")
        modifiers = groups[1].split(":") if len(groups) > 1 else ["1"]
        if len(key) > 3 or len(modifiers) > 2:
            return None
        try:
            return cls((key[0] or "1") + match[2], tuple(key[1:]),
                       int(modifiers[0] or "1"),
                       modifiers[1] if len(modifiers) > 1 else "1",
                       tuple(groups[2].split(":")) if len(groups) > 2 and groups[2] else ())
        except ValueError:
            return None

    def encode(self):
        # Explicit default fields remove syntactic variation from the relation.
        key = ":".join((self.key[:-1], *self.alternate))
        out = f"\x1b[{key};{self.modifiers}:{self.phase}"
        if self.text:
            out += ";" + ":".join(self.text)
        return out + self.key[-1]

    def vector(self, width):
        return (self.key, self.alternate,
                *(((self.modifiers - 1) >> i) & 1 for i in range(width)),
                self.phase, self.text)

    def as_dict(self):
        return {"key": self.key, "alternate": list(self.alternate),
                "modifiers": self.modifiers, "phase": self.phase,
                "text": list(self.text)}

    @classmethod
    def from_vector(cls, row, width):
        return cls(row[0], row[1], 1 + sum(row[2 + i] << i for i in range(width)),
                   row[2 + width], row[3 + width])


@dataclass
class Fact:
    sequence: str
    field: str
    op: str
    expected: object
    source: dict

    def as_dict(self):
        return {"sequence": self.sequence, "field": self.field, "op": self.op,
                "expected": self.expected, "source": self.source}


def parameter_frames(function):
    groups = []
    for deco in function.decorator_list:
        if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
            continue
        if deco.func.attr == "xfail":
            return []
        if deco.func.attr != "parametrize" or len(deco.args) < 2:
            continue
        names, rows = constant(deco.args[0], {}), constant(deco.args[1], {})
        if names is UNKNOWN or rows is UNKNOWN:
            return []
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",")]
        groups.append([dict(zip(names, [row] if len(names) == 1 else row)) for row in rows])
    return [dict(item for g in row for item in g.items()) for row in itertools.product(*groups)]


def projected_assertion(node, env, observed_names=None):
    def observed(attribute):
        value = attribute.value
        while isinstance(value, (ast.Attribute, ast.Subscript)):
            value = value.value
        return observed_names is None or (isinstance(value, ast.Name) and value.id in observed_names)

    if isinstance(node, ast.Attribute) and observed(node):
        return node.attr, "eq", True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and isinstance(node.operand, ast.Attribute) and observed(node.operand):
        return node.operand.attr, "eq", False
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return None
    left, right, op = node.left, node.comparators[0], node.ops[0]
    if isinstance(left, ast.Attribute) and observed(left):
        value = constant(right, env)
        if value is not UNKNOWN:
            kind = "eq" if isinstance(op, (ast.Eq, ast.Is)) else "one_of" if isinstance(op, ast.In) else None
            if kind:
                return left.attr, kind, value
    if isinstance(right, ast.Attribute) and observed(right):
        value = constant(left, env)
        if value is not UNKNOWN:
            kind = "eq" if isinstance(op, (ast.Eq, ast.Is)) else "contains" if isinstance(op, ast.In) else None
            if kind:
                return right.attr, kind, value
    return None


def _input_literals(node, env, helpers):
    """Calls must consume a CSI value; strings in expected assertions are excluded."""
    found = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if not ((isinstance(child.func, ast.Attribute) and child.func.attr == "feed")
                or (isinstance(child.func, ast.Name) and child.func.id in helpers)):
            continue
        for arg in child.args:
            value = constant(arg, env)
            if Packet.parse(value):
                found.append((child.lineno, value))
    return sorted(set(found))


def extract_facts(path, relative, selected_names):
    source = path.read_text()
    tree = ast.parse(source)
    facts = []
    helpers = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                       and child.func.attr == "feed" for child in ast.walk(node))}
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or function.name not in selected_names:
            continue
        for frame in parameter_frames(function):
            env, current, observed_names = dict(frame), None, set()
            # Deliberately do not pretend to interpret arbitrary loops/branches.
            for stmt in function.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assert)):
                    if isinstance(stmt, ast.Assert) and current is not None:
                        projection = projected_assertion(stmt.test, env, observed_names)
                        if projection:
                            attr, op, expected = projection
                            facts.append(Fact(current, attr, op, expected,
                                              {"path": relative, "test": function.name,
                                               "line": stmt.lineno, "parameters": frame,
                                               "assertion": ast.get_source_segment(source, stmt)}))
                    continue
                inputs = _input_literals(stmt, env, helpers)
                if inputs:
                    current = inputs[-1][1]
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    value = constant(stmt.value, env)
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    depends_on_observation = bool(inputs) or any(
                        isinstance(child, ast.Name) and child.id in observed_names
                        for child in ast.walk(stmt.value))
                    for target in targets:
                        names = {child.id for child in ast.walk(target) if isinstance(child, ast.Name)}
                        if depends_on_observation:
                            observed_names.update(names)
                        else:
                            observed_names.difference_update(names)
                    if value is not UNKNOWN:
                        for target in targets:
                            if isinstance(target, ast.Name):
                                env[target.id] = value
    return facts, tree


def infer_dependencies(rows, max_dimensions=16):
    """Return every smallest consistent coordinate set, with no tie breaking.

    Empty dependencies/single-output tables provide no contrast evidence and
    are deliberately rejected. Conflicting identical input rows also reject.
    The cardinality prior is an explicit generalization assumption.
    """
    if not rows or len(rows[0][0]) > max_dimensions:
        return [], "empty_or_dimension_budget"
    differences = set()
    for (a, av), (b, bv) in itertools.combinations(rows, 2):
        if canonical(av) == canonical(bv):
            continue
        diff = frozenset(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
        if not diff:
            return [], "conflicting_examples"
        differences.add(diff)
    if not differences:
        return [], "no_output_contrast"
    varying = sorted(set.union(*(set(d) for d in differences)))
    for size in range(1, len(varying) + 1):
        candidates = [subset for subset in itertools.combinations(varying, size)
                      if all(set(subset) & difference for difference in differences)]
        if candidates:
            return candidates, "empirical_minimum_dependency"
    return [], "no_dependency"


def predict(row, examples, dependencies):
    """Unanimity across all minimum explanations; never use an unseen lookup."""
    predictions = []
    for dependency in dependencies:
        values = {canonical(expected): expected for old, expected in examples
                  if all(old[i] == row[i] for i in dependency)}
        if len(values) != 1:
            return UNKNOWN
        predictions.append(next(iter(values.values())))
    if not predictions or len({canonical(v) for v in predictions}) != 1:
        return UNKNOWN
    return predictions[0]


def _module_file(repository, module):
    relative = Path(*module.split("."))
    for prefix in (repository / "src", repository):
        path = (prefix / relative).with_suffix(".py")
        if path.is_file():
            return path
    return None


def discover_adapter(repository, trees):
    """Resolve a fixture's imported zero-argument constructor and feed method."""
    for tree in trees:
        imports = {alias.asname or alias.name: (node.module, alias.name)
                   for node in tree.body if isinstance(node, ast.ImportFrom) and node.module
                   for alias in node.names}
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        feed_receivers = {node.func.value.id for node in ast.walk(tree)
                          if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                          and node.func.attr == "feed" and isinstance(node.func.value, ast.Name)}
        for receiver in sorted(feed_receivers):
            fixture = functions.get(receiver)
            if fixture is None:
                continue
            for node in ast.walk(fixture):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                    name = node.value.func.id
                    if name in imports and not node.value.args and not node.value.keywords:
                        module, imported = imports[name]
                        module_path = _module_file(repository, module)
                        if module_path:
                            return {"module": module, "class": imported, "method": "feed",
                                    "source": str(module_path.relative_to(repository))}
    return None


def registry_keys(repository, adapter):
    """Read literal key tables in the parser module and its direct imports."""
    module = _module_file(repository, adapter["module"])
    if module is None:
        return [], []
    paths = {module}
    tree = ast.parse(module.read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            path = _module_file(repository, node.module)
            if path:
                paths.add(path)
    found, evidence = set(), []
    for path in sorted(paths):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            values = constant(node, {})
            if not isinstance(values, dict) or len(values) < 2:
                continue
            keys = [k for k, v in values.items() if isinstance(k, str) and SUFFIX.fullmatch(k) and isinstance(v, str)]
            if len(keys) != len(values):
                continue
            found.update(keys)
            evidence.append({"path": str(path.relative_to(repository)), "line": node.lineno,
                             "count": len(keys)})
    return sorted(found), evidence


def learn_and_complete(facts, extra_keys=(), *, guarded=False, derived_fields=None):
    packets = [Packet.parse(f.sequence) for f in facts]
    width = max(1, max((p.modifiers - 1).bit_length() for p in packets)) if packets else 1
    coordinates = ["key_representation", "alternate_codes", *[f"modifier_bit_{i}" for i in range(width)], "event_type", "associated_text"]
    groups = defaultdict(list)
    existing = defaultdict(set)
    vectors = {p.vector(width) for p in packets}
    for fact, packet in zip(facts, packets):
        groups[(fact.field, fact.op)].append((packet.vector(width), fact.expected, fact.source))
        existing[(fact.field, fact.op)].add(packet.vector(width))
    domains = [set(row[i] for row in vectors) for i in range(len(coordinates))]
    if domains:
        domains[0].update(extra_keys)
    obligations, models = [], []
    fitted = {key: infer_dependencies([(row, expected) for row, expected, _ in group])
              for key, group in groups.items()}
    for (field_name, op), group in sorted(groups.items()):
        examples = [(row, expected) for row, expected, _ in group]
        dependencies, reason = fitted[(field_name, op)]
        models.append({"field": field_name, "op": op, "reason": reason,
                       "dependencies": [[coordinates[i] for i in dep] for dep in dependencies],
                       "examples": len(group), "distinct_outputs": len({canonical(v) for _, v in examples})})
        if not dependencies:
            continue
        candidates = {}
        for old, _, _ in sorted(group, key=canonical):
            for index, values in enumerate(domains):
                for value in sorted(values, key=canonical):
                    if value == old[index]:
                        continue
                    row = old[:index] + (value,) + old[index + 1:]
                    # Alternate/text fields only occur in the Unicode form.
                    if row[0][-1] != "u" and (row[1] or row[-1]):
                        continue
                    candidates.setdefault(row, (old, index))
        for row in sorted(candidates, key=canonical):
            if row in existing[(field_name, op)]:
                continue
            expected = predict(row, examples, dependencies)
            if expected is UNKNOWN:
                continue
            old, index = candidates[row]
            if guarded and not any(observed == old and canonical(value) == canonical(expected)
                                   for observed, value, _ in group):
                continue
            obligation = {"sequence": Packet.from_vector(row, width).encode(), "field": field_name,
                          "op": op, "expected": expected,
                          "relation": "unanimous_minimum_projection_dependency",
                          "changed_coordinate": coordinates[index],
                          "seed": Packet.from_vector(old, width).encode(),
                          "support": [source for observed, value, source in group
                                      if canonical(value) == canonical(expected)
                                      and any(all(observed[i] == row[i] for i in dep) for dep in dependencies)]}
            if guarded:
                target_coordinates = set().union(*map(set, dependencies))
                guards = []
                for (other_field, other_op), other_group in groups.items():
                    if other_field == field_name or field_name in (derived_fields or {}).get(other_field, ()):
                        continue
                    other_dependencies, _ = fitted[(other_field, other_op)]
                    other_coordinates = set().union(*map(set, other_dependencies)) if other_dependencies else set()
                    if not target_coordinates & other_coordinates:
                        continue
                    for observed, value, source in other_group:
                        if observed == old:
                            guard = {"field": other_field, "op": other_op, "expected": value}
                            if guard not in guards:
                                guards.append(guard)
                obligation["guards"] = sorted(guards, key=canonical)
                obligation["relation"] = "guarded_minimum_projection_dependency"
            obligation["id"] = "comb_" + hashlib.sha256(canonical(obligation).encode()).hexdigest()[:16]
            obligations.append(obligation)
    return obligations, models, coordinates


def property_dependencies(repository, adapter):
    """Properties that read a target cannot be independent runtime guards."""
    parser_path = _module_file(repository, adapter["module"])
    paths = {parser_path}
    for node in ast.parse(parser_path.read_text()).body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for module in [node.module, *[node.module + "." + alias.name for alias in node.names]]:
                path = _module_file(repository, module)
                if path:
                    paths.add(path)
    relations = defaultdict(set)
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and any(isinstance(d, ast.Name) and d.id == "property" for d in node.decorator_list):
                relations[node.name].update(child.attr for child in ast.walk(node)
                                            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name)
                                            and child.value.id == "self")
    while True:
        expanded = {key: value | set().union(*(relations.get(v, set()) for v in value))
                    for key, value in relations.items()}
        if all(expanded[key] == value for key, value in relations.items()):
            return {key: sorted(value) for key, value in relations.items()}
        relations = expanded


def render_probe(adapter, obligations):
    return '''# Generated locally from input/output projections; no model calls.
import json
import pytest
from {module} import {class_name} as Subject

OBLIGATIONS = json.loads({payload!r})

def normalize(value):
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    return value

def matches(event, predicate):
    actual = normalize(getattr(event, predicate["field"]))
    expected = predicate["expected"]
    if predicate["op"] == "contains":
        return expected in actual
    if predicate["op"] == "one_of":
        return actual in expected
    return actual == expected

@pytest.mark.parametrize("obligation", OBLIGATIONS, ids=[r["id"] for r in OBLIGATIONS])
def test_combination_projection(obligation):
    parser = Subject()
    events = list(parser.{method}(obligation["sequence"]))
    events.extend(parser.{method}(""))
    assert len(events) == 1, (obligation, events)
    if any(not matches(events[0], guard) for guard in obligation.get("guards", [])):
        pytest.skip("projected context guard not established")
    actual = normalize(getattr(events[0], obligation["field"]))
    expected = obligation["expected"]
    if obligation["op"] == "contains":
        assert expected in actual, (obligation, actual)
    elif obligation["op"] == "one_of":
        assert actual in expected, (obligation, actual)
    else:
        assert actual == expected, (obligation, actual)
'''.format(module=adapter["module"], class_name=adapter["class"], method=adapter["method"],
           payload=json.dumps(obligations, sort_keys=True))


def generate_protocol(repository, selection, *, top_k=10, guarded=False):
    """Return source files and audit metadata; caller freezes before evaluation.

    ``selection`` is a retrieval result. All assertions in the first top_k
    retrieved tests are extracted, not just a hand-picked assertion line.
    No issue text, manual annotations, target labels or reference code is read.
    """
    repository = Path(repository)
    anchors = {a["id"]: a for a in selection["anchors"]}
    selected = [anchors[uid] for uid in selection["rankings"]["full"][:top_k]]
    tests = defaultdict(set)
    for anchor in selected:
        if anchor.get("origin") == "repository":
            tests[anchor["path"]].add(anchor["name"])
    facts, trees, hashes = [], [], {}
    for relative, names in sorted(tests.items()):
        path = repository / relative
        if path.suffix != ".py":
            continue
        extracted, tree = extract_facts(path, relative, names)
        facts.extend(extracted)
        trees.append(tree)
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    adapter = discover_adapter(repository, trees)
    metadata = {"algorithm": "minimum_projection_dependency_v1", "top_k": top_k,
                "selected_test_ids": sorted({a["test_id"] for a in selected}),
                "input_hashes": hashes, "model_calls": 0,
                "oracle_status": "empirical_hypothesis_not_proof",
                "facts": [f.as_dict() for f in facts]}
    if not adapter or not facts:
        return {"files": {}, "obligations": [], "skipped": [{"reason": "no_fixture_parser_or_projected_examples"}],
                "metadata": {**metadata, "unsupported": "no_fixture_parser_or_projected_examples"}}
    keys, evidence = registry_keys(repository, adapter)
    derived_fields = property_dependencies(repository, adapter) if guarded else {}
    obligations, models, coordinates = learn_and_complete(facts, keys, guarded=guarded, derived_fields=derived_fields)
    controls = []
    for fact in facts:
        control = fact.as_dict()
        control["id"] = "seed_" + hashlib.sha256(canonical(control).encode()).hexdigest()[:16]
        controls.append(control)
    metadata.update({"adapter": adapter, "registry_evidence": evidence,
                     "coordinates": coordinates, "models": models,
                     "generated_obligations": len(obligations), "seed_controls": len(controls),
                     "guarded": guarded, "derived_fields": derived_fields})
    return {"files": {"tests/test_generated_protocol.py": render_probe(adapter, controls + obligations)},
            "obligations": obligations, "controls": controls,
            "skipped": [m for m in models if not m["dependencies"]], "metadata": metadata,
            "command": "python -m pytest -q tests/test_generated_protocol.py --junitxml=/combination-logs/junit.xml",
            "report_format": "pytest-junit", "report_path": "junit.xml"}


def generate_protocol_transports(repository, selection, *, top_k=10, only_selected_assertions=True):
    """Enumerate syntax-valid proposals without admitting any semantic oracle.

    These rows preserve a source assertion while changing one input coordinate.
    A separate contract stage must decide which transports are justified. The
    output is intentionally *not* marked executable/valid by this generator.
    Positive-only predicates are retained because this stage does not infer
    functional dependencies or require output contrast.
    """
    extracted = generate_protocol(repository, selection, top_k=top_k)
    metadata = extracted["metadata"]
    if "adapter" not in metadata:
        return {"candidates": [], "metadata": metadata}
    facts = [Fact(f["sequence"], f["field"], f["op"], f["expected"], f["source"])
             for f in metadata["facts"]]
    anchors = {a["id"]: a for a in selection["anchors"]}
    selected = [anchors[uid] for uid in selection["rankings"]["full"][:top_k]]
    selected_locations = {(a["path"], a["line"]) for a in selected}
    packets = [Packet.parse(f.sequence) for f in facts]
    width = max(1, max((p.modifiers - 1).bit_length() for p in packets))
    coordinates = metadata["coordinates"]
    rows = [p.vector(width) for p in packets]
    domains = [set(row[i] for row in rows) for i in range(len(coordinates))]
    keys, evidence = registry_keys(Path(repository), metadata["adapter"])
    domains[0].update(keys)
    known = {(row, f.field, f.op, canonical(f.expected)) for row, f in zip(rows, facts)}
    candidates = []
    for fact, old in zip(facts, rows):
        if only_selected_assertions and (fact.source["path"], fact.source["line"]) not in selected_locations:
            continue
        for index, domain in enumerate(domains):
            for value in sorted(domain, key=canonical):
                if value == old[index]:
                    continue
                row = old[:index] + (value,) + old[index + 1:]
                if row[0][-1] != "u" and (row[1] or row[-1]):
                    continue
                if (row, fact.field, fact.op, canonical(fact.expected)) in known:
                    continue
                proposal = {"sequence": Packet.from_vector(row, width).encode(),
                            "field": fact.field, "op": fact.op, "expected": fact.expected,
                            "relation": "unadmitted_one_factor_oracle_transport",
                            "changed_coordinate": coordinates[index],
                            "seed": fact.sequence,
                            "source_assertion": fact.source,
                            "original": dict(zip(coordinates, old)),
                            "followup": dict(zip(coordinates, row)),
                            "source_packet": Packet.from_vector(old, width).as_dict(),
                            "followup_packet": Packet.from_vector(row, width).as_dict(),
                            "donor_sources": [donor.source for donor, other in zip(facts, rows)
                                              if other[index] == value] or evidence}
                proposal["id"] = "transport_" + hashlib.sha256(canonical(proposal).encode()).hexdigest()[:16]
                candidates.append(proposal)
    return {"candidates": candidates, "metadata": {**metadata, "unadmitted_candidates": len(candidates),
             "only_selected_assertions": only_selected_assertions},
            "adapter": metadata["adapter"], "controls": extracted.get("controls", [])}
