"""Abstain on a new serialization/quoting boundary without an adapter proof.

A scalar return type does not establish the grammar accepted by its consumer.
The narrow guard recognizes public Python standard-library encoder families.
It does not classify the candidate as invalid and does not infer an inverse
from a model's narrative. Other semantic obligations retain their prior gate.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import re
import textwrap

VERSION = 'new-codec-boundary-abstention.v2'
DOMAINS = {
    'shlex.quote': 'one POSIX-shell token',
    'shlex.join': 'POSIX-shell command words',
    'json.dumps': 'JSON text',
    'urllib.parse.quote': 'percent-encoded URL component',
    'urllib.parse.quote_plus': 'form-style percent-encoded component',
    'urllib.parse.urlencode': 'URL query string',
}
AUTHORITIES = ['https://docs.python.org/3/library/shlex.html#shlex.quote',
               'https://docs.python.org/3/library/json.html#json.dumps',
               'https://docs.python.org/3/library/urllib.parse.html#urllib.parse.quote']
POLICY = dict(version=VERSION, language='python', domains=DOMAINS,
    rule='If an edited input adds an encoder from the fixed public registry, abstain. The existing model verdict is not an adapter certificate.',
    inputs='Complete original/modified test, exact input edits, and source import fragments from the already frozen request.',
    fragment_context='A non-standalone input edit is checked through its unique byte-exact embedding in the corresponding complete test AST; missing or ambiguous embeddings abstain.',
    status='unknown input/consumer grammar compatibility; never a claim that the product or test is faulty',
    recovery='Keep this candidate unknown; do not choose a later candidate or another cached verdict.',
    forbidden_inputs=['case or repository IDs', 'known witness lists', 'audit labels', 'native failures', 'reference code', 'model rationale'],
    limitations=['Only the listed encoder families are checked.',
                 'Legitimate new encoders can be withheld until an independently checked adapter relation is available.',
                 'Existing encoder calls and other languages remain under their prior semantic gate.'])


def _parse(text):
    try:
        return ast.parse(textwrap.dedent(text))
    except (SyntaxError, ValueError):
        return None


def _imports(payload):
    bindings = defaultdict(set)
    fragments = [payload.get('original_test', ''), payload.get('modified_test', '')]
    fragments += re.findall(r'```(?:\w+)?\n(.*?)```', payload.get('source_analysis', ''), re.S)
    for fragment in fragments:
        tree = _parse(fragment)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bindings[alias.asname or alias.name.split('.')[0]].add(
                        alias.name if alias.asname else alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                for alias in node.names:
                    if alias.name != '*':
                        bindings[alias.asname or alias.name].add(node.module+'.'+alias.name)
    return {name: sorted(values) for name, values in bindings.items()}


def _identities(node, imports):
    if isinstance(node, ast.Name):
        return set(imports.get(node.id, []))
    if isinstance(node, ast.Attribute):
        return {name+'.'+node.attr for name in _identities(node.value, imports)}
    if isinstance(node, ast.Call) and len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
        name = node.args[0].value
        if not isinstance(name, str):
            return set()
        if isinstance(node.func, ast.Name) and node.func.id == '__import__' and not node.keywords:
            # __import__('a.b') returns a; import_module('a.b') returns a.b.
            return {name.split('.')[0]}
        if 'importlib.import_module' in _identities(node.func, imports) and not node.keywords:
            return {name}
    return set()


def _encoders(text, imports, complete_test=''):
    tree = _parse(text)
    extent = None
    if tree is None:
        # Replacement spans start at their first token. Their later lines keep
        # the original enclosing indentation and need not parse in isolation.
        try:
            tree = ast.parse(complete_test)
        except (SyntaxError, ValueError):
            return None
        data, fragment = complete_test.encode(), text.encode()
        start = data.find(fragment)
        if not fragment or start < 0 or data.find(fragment, start+1) >= 0:
            return None
        extent = start, start+len(fragment)
        starts = [0]
        for line in data.splitlines(keepends=True):
            starts.append(starts[-1]+len(line))
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if extent is not None:
            start = starts[node.lineno-1]+node.col_offset
            end = starts[node.end_lineno-1]+node.end_col_offset
            if not extent[0] <= start < end <= extent[1]:
                continue
        matches = sorted(_identities(node.func, imports) & DOMAINS.keys())
        if matches:
            calls.append(dict(identities=matches, syntax=ast.unparse(node.func),
                              line=node.lineno, domains=[DOMAINS[name] for name in matches]))
    return calls


def analyze(payload):
    if payload.get('language') != 'python':
        return dict(version=VERSION, allow_prior_gate=True, status='outside_python_codec_scope', additions=[])
    imports = _imports(payload)
    additions, unknown = [], []
    for index, edit in enumerate(payload.get('input_edits', [])):
        before = _encoders(edit.get('before', ''), imports, payload.get('original_test', ''))
        after = _encoders(edit.get('after', ''), imports, payload.get('modified_test', ''))
        if before is None or after is None:
            unknown.append(dict(edit=index, reason='input_edit_syntax_unresolved'))
            continue
        remaining = Counter(tuple(row['identities']) for row in before)
        for call in after:
            key = tuple(call['identities'])
            if remaining[key]:
                remaining[key] -= 1
            else:
                additions.append(dict(edit=index, role=edit.get('role'), **call))
    return dict(version=VERSION, allow_prior_gate=not additions and not unknown,
                status='new_codec_adapter_unproved' if additions else 'input_edit_unresolved' if unknown
                else 'no_added_registered_codec', additions=additions, unknown=unknown,
                note='This guard withholds unsupported cross-format assumptions; it does not establish complete semantic validity.')
