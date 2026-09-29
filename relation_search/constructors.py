"""Compose source input representations at the same call port.

Two bounded AST operations preserve a recipient's complete observation:
extend a literal sequence and its source-demonstrated delimited encoding;
move a symbolic input's outer numeric frame to another source frame while
preserving every interpolation. Neither operation supplies a new oracle.
Donor discovery reads complete source files, so the seed ranking limit does
not silently erase older constructors in those files.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
import copy
import hashlib
import json
import re


def _id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return ...


def _walk(node):
    """Do not interpret nested definitions, decorators, or assertions as input."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, ast.Assert)):
            continue
        yield from _walk(child)


class File:
    def __init__(self, path, code):
        self.path, self.code, self.data = path, code, code.encode()
        self.tree = ast.parse(code)
        self.offsets = [0]
        for line in code.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line.encode()))

    def span(self, node):
        return dict(path=self.path, start_byte=self.offsets[node.lineno-1]+node.col_offset,
                    end_byte=self.offsets[node.end_lineno-1]+node.end_col_offset,
                    line=node.lineno, end_line=node.end_lineno)

    def text(self, node):
        span = self.span(node)
        return self.data[span['start_byte']:span['end_byte']].decode()

    def imports(self, body):
        result = {}
        for node in body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    result[alias.asname or alias.name] = ('.'*node.level+(node.module or '')+'.'+alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    result[alias.asname or alias.name.split('.')[0]] = alias.name
        return result

    def units(self):
        for unit in ast.walk(self.tree):
            if not isinstance(unit, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(n, ast.Assert) for statement in unit.body for n in _walk(statement)):
                continue
            imports = self.imports(self.tree.body) | self.imports(unit.body)
            bindings = defaultdict(list)
            for statement in unit.body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for node in _walk(statement):
                    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                        bindings[node.targets[0].id].append((node.lineno, node.value))
                    elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
                        bindings[node.target.id].append((node.lineno, node.iter))
            calls = []
            for statement in unit.body:
                if isinstance(statement, (ast.Assert, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for call in _walk(statement):
                    if not isinstance(call, ast.Call):
                        continue
                    name = ast.unparse(call.func)
                    root, dot, suffix = name.partition('.')
                    identity = imports.get(root, self.path+'::'+root) + (dot+suffix if dot else '')
                    slots = {str(i): value for i, value in enumerate(call.args)}
                    slots.update({kw.arg: kw.value for kw in call.keywords if kw.arg is not None})
                    calls.append(dict(file=self, unit=unit, call=call, statement=statement,
                                      identity=identity, slots=slots, bindings=bindings))
            yield unit, calls


def _leaves(node, bindings, before, seen=(), depth=0):
    if depth > 8:
        return
    if isinstance(node, (ast.Constant, ast.JoinedStr)):
        yield node
    elif isinstance(node, ast.Name) and node.id not in seen:
        definitions = [item for item in bindings.get(node.id, []) if item[0] <= before]
        if definitions:
            at, value = max(definitions, key=lambda row: row[0])
            yield from _leaves(value, bindings, at, (*seen, node.id), depth+1)
    elif isinstance(node, (ast.BinOp, ast.List, ast.Tuple, ast.Call)):
        children = node.args if isinstance(node, ast.Call) else ast.iter_child_nodes(node)
        for child in children:
            yield from _leaves(child, bindings, before, seen, depth+1)


def _edit(file, node, value, role='input'):
    return dict(span=file.span(node), before=file.text(node), after=value, role=role)


def _candidate(test, target, donor, kind, edits, detail):
    file, source_file = target['file'], donor['file']
    return dict(id='constructor_'+_id([test['id'], kind, edits]),
                base_test_id=test['id'], source_test_ids=[], imports=[], language='python',
                kind=kind, operator=kind, edits=edits,
                selection=dict(base_retrieval_rank=test.get('retrieval_rank')),
                source_provenance=dict(seed=test['id'], source=source_file.span(donor['unit']),
                                       source_call=source_file.span(donor['call']),
                                       recipient_call=file.span(target['call']),
                                       call_identity=target['identity']),
                relation=dict(domain=kind, status='statically_constructed_runtime_unconfirmed', **detail),
                oracle=dict(mode='retain_all', applicability='unknown_requires_contract_review'),
                source_contexts=[dict(path=source_file.path, span=source_file.span(donor['unit']),
                                      code=source_file.text(donor['unit'])[:12000])])


def _encodings(value, members):
    if type(value) is not str or not members:
        return []
    result = []
    for delimiter in sorted(set(re.findall(r'[^\w]+', value))):
        pieces = value.split(delimiter)
        if len(pieces) > len(members) and sorted(pieces[:len(members)]) == sorted(members):
            result.append((delimiter, pieces[len(members):]))
    return result


def _sequence_products(test, target, donors):
    for slot, node in target['slots'].items():
        members = _literal(node)
        if not isinstance(members, (list, tuple)) or not members or len(members) > 8 or not all(type(v) is str for v in members):
            continue
        for donor in donors:
            other = _literal(donor['slots'].get(slot))
            if not isinstance(other, (list, tuple)) or len(other) > 8 or not all(type(v) is str for v in other):
                continue
            for atom in dict.fromkeys(other):
                if atom in members:
                    continue
                extended = [*members, atom]
                output = tuple(extended) if isinstance(members, tuple) else extended
                edits = [_edit(target['file'], node, repr(output))]
                coupled = []
                for other_slot, text_node in target['slots'].items():
                    if other_slot == slot:
                        continue
                    for delimiter, remainder in _encodings(_literal(text_node), members):
                        donor_encodings = _encodings(_literal(donor['slots'].get(other_slot)), other)
                        if not any(d == delimiter for d, _ in donor_encodings):
                            continue
                        edits.append(_edit(target['file'], text_node,
                                           repr(delimiter.join([*extended, *remainder])), 'input_encoding'))
                        coupled.append(other_slot)
                        break
                if coupled:
                    yield _candidate(test, target, donor, 'coupled_sequence_extension', edits,
                                     dict(sequence_slot=slot, encoded_slots=coupled,
                                          previous_length=len(members), next_length=len(extended)))


def _frame_products(test, target, donors):
    for slot, node in target['slots'].items():
        if not isinstance(node, ast.JoinedStr) or len(node.values) < 3:
            continue
        first, last = node.values[0], node.values[-1]
        if not (isinstance(first, ast.Constant) and type(first.value) is str
                and isinstance(last, ast.Constant) and type(last.value) is str):
            continue
        match = re.fullmatch(r'([^\d]+)(\d+)(.*)', first.value, flags=re.S)
        if not match or not match[3] or not re.fullmatch(r'[^\d]+', last.value):
            continue
        for donor in donors:
            source = donor['slots'].get(slot)
            if source is None:
                continue
            for leaf in _leaves(source, donor['bindings'], donor['call'].lineno):
                value = _literal(leaf)
                frame = re.fullmatch(r'([^\d]+)(\d+)([^\d]+)', value, flags=re.S) if type(value) is str else None
                if not frame or frame[1] != match[1] or frame[3] == last.value:
                    continue
                changed = copy.deepcopy(node)
                changed.values[0].value = frame[1]+frame[2]+match[3]
                changed.values[-1].value = frame[3]
                encoded = ast.unparse(changed)
                # No interpolation binding or conversion may change.
                holes = lambda n: [ast.dump(x, include_attributes=False) for x in n.values if isinstance(x, ast.FormattedValue)]
                if holes(ast.parse(encoded, mode='eval').body) != holes(node):
                    continue
                yield _candidate(test, target, donor, 'symbolic_frame_route',
                                 [_edit(target['file'], node, encoded)],
                                 dict(slot=slot, source_frame=donor['file'].span(leaf),
                                      retained_interpolations=holes(node),
                                      flow='bounded_local_may_value_flow'))


def generate(corpus, frontend=None, budget=128, *, max_per_seed=16, max_donors=256):
    if corpus.get('language') != 'python':
        return []
    families, indexed = defaultdict(list), {}
    for path, metadata in sorted(corpus['sources'].items()):
        try:
            file = File(path, metadata['code'])
        except (SyntaxError, ValueError, RecursionError):
            continue
        for unit, calls in file.units():
            indexed[(path, file.span(unit)['start_byte'])] = calls
            for call in calls:
                families[call['identity']].append(call)
    streams = []
    for test in sorted(corpus['tests'].values(), key=lambda row: (row.get('retrieval_rank') or 10**9, row['id'])):
        definition = test.get('definition_span', test['span'])
        calls = indexed.get((definition['path'], definition['start_byte']), [])
        plans, seen = [], set()
        for call in calls:
            donors = families[call['identity']][:max_donors]
            operators = [_sequence_products(test, call, donors), _frame_products(test, call, donors)]
            queue = deque(operators)
            while queue and len(plans) < max_per_seed:
                stream = queue.popleft()
                row = next(stream, None)
                if row is not None:
                    queue.append(stream)
                    if row['id'] not in seen:
                        seen.add(row['id']); plans.append(row)
        if plans:
            streams.append(iter(plans))
    result, queue = [], deque(streams)
    while queue and len(result) < budget:
        stream = queue.popleft()
        row = next(stream, None)
        if row is not None:
            queue.append(stream); result.append(row)
    return result
