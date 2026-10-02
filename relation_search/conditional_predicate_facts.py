"""Small Python type facts about exact, already-selected check predicates.

These facts do not judge a test. They describe a comparison *if it is reached
and both operands evaluate normally*. A false predicate may be unreachable or
its AssertionError intentionally consumed. No implementation output, issue,
execution result, or evaluation label participates.
"""
from __future__ import annotations

import ast
import hashlib


VERSION = 'conditional-builtin-comparison-facts.v1'
PREMISE = ('The comparison is reached and its operands evaluate normally, under '
           'standard Python builtin semantics and without external mutation of '
           'the module namespace or builtin bindings.')
LIMITATION = ('These are conditional expression facts, not reachability, '
              'uncaught-failure, expected-exception, or test-validity judgments.')
_LITERAL_TYPES = {bool: 'number', int: 'number', float: 'number', complex: 'number',
                  str: 'str', bytes: 'bytes', type(None): 'NoneType'}
_CONTAINERS = {ast.List: 'list', ast.Tuple: 'tuple', ast.Dict: 'dict', ast.Set: 'set',
               ast.ListComp: 'list', ast.DictComp: 'dict', ast.SetComp: 'set'}
_DYNAMIC_NAMES = {'exec', 'eval', 'globals', 'locals', 'vars', '__import__',
                  'setattr', 'delattr', '__builtins__'}


def _builtin_len_context(tree):
    """Conservatively reject *any* source binding, including unrelated scopes.

    This intentionally sacrifices some precision to avoid a new scope/dataflow
    engine. A module with no binding called len cannot lexically shadow bare
    len. Runtime namespace/builtin mutation remains an explicit premise.
    """
    reasons = set()
    for node in ast.walk(tree):
        names = set()
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                names.add(node.id)
            if node.id in _DYNAMIC_NAMES:
                reasons.add('visible_dynamic_namespace_or_builtin_operation')
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == '*':
                    reasons.add('wildcard_import')
                names.add(alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
        if 'len' in names:
            reasons.add('source_binding_named_len')
        if isinstance(node, ast.Attribute):
            if isinstance(node.ctx, (ast.Store, ast.Del)) and node.attr == 'len':
                reasons.add('visible_len_attribute_mutation')
            if node.attr in {'setattr', 'delattr', 'patch'}:
                reasons.add('visible_dynamic_namespace_or_builtin_operation')
    return dict(builtin_len_available=not reasons, blockers=sorted(reasons),
                proof_scope='complete_module_no_visible_binding_or_namespace_mutation',
                external_mutation_excluded_by_premise=True)


def _category(node, len_available):
    if isinstance(node, ast.Constant) and type(node.value) in _LITERAL_TYPES:
        return _LITERAL_TYPES[type(node.value)], 'literal_exact_builtin_type'
    if type(node) in _CONTAINERS:
        return _CONTAINERS[type(node)], 'container_syntax_exact_builtin_type'
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Invert))
            and isinstance(node.operand, ast.Constant)
            and type(node.operand.value) in {bool, int, float, complex}):
        return 'number', 'numeric_literal_unary_operation'
    if (len_available and isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == 'len' and len(node.args) == 1
            and not isinstance(node.args[0], ast.Starred) and not node.keywords):
        return 'number', 'unshadowed_builtin_len_returns_int_on_normal_completion'
    return None


def _offsets(code):
    offsets = [0]
    for line in code.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line.encode()))
    return offsets


def _span(node, path, offsets):
    return dict(path=path, start_byte=offsets[node.lineno - 1] + node.col_offset,
                end_byte=offsets[node.end_lineno - 1] + node.end_col_offset,
                line=node.lineno, end_line=node.end_lineno)


def analyze_source(code, *, path='test.py', language='python', predicate_spans=None,
                   max_source_bytes=1000000):
    """Return facts for selected predicates, or top-level assert predicates.

    ``code`` must be the complete module, not a dedented function excerpt.
    Explicit spans must exactly match an AST expression. Only a single == or
    != comparison between disjoint *known builtin* categories is concluded.
    bool/int/float/complex deliberately share a category. Imported aliases,
    variable propagation, arbitrary calls and user-defined equality stay unknown.
    """
    result = dict(version=VERSION, premise=PREMISE, limitation=LIMITATION,
                  status='analyzed', facts=[], unknowns=[], test_validity='unconfirmed')
    if language != 'python':
        return dict(result, status='unsupported_language')
    if not isinstance(code, str) or len(code.encode()) > max_source_bytes:
        return dict(result, status='unknown_source_budget')
    try:
        tree = ast.parse(code, filename=path)
    except (SyntaxError, ValueError, RecursionError):
        return dict(result, status='unknown_python_parse')
    result['source_sha256'] = hashlib.sha256(code.encode()).hexdigest()
    context = _builtin_len_context(tree)
    result['builtin_context'] = context
    offsets = _offsets(code)
    expressions = {(position['start_byte'], position['end_byte']): node
                   for node in ast.walk(tree) if isinstance(node, ast.expr)
                   for position in [_span(node, path, offsets)]}
    if predicate_spans is None:
        selected = [(None, node.test) for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    else:
        selected = []
        for requested in predicate_spans:
            identifier = requested.get('check_id')
            node = expressions.get((requested['start_byte'], requested['end_byte']))
            if requested.get('path', path) != path or node is None:
                result['unknowns'].append(dict(check_id=identifier, reason='predicate_span_not_exact_expression'))
            else:
                selected.append((identifier, node))
    for identifier, predicate in selected:
        at = _span(predicate, path, offsets)
        base = dict(check_id=identifier, predicate_span=at)
        if not (isinstance(predicate, ast.Compare) and len(predicate.ops) == 1
                and isinstance(predicate.ops[0], (ast.Eq, ast.NotEq))):
            result['unknowns'].append(dict(base, reason='unsupported_predicate_shape'))
            continue
        operands = (predicate.left, predicate.comparators[0])
        categories = [_category(node, context['builtin_len_available']) for node in operands]
        if any(value is None for value in categories):
            result['unknowns'].append(dict(base, reason='operand_type_not_established'))
            continue
        if categories[0][0] == categories[1][0]:
            result['unknowns'].append(dict(base, reason='builtin_categories_not_disjoint'))
            continue
        operand_facts = []
        for node, (category, reason) in zip(operands, categories):
            position = _span(node, path, offsets)
            operand_facts.append(dict(span=position,
                text=code.encode()[position['start_byte']:position['end_byte']].decode(),
                type_category=category, derivation=reason))
        outcome = isinstance(predicate.ops[0], ast.NotEq)
        result['facts'].append(dict(base,
            predicate=code.encode()[at['start_byte']:at['end_byte']].decode(),
            operands=operand_facts, operator='!=' if outcome else '==',
            normal_completion_value=outcome,
            reason='disjoint_exact_builtin_equality_categories',
            premise=PREMISE, implies_test_invalid=False))
    return result


def analyze(corpus, frontend, candidate, *, source_analysis):
    """Attach facts only to predicates already selected by the compact graph.

    Reconstruct the complete modified modules to check lexical bindings. Exact
    compact source bytes must agree before a Q reference can receive any fact.
    ``frontend`` is accepted for caller symmetry; it supplies no inferred truth.
    """
    from relation_search.admission import program_candidate
    from relation_search.oracle_evidence import _modified_sources

    result = dict(version=VERSION, premise=PREMISE, limitation=LIMITATION,
                  facts=[], unknowns=[], test_validity='unconfirmed')
    if corpus.get('language') != 'python':
        return dict(result, status='unsupported_language')
    try:
        sources, *_ = _modified_sources(corpus, program_candidate(candidate))
        by_path = {source.path: source for source in sources}
        selected = {}
        for identifier, site in source_analysis.get('obligations', {}).items():
            reference = site.get('predicate')
            if not reference:
                continue
            block = source_analysis['sources'][reference['source']]
            source = by_path[block['path']]
            if source.data[block['start_byte']:block['end_byte']].decode() != block['code']:
                raise ValueError('compact source block differs from modified module')
            selected.setdefault(source.path, []).append(dict(check_id=identifier, path=source.path,
                start_byte=block['start_byte'] + reference['start'],
                end_byte=block['start_byte'] + reference['end']))
        result['modules'] = {}
        for path, predicates in selected.items():
            local = analyze_source(by_path[path].code, path=path, predicate_spans=predicates)
            result['facts'].extend(local.pop('facts'))
            result['unknowns'].extend(local.pop('unknowns'))
            result['modules'][path] = local
        return dict(result, status='analyzed')
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError) as error:
        return dict(result, status='unknown_source_binding', facts=[],
                    unknowns=[dict(reason='modified_source_unavailable', detail=str(error))])
