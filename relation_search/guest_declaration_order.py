"""Swap adjacent independent guest declarations without changing host oracles.

The operation targets accidental dependence on compiled declaration slots.
Source call/return bindings establish the executable guest boundary. A source
factory on the same creation path establishes the supported Go-like syntax.
No subject name, historical candidate or runtime result selects an edit.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re

from anchor_retrieval.syntax import CALLS, Source, attr_parts, call_parts, child, walk
from prototypes import relation_search_go_ts as syntax
from relation_search import checked_carrier_inverse as flow

VERSION = 'source-guest-independent-declaration-order.v1'
POLICY = dict(version=VERSION,
    relation='Adjacent independent closed scalar initializations commute; named guest state and the complete host test stay unchanged.',
    purpose='Expose a named cross-instance operation that accidentally depends on guest declaration slots.',
    language='Source-established Go-like guest syntax embedded in Go raw strings.',
    premises=['same source creation path has a callable guest factory',
              'named lookup owner traces to the exact guest literal',
              'adjacent single-line module declarations have closed scalar initializers',
              'each selected name has one binding in the whole guest program',
              'input text is consumed once and owner observations use declared names',
              'no error-text, source-position or direct runtime-object observation'],
    ordering='source path, test position, literal position, first declaration position, candidate hash',
    unchanged='all host setup, operations, assertions and expected expressions; all other guest bytes',
    alert='one complete candidate fails twice with passing source controls and exact transport; independent audit still required',
    forbidden_inputs=['task identities', 'historical candidates', 'runtime outcomes during generation',
                      'audit labels', 'reference implementations', 'hidden tests'],
    limitations=['bounded lexical guest grammar, not an arbitrary-language equivalence proof',
                 'same-file helper inputs must have one direct consumption',
                 'only direct inline source strings and named runtime access are supported',
                 'unresolved source roles abstain; passing controls do not prove an oracle'])

_IDENT = r'[A-Za-z_]\w*'
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|0[bB][01]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'
_SCALAR = rf'(?:[+-]?{_NUMBER}|true|false|undefined|"(?:\\.|[^"\\\r\n])*"|\'(?:\\.|[^\'\\\r\n])*\')'
_DECLARATION = re.compile(rf'^(?P<indent>[ \t]*)(?P<name>{_IDENT})[ \t]*:=[ \t]*(?P<value>{_SCALAR})[ \t]*;?[ \t]*(?:\r?\n)?$')
_DIAGNOSTIC = re.compile(r'(?i)(?:\b(?:line|column|position|location|sourcemap|traceback|stacktrace|bytecode|disassembl\w*|offset)\b|:\d+[:)])')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def declaration_pairs(program):
    """Recognize a deliberately small commutation law in module scope."""
    if '`' in program or re.search(r'(?m)^\s*//\s*(?:line|go:)', program):
        return []
    tokens = [(m.group(), m.start(), m.end()) for m in syntax._GUEST_TOKEN.finditer(program)
              if not m.group().isspace() and not m.group().startswith(('//', '/*'))]
    stack, depth, ends = [], {}, {}
    for i, (token, start, _) in enumerate(tokens):
        depth[start] = len(stack)
        if token in {'(', '[', '{'}:
            stack.append((token, i))
        elif token in {')', ']', '}'}:
            if not stack or {'(': ')', '[': ']', '{': '}'}[stack[-1][0]] != token:
                return []
            _, begin = stack.pop()
            ends[begin] = i
    if stack:
        return []
    bound = Counter()
    for i, (token, _, _) in enumerate(tokens):
        if token == ':=':
            cursor = i-1
            while cursor >= 0 and re.fullmatch(_IDENT, tokens[cursor][0]):
                bound[tokens[cursor][0]] += 1
                if cursor < 2 or tokens[cursor-1][0] != ',':
                    break
                cursor -= 2
        elif token == 'func' and i+1 in ends and tokens[i+1][0] == '(':
            for name, _, _ in tokens[i+2:ends[i+1]]:
                if re.fullmatch(_IDENT, name):
                    bound[name] += 1
        elif token == 'for':
            cursor = i+1
            while cursor < len(tokens) and tokens[cursor][0] not in {'in', ':=', '{', ';'}:
                if re.fullmatch(_IDENT, tokens[cursor][0]):
                    bound[tokens[cursor][0]] += 1
                cursor += 1
    lines, offset, previous, pairs = program.splitlines(keepends=True), 0, None, []
    for line in lines:
        match = _DECLARATION.fullmatch(line)
        current = None
        if match:
            name = match['name']
            position = offset+len(match['indent'])
            if (depth.get(position) == 0 and bound[name] == 1
                    and name not in {'true', 'false', 'undefined', 'func', 'for', 'import', 'export'}):
                current = dict(name=name, start=offset, end=offset+len(line), text=line)
        if previous is not None and current is not None:
            # Both complete lines move together. No following byte/line offset
            # changes, and neither initializer can throw or consume a name.
            pairs.append((previous, current))
        previous = current
        offset += len(line)
    return pairs


def _creation(source, node):
    current = node
    while current.parent is not None:
        current = current.parent
        if current.type in CALLS:
            function, _ = call_parts(current)
            path = syntax._path(source, function)
            if path is None:
                return None
            # Nested text-producing calls are not transparent source inputs.
            parent = current.parent
            while parent is not None and parent.type not in {'short_var_declaration', 'assignment_statement',
                                                             'return_statement', 'expression_statement'}:
                if parent.type in CALLS and call_parts(parent)[1]:
                    return None
                parent = parent.parent
            return current, syntax._import_signature(source, path)
        if current.type not in {'argument_list', 'type_conversion_expression', 'parenthesized_expression', 'selector_expression'}:
            return None
    return None


def _input_safe(source, unit, invocation, literal, seen=()):
    """Prevent a helper from also observing or comparing the raw input text."""
    if invocation.start_byte in seen or len(seen) >= 12:
        return False
    try:
        summary = flow._helper_return(source, unit, invocation, {})
    except ValueError:
        return False
    if summary is None:
        return True
    helper, _, bindings = summary
    tainted = [name for name, (_, actual, _) in bindings.items() if syntax._contains(actual, literal)]
    if len(tainted) != 1:
        return False
    uses = [node for node in walk(helper.body) if node.type == 'identifier' and source.text(node) == tainted[0]]
    if len(uses) != 1:
        return False
    consumed = _creation(source, uses[0])
    return consumed is not None and _input_safe(source, helper, consumed[0], uses[0], (*seen, invocation.start_byte))


def _reaches(source, unit, node, literal, symbol=None):
    try:
        return flow._reaches(source, unit, node, {}, literal, symbol)
    except (ValueError, TypeError, IndexError):
        return False


def _lookups(source, unit, literal):
    rows = []
    for invocation in walk(unit.body):
        if invocation.type not in CALLS:
            continue
        for symbol in [n for n in walk(invocation) if n.type == 'interpreted_string_literal']:
            if _reaches(source, unit, invocation, literal, symbol):
                rows.append((invocation, symbol))
    return rows


def _observation_problem(source, unit, literal, lookups, names):
    def problem(reason, node):
        return dict(reason=reason, source=syntax._span(source, node), text=source.text(node)[:500])
    helpers = {helper.name: helper for helper in flow.units(source)[0] if not helper.test and not helper.owner}
    pending, visited = [unit], set()
    while pending:
        scope = pending.pop()
        if scope.node.start_byte in visited:
            continue
        visited.add(scope.node.start_byte)
        if len(visited) > 32:
            return problem('helper_observation_closure_limit', scope.node)
        for invocation in walk(scope.body):
            if invocation.type == 'field_identifier' and _DIAGNOSTIC.search(source.text(invocation)):
                return problem('diagnostic_field_observed', invocation)
            if invocation.type not in CALLS:
                continue
            function, arguments = call_parts(invocation)
            path = syntax._path(source, function)
            method = path[-1] if path else ''
            if path and len(path) == 1 and path[0] in helpers:
                pending.append(helpers[path[0]])
            if method != 'NoError' and (method.endswith('Error') or method in {'Errorf', 'Fatal', 'Fatalf', 'Fail', 'FailNow'}):
                return problem('error_or_failure_text_observed', invocation)
            if syntax._assertion_call(source, invocation) and any(
                    n.type == 'interpreted_string_literal' and _DIAGNOSTIC.search(source.text(n))
                    for arg in arguments for n in walk(arg)):
                return problem('diagnostic_assertion', invocation)
    for node in walk(unit.body):
        if node.type != 'identifier' or not _reaches(source, unit, node, literal):
            continue
        # A named lookup may be hidden behind a source-checked typed helper.
        if any(syntax._contains(invocation, node) and syntax._constant(source, symbol)[1] in names
               and _input_safe(source, unit, invocation, node)
               for invocation, symbol in lookups):
            continue
        parent, ancestors = node.parent, []
        while parent is not None and parent != unit.body:
            ancestors.append(parent)
            parent = parent.parent
        if any(n.type == 'func_literal' for n in ancestors):
            return problem('captured_runtime_owner', node)
        if any(n.type in CALLS and (path := syntax._path(source, call_parts(n)[0]))
               and path[-1] == 'NoError' for n in ancestors):
            # Running/compiling the program and checking success observes no
            # raw input bytes or diagnostic location.
            continue
        invocation = node.parent
        while invocation is not None and invocation.type not in CALLS:
            if invocation.type in {'func_literal', 'unary_expression', 'short_var_declaration', 'assignment_statement'}:
                break
            invocation = invocation.parent
        if invocation is None or invocation.type not in CALLS:
            return problem('unclassified_runtime_owner_use', node.parent or node)
        function, arguments = call_parts(invocation)
        receiver, _ = attr_parts(function) if function is not None else (None, None)
        if receiver is not None and not arguments and any(
                _reaches(source, unit, query, invocation, symbol) for query, symbol in lookups):
            # An intermediate zero-argument compile/run/clone result lies on
            # the actual return-value path to a checked named lookup.
            continue
        if (receiver is None or not syntax._contains(receiver, node) or len(arguments) != 2
                or syntax._constant(source, arguments[0]) not in {(True, name) for name in names}):
            return problem('unclassified_runtime_owner_use', invocation)
    return None


def generate(corpus, frontend, issue='', *, limit=16):
    del issue  # The relation is source-language commutation, not issue keywords.
    empty = dict(version=VERSION, candidates=[], total_candidates=0, skipped=[])
    if corpus['language'] != 'go':
        return dict(empty, status='language_unsupported')
    sources, tests = {}, {}
    for identifier, test in corpus['tests'].items():
        path = test['span']['path']
        row = corpus['sources'][path]
        if row.get('origin') != 'repository' or row.get('parse_error'):
            continue
        if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:'+path)
        sources.setdefault(path, Source(path, row['code'], 'go', 'repository'))
        tests[(path, test.get('definition_span', test['span'])['start_byte'])] = identifier
    materials, anchors, skipped = [], set(), []
    for path, source in sorted(sources.items()):
        for unit in syntax._tests(source):
            base = tests.get((path, unit.node.start_byte))
            if base is None:
                continue
            for literal in walk(unit.body):
                if literal.type != 'raw_string_literal':
                    continue
                program = source.text(literal)[1:-1]
                factories = syntax._guest_factories(program)
                pairs = declaration_pairs(program)
                if not pairs and not factories:
                    continue
                creation = _creation(source, literal)
                if creation is None:
                    if pairs:
                        skipped.append(dict(base_test_id=base, literal_start=literal.start_byte,
                                            reason='inline_source_creation_unresolved'))
                    continue
                if not _input_safe(source, unit, creation[0], literal):
                    if pairs:
                        skipped.append(dict(base_test_id=base, literal_start=literal.start_byte,
                                            reason='raw_source_input_reused_or_unresolved'))
                    continue
                lookups = _lookups(source, unit, literal)
                if not lookups:
                    if pairs:
                        skipped.append(dict(base_test_id=base, literal_start=literal.start_byte,
                                            reason='no_named_lookup_with_source_provenance'))
                    continue
                for factory in factories:
                    if any(syntax._constant(source, symbol) == (True, factory['name']) for _, symbol in lookups):
                        anchors.add(creation[1])
                materials.append((source, unit, base, literal, creation[1], program, lookups))
    candidates = []
    for source, unit, base, literal, creation, program, lookups in materials:
        pairs = declaration_pairs(program)
        if not pairs:
            continue
        if creation not in anchors:
            skipped.append(dict(base_test_id=base, literal_start=literal.start_byte, reason='no_callable_guest_factory_on_creation_path'))
            continue
        names = set(re.findall(rf'(?m)^\s*({_IDENT})\s*:=', program))
        observation_problem = _observation_problem(source, unit, literal, lookups, names)
        if observation_problem is not None:
            skipped.append(dict(base_test_id=base, literal_start=literal.start_byte, **observation_problem))
            continue
        for left, right in pairs:
            left_body, right_body = left['text'].rstrip('\r\n'), right['text'].rstrip('\r\n')
            swapped = (right_body+left['text'][len(left_body):]
                       +left_body+right['text'][len(right_body):])
            replacement = program[:left['start']]+swapped+program[right['end']:]
            edit = dict(span=syntax._span(source, literal), before=source.text(literal), after='`'+replacement+'`', role='input')
            identifier = 'declorder_'+digest([VERSION, base, edit])[:24]
            candidates.append(dict(id=identifier, base_test_id=base, source_test_ids=[base], imports=[],
                edits=[edit], generator=VERSION, operator='independent_guest_declaration_swap',
                kind='source_semantic_commutation', oracle_status='source_equivalence_pending_native_controls_and_full_audit',
                source_evidence=dict(creation=list(creation), declarations=[left, right],
                    observed_named_symbols=sorted({syntax._constant(source, n)[1] for _, n in lookups}),
                    relation=POLICY['relation']),
                order=[source.path, unit.node.start_byte, literal.start_byte, left['start'], identifier]))
    candidates.sort(key=lambda row: row['order'])
    return dict(version=VERSION, status='source_candidates', candidates=candidates[:limit],
                total_candidates=len(candidates), selected=min(len(candidates), limit), skipped=skipped,
                creation_anchors=[list(key) for key in sorted(anchors)])
