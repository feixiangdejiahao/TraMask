"""Identify a narrow source template for amplifying expected rejection.

This predicate classifies syntax, not input validity. The complete modified
test still needs a contract review. In particular, an exception elsewhere in
the test does not prove that the edited field should be rejected.
"""
from __future__ import annotations

import ast
import hashlib

from relation_search import source_control_context as context

VERSION = 'direct-negative-exception-template.v1'
POLICY = {
    'version': VERSION,
    'purpose': 'Restrict input-validity amplification to existing direct expected-exception templates.',
    'scope': 'Original Python module-level tests with exactly one direct bound pytest.raises region, one direct imported operation in that region, and no other lexical assertions or control flow.',
    'meaning': 'Template eligibility only. Neither exception syntax nor a passing source control establishes rejection of the changed input.',
    'required_afterward': 'Complete-test contract review, fixed-order execution, and independent audit.',
    'unknown': 'Withhold; do not infer that the test is invalid.',
    'ranking': 'Keep original candidate ranks. No refill from later candidates.',
}


def classify(corpus, candidate):
    def result(status, reason, **extra):
        return dict(version=VERSION, status=status, reason=reason,
                    semantic_validity_established=False, **extra)

    if corpus.get('language') != 'python':
        return result('unknown', 'language_unsupported')
    test = corpus.get('tests', {}).get(candidate.get('base_test_id'))
    if test is None:
        return result('unknown', 'base_test_unavailable')
    span = test['span']; path = span['path']
    source = corpus.get('sources', {}).get(path)
    if not source or source.get('origin') != 'repository':
        return result('unknown', 'original_repository_source_required')
    code = source['code']; raw = code.encode(); offsets = context._offsets(code)
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return result('unknown', 'source_parse_failed')
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and all(context._span(node, path, offsets, decorated=True)[key] == span[key]
                       for key in ('start_byte', 'end_byte'))]
    if len(matches) != 1:
        return result('unknown', 'complete_unique_module_test_required')
    function = matches[0]
    module_names, wildcard = context._module_bindings(tree)
    _, _, blocked = context._names(function)
    if wildcard or module_names[function.name] != 1:
        return result('unknown', 'module_binding_ambiguous')
    imports = context._imports(tree)
    # Module rebinding must also invalidate an imported pytest/operation name.
    blocked = set(blocked) | {name for name, count in module_names.items()
                              if name in imports and count != 1}
    regions = [node for node in function.body if isinstance(node, ast.With)]
    if len(regions) != 1:
        return result('withheld', 'requires_one_direct_exception_region')
    region = regions[0]
    if len(region.items) != 1:
        return result('withheld', 'multiple_context_managers')
    adapter = region.items[0].context_expr
    if (not isinstance(adapter, ast.Call)
            or context._import_symbol(adapter.func, imports, blocked) != ('pytest', 'raises')
            or len(adapter.args) != 1 or any(k.arg not in {'match'} for k in adapter.keywords)
            or region.items[0].optional_vars is not None):
        return result('unknown', 'bound_exception_adapter_unresolved')
    if (len(region.body) != 1 or not isinstance(region.body[0], ast.Expr)
            or not isinstance(region.body[0].value, ast.Call)):
        return result('withheld', 'exception_region_has_multiple_or_indirect_actions')
    operation = region.body[0].value
    imported = context._import_symbol(operation.func, imports, blocked)
    if not imported or imported[0] == 'pytest':
        return result('unknown', 'exception_operation_binding_unresolved')
    roots = {context._chain(call.func)[0] for call in (adapter, operation)}
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Attribute, ast.Subscript))
                and isinstance(node.ctx, (ast.Store, ast.Del))):
            owner = node
            while isinstance(owner, (ast.Attribute, ast.Subscript)):
                owner = owner.value
            if isinstance(owner, ast.Name) and owner.id in roots:
                return result('unknown', 'imported_adapter_or_operation_attribute_written')
    forbidden = (ast.Assert, ast.Raise, ast.If, ast.For, ast.AsyncFor, ast.While,
                 ast.Try, ast.AsyncWith, ast.Return, ast.Yield, ast.YieldFrom,
                 ast.Lambda, ast.AsyncFunctionDef, ast.ClassDef, ast.Match)
    for node in ast.walk(function):
        if (isinstance(node, forbidden)
                or isinstance(node, ast.FunctionDef) and node is not function
                or isinstance(node, ast.With) and node is not region):
            return result('withheld', 'additional_observation_or_control_flow')
    edits = candidate.get('edits', [])
    if not edits:
        return result('unknown', 'no_input_edit')
    edited = []
    for edit in edits:
        position = edit.get('span', {})
        if (edit.get('role') != 'input' or position.get('path') != path
                or not span['start_byte'] <= position.get('start_byte', -1)
                < position.get('end_byte', -1) <= span['end_byte']
                or not isinstance(edit.get('before'), str)
                or raw[position['start_byte']:position['end_byte']] != edit['before'].encode()):
            return result('unknown', 'input_edit_receipt_mismatch')
        edited.append(position)
    adapter_span = context._span(adapter, path, offsets)
    if any(p['start_byte'] < adapter_span['end_byte'] and adapter_span['start_byte'] < p['end_byte']
           for p in edited):
        return result('withheld', 'exception_expectation_edited')
    return result('eligible', 'direct_expected_rejection_template',
                  source_sha256=hashlib.sha256(raw).hexdigest(),
                  original_test=dict(span), exception_adapter=adapter_span,
                  operation=context._span(operation, path, offsets),
                  operation_binding=list(imported),
                  binding_limit='Lexical direct imports only. Dynamic monkeypatches, alias effects and fixture effects require complete-test review.',
                  input_to_rejection_binding='Requires complete-test semantic review; not proved by this syntax predicate.')
