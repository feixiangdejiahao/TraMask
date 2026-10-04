"""Bounded SQLite predicate spelling hypotheses from original Python tests.

The constructor recognizes a literal shape, not a SQL consumer or a valid
oracle. An independent complete-test review must establish every premise.
"""
from __future__ import annotations

import ast
import hashlib
import io
import re
import tokenize

from relation_search.absence_null import _Test, _inside, digest
from relation_search import source_control_context as context, test_roles

VERSION = 'source-sql-predicate-clamp-hypotheses.v1'
MAX_CANDIDATES = 16
PREDICATE = re.compile(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|<|>)\s*([+-]?[0-9]+)\s*', re.ASCII)
CLAMP = {'<': 'min', '>': 'max', '<=': 'max', '>=': 'min'}
POLICY = dict(
    version=VERSION, language='python', max_candidates=MAX_CANDIDATES,
    construction='Replace a complete direct call-argument string literal x op integer with clamp(x, integer) op integer. Use min for < or >=, max for > or <=.',
    ordering='retrieval_rank, source path, literal start byte',
    grammar='One ASCII identifier, one of < > <= >=, and one signed decimal integer in the SQLite INTEGER range. No SQL statement, quoted identifier, expression, subquery or general SQL parser.',
    scope='Complete original module-level Python tests with an assertion or bound pytest.raises. Direct positional or keyword literals only; exclude decorators, assertions, expected-value dependencies, pytest adapter arguments and nested functions.',
    unchanged='The complete original test, decorators, setup, operations, all assertions and original control, except one literal spelling.',
    input_role='Syntactic call argument only. Unknown receiver/consumer binding remains explicit and must be resolved by review; no task or API name selects candidates.',
    premises='A SQLite expression consumer; built-in unoverridden two-argument min/max; one stable numeric-or-NULL field value; numeric comparison without text/blob affinity changes; preservation of the whole consumer contract and every assertion.',
    admission='Fresh source-only complete-test semantic review must establish dialect, binding, value domain and unchanged whole-test expectations. Unknown premises do not execute.',
    semantics='Source hypotheses only. Literal syntax does not prove SQL applicability, expression equivalence at the consumer, or oracle correctness.',
    novelty='A narrow development experiment in representation-equivalent predicates; no novelty claim for clamping or SQL rewriting alone.',
    forbidden_inputs=['case identities', 'runtime outcomes', 'old candidates', 'audit labels', 'hidden tests', 'reference implementations'],
)


def rewrite(value):
    if not isinstance(value, str):
        return None
    match = PREDICATE.fullmatch(value)
    if match is None:
        return None
    name, operator, bound = match.groups()
    # Long decimal tokens are outside this finite literal grammar and need not
    # enter Python's arbitrary-precision integer parser.
    digits = bound.lstrip('+-')
    if len(digits) > 19 or not -(2**63) <= int(bound) < 2**63:
        return None
    function = CLAMP[operator]
    return dict(identifier=name, operator=operator, bound_sql=bound,
                function=function, value_before=value,
                value_after=f'{function}({name}, {bound}) {operator} {bound}')


def _one_literal(text):
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
                  if t.type not in {tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER}]
    except (tokenize.TokenError, IndentationError):
        return False
    return len(tokens) == 1 and tokens[0].type == tokenize.STRING


def generate(corpus, frontend, issue, *, limit=16):
    if type(limit) is not int or not 0 <= limit <= MAX_CANDIDATES:
        raise ValueError('limit must be an integer from 0 through 16')
    empty = dict(version=VERSION, candidates=[], catalog=[], total_candidates=0, selected=0, skipped=[])
    if corpus.get('language') != 'python':
        return dict(empty, status='language_unsupported')
    sources = {p: r for p, r in corpus['sources'].items() if r.get('origin') == 'repository'}
    tests = {k: t for k, t in corpus['tests'].items() if t['span']['path'] in sources}
    role_corpus = dict(corpus, sources=sources, tests=tests)
    trees, role_cache, candidates, skipped = {}, {}, [], []
    for identifier, test in sorted(tests.items()):
        path = test['span']['path']; row = sources[path]
        if not row.get('complete_file', True) or row.get('language', 'python') != 'python' or row.get('parse_error'):
            continue
        if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:' + path)
        if path not in trees:
            try:
                trees[path] = ast.parse(row['code'])
            except (SyntaxError, ValueError):
                trees[path] = None
        tree = trees[path]
        if tree is None:
            continue
        definition = test.get('definition_span', test['span'])
        functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == test['name'] and n.lineno == definition['line']]
        if len(functions) != 1:
            continue
        scope = _Test(path, row['code'], tree, functions[0], test)
        if scope.wildcard or scope.module_names[scope.fn.name] != 1 or not scope.has_observation():
            continue
        original = test['span']; full = context._span(scope.fn, path, scope.offsets, decorated=True)
        if any(original[k] != full[k] for k in ('start_byte', 'end_byte')):
            skipped.append(dict(base_test_id=identifier, reason='incomplete_original_test_span')); continue
        raw = row['code'].encode()
        complete = dict(original, source_sha256=hashlib.sha256(raw).hexdigest(),
                        text=raw[original['start_byte']:original['end_byte']].decode())
        for node in ast.walk(scope.fn):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            relation = rewrite(node.value)
            if relation is None:
                continue
            position = scope.span(node)
            try:
                parent = scope.parents.get(node)
                call = scope.parents.get(parent) if isinstance(parent, ast.keyword) else parent
                if not isinstance(call, ast.Call) or not (node in call.args or
                        isinstance(parent, ast.keyword) and parent in call.keywords):
                    raise ValueError('not_direct_call_argument_literal')
                if (scope.oracle_context(node) or any(_inside(position, scope.span(d)) for d in scope.fn.decorator_list)):
                    raise ValueError('oracle_decorator_or_nested_region')
                before = scope.receipt(node)['text']
                if not _one_literal(before):
                    raise ValueError('not_one_source_string_literal')
                if identifier not in role_cache:
                    role_cache[identifier] = test_roles.analyze(role_corpus, frontend,
                        dict(id='original_sql_roles', base_test_id=identifier, edits=[], imports=[]))
                roles = role_cache[identifier]
                if any(u.get('code') in {'source_role_analysis_unavailable', 'modified_test_owner_not_recovered',
                                         'role_depth_budget', 'call_context_budget_or_recursion'} for u in roles['unknowns']):
                    raise ValueError('source_role_analysis_unresolved')
                if any(r['role'] == 'expected' and _inside(position, r['span']) for r in roles['roles']):
                    raise ValueError('source_expected_value_dependency')
            except ValueError as error:
                skipped.append(dict(base_test_id=identifier, span=position, reason=str(error))); continue
            binding = scope.consumer(call)
            evidence = dict(predicate=relation, literal=scope.receipt(node), call=scope.receipt(call),
                original_test=complete, consumer_binding=binding,
                consumer_status='source_binding_hint' if binding else 'unresolved_consumer',
                dialect_status='unproved', numeric_or_null_values='unproved',
                input_role='syntactic_argument_hypothesis_requires_complete_review',
                oracle_preservation_proved=False,
                issue_sha256=hashlib.sha256(issue.encode()).hexdigest())
            edit = dict(span=position, before=before, after=repr(relation['value_after']), role='input')
            rank = test.get('retrieval_rank')
            rank = rank if type(rank) is int and rank >= 0 else 10**12
            candidates.append(dict(id='sqlclamp_' + digest([VERSION, identifier, edit])[:24],
                base_test_id=identifier, source_test_ids=[identifier], imports=[], edits=[edit],
                generator=VERSION, operator='sqlite_scalar_clamp_predicate', kind='source_input_hypothesis',
                oracle_status='unchanged_oracle_requires_semantic_review', source_evidence=evidence,
                order=[rank, path, position['start_byte']]))
    candidates.sort(key=lambda x: x['order'])
    selected = candidates[:limit]
    return dict(version=VERSION, status='source_hypotheses', candidates=selected,
                catalog=[x['source_evidence'] for x in selected], total_candidates=len(candidates),
                selected=len(selected), skipped=skipped)
