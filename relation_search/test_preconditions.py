"""Source-proved applicability checks for edited test calls.

These are counterexamples to applicability, not a test-validity classifier.
An unresolved call or an unsupported type stays unknown. In particular, source
implementation output is never used as an oracle. Literal type discriminants
are checked by their declarations, irrespective of API or property spelling.
"""
from __future__ import annotations

import ast
import inspect
import posixpath
import re
import textwrap

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import CALLS, FUNCTIONS, Source, child, literal, units, walk
from relational_gap.frontend import extract_frontend
from relation_search.oracle_evidence import _modified_sources, _overlap, _resolved_targets


VERSION = 'test_preconditions.v1'
LIMITS = ['Partial source contracts, not a proof that a test is valid.',
          'Dynamic dispatch, spread values, heap/resource setup and embedded languages remain unknown.',
          'Literal structural constraints only; no general TypeScript subtype solver.']


def _span(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte)


def _contained(inner, outer):
    return inner['path'] == outer['path'] and outer['start_byte'] <= inner['start_byte'] <= inner['end_byte'] <= outer['end_byte']


def _handled(call, current):
    """A bad API invocation can be the intended input of a negative test."""
    if any(q.get('observation_type') == 'exception' and _contained(call['span'], q['span'])
           for q in current['observations']):
        return True
    return any(c.get('kind') in {'try_statement', 'catch_clause', 'except_clause'}
               for c in call.get('contexts', []))


def _python_arity(source, declaration, call):
    try:
        function = ast.parse(textwrap.dedent(source.text(declaration))).body[0]
        # Decorators may replace the callable and thereby replace its signature.
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or function.decorator_list:
            return None, 'decorated_or_non_function_signature'
        args, rows = function.args, []
        positional = [*args.posonlyargs, *args.args]
        for i, arg in enumerate(positional):
            kind = inspect.Parameter.POSITIONAL_ONLY if i < len(args.posonlyargs) else inspect.Parameter.POSITIONAL_OR_KEYWORD
            default = None if i >= len(positional) - len(args.defaults) else inspect.Parameter.empty
            rows.append(inspect.Parameter(arg.arg, kind, default=default))
        if args.vararg:
            rows.append(inspect.Parameter(args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            rows.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY,
                default=None if default is not None else inspect.Parameter.empty))
        if args.kwarg:
            rows.append(inspect.Parameter(args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
        positional_values = [None for a in call['arguments'] if a['keyword'] is None]
        keywords = [a['keyword'] for a in call['arguments'] if a['keyword'] is not None]
        if len(keywords) != len(set(keywords)):
            return False, 'duplicate_keyword_argument'
        inspect.Signature(rows).bind(*positional_values, **dict.fromkeys(keywords))
        return True, None
    except TypeError as error:
        return False, str(error)
    except (SyntaxError, ValueError, AttributeError):
        return None, 'signature_not_recovered'


def _parameters(source, declaration):
    params = child(declaration, 'parameters')
    return [p for p in params.named_children if p.type != 'comment'] if params is not None else []


def _arity(source, declaration, call):
    if any(a.get('spread') for a in call['arguments']):
        return None, 'spread_arguments'
    if source.language == 'python':
        # Methods require descriptor/receiver reasoning; do not guess self.
        scope = declaration.parent
        while scope is not None and scope.type not in FUNCTIONS | {'module', 'class_definition'}:
            scope = scope.parent
        if scope is not None and scope.type == 'class_definition':
            return None, 'method_receiver_signature'
        return _python_arity(source, declaration, call)
    minimum = maximum = 0
    for parameter in _parameters(source, declaration):
        pattern = child(parameter, 'pattern', 'name')
        variadic = 'variadic' in parameter.type or (pattern is not None and pattern.type == 'rest_pattern')
        if variadic:
            maximum = None
            # A rest tuple has required initial positions, unlike an array rest.
            typ = child(parameter, 'type')
            value = next(iter(typ.named_children), None) if typ is not None else None
            if value is not None and value.type == 'tuple_type':
                for item in value.named_children:
                    if item.type not in {'rest_type', 'optional_type'}:
                        minimum += 1
            continue
        count = len(parameter.children_by_field_name('name')) if source.language == 'go' else 1
        count = count or 1
        optional = parameter.type == 'optional_parameter' or child(parameter, 'value') is not None
        minimum += 0 if optional else count
        if maximum is not None:
            maximum += count
    count = len(call['arguments'])
    if source.language == 'typescript':
        # JavaScript may intentionally accept extra arguments; only missing
        # declared required inputs are an applicability counterexample here.
        maximum = None
    if source.language == 'go' and count == 1 and call['arguments'][0].get('node_type') in CALLS and minimum > count:
        return None, 'possible_go_multi_value_argument'
    okay = count >= minimum and (maximum is None or count <= maximum)
    return okay, None if okay else dict(required_minimum=minimum, accepted_maximum=maximum, actual=count)


def _module_paths(sources, owner, module, resolution):
    """Explicit module paths only, with no global same-name fallback."""
    source = sources[owner]
    if source.language == 'python':
        if module.startswith('.'):
            dots = len(module) - len(module.lstrip('.'))
            base = posixpath.dirname(source.lookup_path)
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            stem = posixpath.join(base, module[dots:].replace('.', '/'))
            return [p for p in (stem+'.py', stem+'/__init__.py') if p in sources]
        stem = module.replace('.', '/')
        return [p for p in sources if p in {stem+'.py', stem+'/__init__.py'}
                or p.endswith('/'+stem+'.py') or p.endswith('/'+stem+'/__init__.py')]
    if source.language != 'typescript':
        return []
    stems = []
    if module.startswith('.'):
        stems = [posixpath.join(posixpath.dirname(source.lookup_path), module)]
    else:
        matches = []
        for pattern, targets in (resolution.get('aliases') or {}).items():
            if '*' in pattern:
                prefix, suffix = pattern.split('*')
                if not module.startswith(prefix) or not module.endswith(suffix):
                    continue
                capture = module[len(prefix):len(module)-len(suffix) if suffix else None]
            elif module == pattern:
                capture = ''
            else:
                continue
            matches.append(((('*' not in pattern), len(pattern.split('*')[0])), targets, capture))
        if matches:
            priority = max(row[0] for row in matches)
            for _, targets, capture in (row for row in matches if row[0] == priority):
                targets = [targets] if isinstance(targets, str) else targets
                stems.extend(posixpath.join(resolution.get('base_url') or '', t.replace('*', capture)) for t in targets)
    result = []
    for stem in stems:
        stem = posixpath.normpath(stem)
        base, extension = posixpath.splitext(stem)
        replacements = {'.js': ['.ts', '.tsx'], '.jsx': ['.tsx', '.ts'], '.mjs': ['.mts', '.ts'], '.cjs': ['.cts', '.ts']}
        result.extend(p for p in [stem, *(base+e for e in replacements.get(extension, [])),
                                 stem+'.ts', stem+'.tsx', stem+'/index.ts'] if p in sources)
    return list(dict.fromkeys(result))


def _type_declarations(sources, owner, name, resolution, seen=None):
    seen = set() if seen is None else set(seen)
    if (owner, name) in seen:
        return []
    seen.add((owner, name))
    source, result = sources[owner], []
    for statement in source.root.named_children:
        node = child(statement, 'declaration') if statement.type == 'export_statement' else statement
        if node is not None and node.type in {'interface_declaration', 'type_alias_declaration'} and source.text(child(node, 'name')) == name:
            result.append((source, node))
    if result:
        return result
    if name in source.imports and source.imports[name][1]:
        module, original = source.imports[name]
        for path in _module_paths(sources, owner, module, resolution):
            result.extend(_type_declarations(sources, path, original, resolution, seen))
    for module in source.exports:
        for path in _module_paths(sources, owner, module, resolution):
            result.extend(_type_declarations(sources, path, name, resolution, seen))
    return list({(s.path, n.start_byte): (s, n) for s,n in result}.values())


def _unwrap_type(node):
    while node is not None and node.type in {'type_annotation', 'constraint', 'parenthesized_type'}:
        node = next(iter(node.named_children), None)
    return node


def _literal_properties(sources, source, node, declaration, resolution, seen=None):
    """Only requirements forced by a structural declaration are returned."""
    node = _unwrap_type(node)
    seen = set() if seen is None else set(seen)
    if node is None or len(seen) > 12:
        return {}
    key = source.path, node.start_byte, node.end_byte
    if key in seen:
        return {}
    seen.add(key)
    if node.type == 'generic_type':
        node = child(node, 'name')
    if node is not None and node.type == 'type_identifier':
        name = source.text(node)
        generics = child(declaration, 'type_parameters')
        for parameter in generics.named_children if generics is not None else []:
            if source.text(child(parameter, 'name')) == name:
                return _literal_properties(sources, source, child(parameter, 'constraint'), declaration, resolution, seen)
        resolved = _type_declarations(sources, source.path, name, resolution)
        if len(resolved) != 1:
            return {}
        owner, target = resolved[0]
        result = _literal_properties(sources, owner, child(target, 'body', 'value'), target, resolution, seen)
        for clause in target.named_children:
            if clause.type == 'extends_type_clause':
                for parent in clause.named_children:
                    result.update(_literal_properties(sources, owner, parent, target, resolution, seen))
        return result
    if node.type not in {'interface_body', 'object_type'}:
        return {}
    result = {}
    for prop in node.named_children:
        if prop.type != 'property_signature' or any(c.type == '?' for c in prop.children):
            continue
        typ, name = _unwrap_type(child(prop, 'type')), child(prop, 'name')
        if typ is None or typ.type != 'literal_type' or name is None:
            continue
        try:
            result[source.text(name).strip('"\'')] = (literal(source.text(typ)), _span(source, prop))
        except ValueError:
            continue
    return result


def _return_properties(source, declaration):
    """Literal fields common to every direct returned object; no execution."""
    returns = [n for n in walk(child(declaration, 'body'), stop_functions=True) if n.type == 'return_statement']
    if not returns:
        return {}
    common = None
    for returned in returns:
        value = next(iter(returned.named_children), None)
        if value is None or value.type != 'object':
            return {}
        props = {}
        for pair in value.named_children:
            if pair.type != 'pair':
                # A spread can overwrite a previous literal field.
                if pair.type == 'spread_element':
                    props.clear()
                continue
            name, expression = child(pair, 'key'), child(pair, 'value')
            if name is None or name.type not in {'property_identifier', 'string'}:
                continue
            field = source.text(name).strip('"\'')
            props.pop(field, None)
            try:
                props[field] = (literal(source.text(expression)), _span(source, pair))
            except ValueError:
                pass
        common = props if common is None else {k:v for k,v in common.items() if k in props and v[0] == props[k][0]}
    return common or {}


def _signatures(source, declaration):
    # Overloads establish caller contracts, while the implementation signature
    # often uses a wider rest tuple. Do not confuse the two.
    name = source.text(child(declaration, 'name'))
    siblings = declaration.parent.named_children if declaration.parent is not None else []
    if declaration.parent is not None and declaration.parent.type == 'export_statement':
        siblings = declaration.parent.parent.named_children
    overloads = []
    for sibling in siblings:
        node = child(sibling, 'declaration') if sibling.type == 'export_statement' else sibling
        if node is not None and node.type == 'function_signature' and source.text(child(node, 'name')) == name:
            overloads.append(node)
    return overloads or [declaration]


def _node_map(source):
    return {(n.start_byte, n.end_byte): n for n in walk(source.root)}


def analyze(corpus, frontend, candidate):
    """Return deterministic applicability counterexamples/review obligations.

    ``invalid`` requires a source-proved call contradiction outside an existing
    error observation. ``review`` and ``unknown`` must remain in the search;
    neither constitutes permission to report a defect.
    """
    findings = []
    try:
        sources, owner, changes, imports, unknowns = _modified_sources(corpus, candidate)
    except (ValueError, KeyError) as error:
        return dict(version=VERSION, status='invalid', findings=[dict(code='unapplicable_source_edit', evidence=str(error))], changes=[], limits=LIMITS)
    source_map = {s.path:s for s in sources}
    resolution = frontend.get('module_resolution', {})
    if owner.root.has_error:
        original = Source(owner.path, corpus['sources'][owner.path]['code'], owner.language)
        if not original.root.has_error:
            findings.append(dict(code='introduced_parse_error', severity='invalid', span=dict(path=owner.path, start_byte=0, end_byte=len(owner.data))))
        else:
            findings.append(dict(code='existing_parse_error', severity='review', span=dict(path=owner.path, start_byte=0, end_byte=len(owner.data))))
    try:
        current = extract_frontend(sources, test_ids=[candidate['base_test_id']], max_production_depth=0,
            max_production_units=0, module_aliases=resolution.get('aliases'), module_base_url=resolution.get('base_url'),
            go_modules=resolution.get('go_modules'))
    finally:
        for method in (Index.module_paths, Index.reach, Index.field_factors):
            method.cache_clear()
    functions = {f['id']:f for f in current['functions']}
    nodes = {owner.path:_node_map(owner)}
    calls = {(c['span']['path'], c['span']['start_byte'], c['span']['end_byte']):c for c in current['calls']}
    all_units = {}
    for source in sources:
        for unit in units(source)[0]:
            all_units[unit.id] = unit
    edits = [e for e in changes if e['role'] != 'semantic_expected']
    for call in current['calls']:
        if not any(_overlap(edit['span'], call['span']) for edit in edits):
            continue
        targets = _resolved_targets(call, functions, source_map, resolution)
        if len(targets) != 1 or targets[0]['function_id'] not in all_units:
            findings.append(dict(code='edited_call_contract_unresolved', severity='review', span=call['span'], callee=call['callee']))
            continue
        unit = all_units[targets[0]['function_id']]
        declared = _signatures(unit.source, unit.node) if owner.language == 'typescript' else [unit.node]
        valid_signatures, unknown_signatures, arity_errors = [], [], []
        for declaration in declared:
            okay, reason = _arity(unit.source, declaration, call)
            if okay is True:
                valid_signatures.append(declaration)
            elif okay is None:
                unknown_signatures.append(declaration)
            else:
                arity_errors.append(reason)
        severity = 'review' if _handled(call, current) else 'invalid'
        if not valid_signatures and not unknown_signatures:
            findings.append(dict(code='call_signature_contradiction', severity=severity, span=call['span'],
                callee=call['callee'], evidence=dict(declaration=_span(unit.source, unit.node), failures=arity_errors,
                                                  error_observation_or_handler=severity == 'review')))
            continue
        if unknown_signatures:
            findings.append(dict(code='call_signature_not_proved', severity='review', span=call['span'], callee=call['callee']))
        if owner.language != 'typescript' or unknown_signatures:
            continue
        contradictions = []
        for declaration in valid_signatures:
            contradiction = None
            for index, parameter in enumerate(_parameters(unit.source, declaration)):
                if index >= len(call['arguments']):
                    break
                pattern = child(parameter, 'pattern', 'name')
                if pattern is not None and pattern.type == 'rest_pattern':
                    break
                required = _literal_properties(source_map, unit.source, child(parameter, 'type'), declaration, resolution)
                argument = call['arguments'][index]
                nested = calls.get((argument['span']['path'], argument['span']['start_byte'], argument['span']['end_byte']))
                if not nested or not required:
                    continue
                nested_targets = _resolved_targets(nested, functions, source_map, resolution)
                if len(nested_targets) != 1:
                    continue
                producer = all_units.get(nested_targets[0]['function_id'])
                if producer is None:
                    continue
                returned = _return_properties(producer.source, producer.node)
                for field in sorted(required.keys() & returned.keys()):
                    expected, contract_span = required[field]
                    actual, return_span = returned[field]
                    if type(expected) is type(actual) and expected != actual:
                        contradiction = dict(argument=index, property=field, required=expected, returned=actual,
                            required_declaration=contract_span, returned_declaration=return_span,
                            caller_declaration=_span(unit.source, declaration), producer_declaration=_span(producer.source, producer.node))
                        break
                if contradiction:
                    break
            contradictions.append(contradiction)
        if contradictions and all(contradictions):
            findings.append(dict(code='declared_literal_property_contradiction', severity=severity,
                span=call['span'], callee=call['callee'], evidence=contradictions))
    for record in unknowns:
        findings.append(dict(code=record['reason'], severity='review', evidence=record))
    status = 'invalid' if any(f.get('severity') == 'invalid' for f in findings) else 'review' if findings else 'unknown'
    return dict(version=VERSION, status=status, findings=findings, changes=changes, limits=LIMITS)
