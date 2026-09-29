"""Joint resource/serialization edits inferred from Python test syntax.

A path construction and a string formatting use are two views of one binding.
Change the resource name and encode the corresponding interpolation together.
No repository, API, case identifier or expected output is matched.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
import hashlib
import json


def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:24]


def generate(corpus, frontend=None, budget=128):
    if corpus['language'] != 'python':
        return []
    trees = {}
    plans = defaultdict(list)
    tests = sorted(corpus['tests'].values(), key=lambda t: (t.get('retrieval_rank') or 10**9, t['id']))
    for test in tests:
        path = test['span']['path']
        text = corpus['sources'][path]['code']
        if path not in trees:
            try:
                tree = ast.parse(text)
            except SyntaxError:
                trees[path] = None
                continue
            offsets = [0]
            for line in text.splitlines(keepends=True):
                offsets.append(offsets[-1] + len(line.encode()))
            trees[path] = tree, offsets
        parsed = trees[path]
        if parsed is None:
            continue
        tree, offsets = parsed

        def span(node):
            return dict(path=path, start_byte=offsets[node.lineno-1]+node.col_offset,
                        end_byte=offsets[node.end_lineno-1]+node.end_col_offset,
                        line=node.lineno, end_line=node.end_lineno)

        def code(node):
            s = span(node)
            return text.encode()[s['start_byte']:s['end_byte']].decode()

        definition = test.get('definition_span', test['span'])
        unit = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and span(n)['start_byte'] == definition['start_byte']), None)
        if unit is None:
            continue
        # Track each simple local's latest direct construction. Nested scopes
        # are deliberately excluded; a same-spelled variable is not identity.
        bindings = {}
        for statement in unit.body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
                name, value = statement.targets[0].id, statement.value
                bindings.pop(name, None)
                if (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div)
                        and isinstance(value.right, ast.Constant) and type(value.right.value) is str
                        and value.right.value and '/' not in value.right.value):
                    bindings[name] = value.right
            # Calls inside lambdas/comprehensions/nested definitions need a
            # different execution cut and are outside this bounded operator.
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for node in ast.walk(statement):
                if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)
                        and isinstance(node.left, ast.Constant) and type(node.left.value) is str
                        and isinstance(node.right, ast.Name) and node.right.id in bindings):
                    continue
                if node.left.value.count('%s') != 1 or '%' in node.left.value.replace('%s', ''):
                    continue
                leaf = bindings[node.right.id]
                stem, dot, extension = leaf.value.rpartition('.')
                stem, tail = (stem, '.'+extension) if dot and stem else (leaf.value, '')
                for marker in (' space', "'quoted"):
                    changed = stem + marker + tail
                    encoded = f'{code(node.left)} % __import__("shlex").quote(str({node.right.id}))'
                    edits = [dict(span=span(leaf), before=code(leaf), after=repr(changed), role='input'),
                             dict(span=span(node), before=code(node), after=encoded, role='input_encoding')]
                    identifier = 'route_' + stable([test['id'], edits])
                    plans[test['id']].append(dict(
                        id=identifier, base_test_id=test['id'], source_test_ids=[], imports=[],
                        language='python', kind='resource_representation_route', edits=edits,
                        relation=dict(domain='resource_serialization', binding=node.right.id,
                                      producer=span(leaf), consumer=span(node),
                                      representation='shell_word',
                                      joint_shape=[any(c.isspace() for c in changed), "'" in changed, True],
                                      status='statically_constructed_runtime_unconfirmed'),
                        oracle=dict(mode='retain_all', applicability='requires_contract_review'),
                        provenance=dict(source_spans=[span(leaf), span(node)],
                                        basis='same lexical path binding consumed by percent interpolation'),
                        runtime_probes=[dict(phase='before_serialized_consumer', insert_before=span(statement),
                                             roles=[dict(name='resource', expression=node.right.id, origin_span=span(leaf)),
                                                    dict(name='component', expression=repr(changed),
                                                         control_expression=repr(leaf.value), origin_span=span(leaf))])]))
    queue = deque(iter(rows) for rows in plans.values())
    result = []
    while queue and len(result) < budget:
        stream = queue.popleft()
        item = next(stream, None)
        if item is not None:
            result.append(item)
            queue.append(stream)
    return result
