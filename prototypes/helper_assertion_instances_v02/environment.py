"""Lexical identities for an open call term; values/effects are never executed."""
from anchor_retrieval.syntax import CALLS, Source, child, walk
from prototypes.test_edit_analogy_v02.bindings import _Index, _value_reference
from prototypes.helper_assertion_instances_v01.core import _contains, _span
from generic_composition.terms import subterms


_VARIABLES = {'parameter', 'local', 'var'}
_BINDERS = {'function_definition', 'function_declaration', 'function_expression', 'arrow_function',
            'lambda', 'func_literal', 'class_definition', 'class', 'named_expression',
            'list_comprehension', 'dictionary_comprehension', 'set_comprehension', 'generator_expression'}


def identity(source, index, node, *, undo_shift=lambda offset: offset):
    binding, status, reason = index.resolve(source.text(node), node)
    if binding is not None:
        label = ('lexical_binding', source.path, binding.kind, undo_shift(binding.node.start_byte),
                 binding.scope.kind, undo_shift(binding.scope.node.start_byte))
    elif reason == 'language_builtin':
        label = ('builtin_binding', source.language, source.text(node))
    else:
        scope = index.scope_for[node.id]
        label = ('unresolved_binding', source.path, scope.kind, undo_shift(scope.node.start_byte), source.text(node))
    return label, binding, status, reason


def declaration(source, binding):
    if binding is None:
        return None
    node = binding.node
    while node.parent is not None and node.parent.type not in {
            'module', 'program', 'source_file', 'block', 'statement_block', 'statement_list',
            'parameter_list', 'parameters', 'formal_parameters'}:
        node = node.parent
    return {'span': _span(source, node), 'code': source.text(node), 'kind': binding.kind}


def collect(source, index, statement, tree, ports):
    """Return occurrence identities, declaration evidence, calls and unknowns."""
    if any(n.type in _BINDERS for n in walk(statement)):
        return None, 'binder_inside_instance_requires_scope_transport'
    terms = dict(subterms(tree.term))
    paths = {(span.start_byte, span.end_byte): path for path, span in tree.spans.items()
             if terms[path].kind in {'identifier', 'shorthand_property_identifier'}}
    references, calls, unknowns = [], [], []
    for node in walk(statement):
        if node.type in CALLS:
            calls.append({'span': _span(source, node), 'text': source.text(node), 'effects': 'unknown'})
        if not _value_reference(index, node):
            continue
        label, binding, status, reason = identity(source, index, node)
        if status == 'invalid':
            return None, 'invalid_source_reference:' + str(reason)
        port = tuple(sorted({(p['helper_id'], p['parameter']) for p in ports if _contains(p['actual']['span'], node)}))
        row = {'path': paths[(node.start_byte, node.end_byte)], 'span': _span(source, node),
               'name': source.text(node), 'binding': label, 'status': status, 'reason': reason,
               'port': port, 'declaration': declaration(source, binding)}
        references.append(row)
        if status != 'available':
            unknowns.append({'span': row['span'], 'reason': reason})
    return {'references': references, 'calls': calls, 'unknowns': unknowns,
            'unproved': ['value_equivalence', 'effects', 'aliasing', 'dynamic_rebinding', 'oracle_validity']}, None


def corresponding(records):
    """Propose variable-port correspondences; preserve actual origin identities.

    Distinct bindings may correspond even when spelled alike. This explicitly
    substitutes A's binding by C's; it does not assert equal values. B must
    refer to the exact A binding, rather than an unrelated same-named local.
    """
    A, B, C = records
    a_by_path = {tuple(r['path']): r for r in A['environment']['references']}
    c_by_path = {tuple(r['path']): r for r in C['environment']['references']}
    pairs, lookup = {}, {}
    for path, a in a_by_path.items():
        c = c_by_path.get(path)
        if not c or a['binding'] == c['binding'] or not a['port'] or a['port'] != c['port']:
            continue
        if any(r['binding'][0] != 'lexical_binding' or r['binding'][2] not in _VARIABLES for r in (a, c)):
            continue
        label = ('binding_correspondence', a['binding'], c['binding'], a['port'])
        for side, row in [('A', a), ('C', c)]:
            key = (side, row['binding'], row['port'])
            if key in lookup and lookup[key] != label:
                return None, None, 'ambiguous_binding_correspondence'
            lookup[key] = label
        pairs[label] = {'A': a, 'C': c, 'same_spelling': a['name'] == c['name'],
                        'claim': 'syntactic_port_correspondence_not_value_equivalence'}
    result = []
    for side, record in zip('ABC', records):
        labels = dict(record['bindings'])
        for row in record['environment']['references']:
            key = ('A' if side == 'B' else side, row['binding'], row['port'])
            labels[tuple(row['path'])] = lookup.get(key, row['binding'])
        result.append(dict(record, bindings=labels))
    return result, pairs, None


def check_output(corpus, C, output, output_roles, pairs):
    """Require each output reference to resolve to its transported origin."""
    from generic_composition.terms import render
    text = render(output)
    path, lo, hi = C['span']['path'], C['span']['start_byte'], C['span']['end_byte']
    original = corpus['sources'][path]['code'].encode()
    encoded = text.encode()
    source = Source(path, (original[:lo] + encoded + original[hi:]).decode(), corpus['language'])
    if source.root.has_error:
        return {'status': 'invalid', 'reason': 'edited_source_parse_error'}
    delta = len(encoded) - (hi - lo)
    unshift = lambda offset: offset - delta if offset >= lo + len(encoded) else offset
    index, labels_by_span = _Index(source), {}

    def position(node, path=(), start=lo):
        end = start
        if node.children:
            for i, nested in enumerate(node.children):
                end = position(nested, path + (i,), end)
        elif node.atom is not None:
            end += len(str(node.atom).encode())
        if path in output_roles and node.kind in {'identifier', 'shorthand_property_identifier'}:
            labels_by_span[(start, end)] = output_roles[path]
        return end

    position(output)
    checked, unknowns = [], []
    for node in walk(source.root):
        if not (lo <= node.start_byte < node.end_byte <= lo + len(encoded)) or not _value_reference(index, node):
            continue
        origin = labels_by_span.get((node.start_byte, node.end_byte))
        if origin is None:
            return {'status': 'invalid', 'reason': 'untracked_output_reference', 'name': source.text(node)}
        if origin[0] == 'binding_correspondence':
            # An explicit environment substitution also works when spelling
            # stays unchanged. Requiring C's actual identity prevents capture.
            origin = pairs[origin]['C']['binding']
        actual, binding, status, reason = identity(source, index, node, undo_shift=unshift)
        if actual != origin or status == 'invalid':
            return {'status': 'invalid', 'reason': 'binding_capture_or_missing_reference', 'name': source.text(node),
                    'expected_binding': origin, 'actual_binding': actual}
        checked.append({'name': source.text(node), 'relative_span': [node.start_byte - lo, node.end_byte - lo],
                        'binding': actual, 'status': status})
        if status != 'available':
            unknowns.append({'name': source.text(node), 'reason': reason})
    return {'status': 'unknown' if unknowns else 'compatible', 'references': checked, 'unknowns': unknowns,
            'unproved': ['value_equivalence', 'effects', 'dynamic_rebinding', 'oracle_validity']}
