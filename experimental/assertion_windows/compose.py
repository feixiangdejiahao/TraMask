"""Compose contiguous observation windows with the unchanged v3 ABC kernel."""
from anchor_retrieval.syntax import Source, walk
from experimental.assertion_instances.core import _id, _span
from experimental.assertion_instances_v2.environment import declaration, identity
from experimental.generic_v2.bindings import _Index, _value_reference, analyze_bindings
from experimental.generic_v2.generate import _refine, _roles
from experimental.generic_v3.alignment import _parts, align_analogy
from generic_composition.corpus import source_text
from generic_composition.terms import BudgetExceeded, SourceTerm, render, subterms


def _external_identity(source, index, node, undo=lambda n: n):
    label, binding, status, reason = identity(source, index, node, undo_shift=undo)
    if binding is None and reason == 'external_or_unresolved_binding':
        # No lexical declaration was found in any enclosing scope. Preserve
        # this unresolved global namespace, and retain status='unknown'.
        label = ('unresolved_global', source.path, source.text(node))
    return label, binding, status, reason


def prepare_environment(corpus, record, cache):
    """Classify internal binders versus the window's external interface."""
    path, lo, hi = record['span']['path'], record['span']['start_byte'], record['span']['end_byte']
    if path not in cache:
        source = Source(path, corpus['sources'][path]['code'], corpus['language'])
        cache[path] = source, _Index(source)
    source, index = cache[path]
    terms = dict(subterms(record['tree'].term))
    paths = {(span.start_byte, span.end_byte): p for p, span in record['tree'].spans.items()
             if terms[p].kind in {'identifier', 'shorthand_property_identifier'}}
    labels, literal_roles, external = dict(record['bindings']), dict(record['literal_roles']), []
    for node in walk(source.root):
        if not (lo <= node.start_byte < node.end_byte <= hi) or not _value_reference(index, node):
            continue
        label, binding, status, reason = _external_identity(source, index, node)
        p = paths[(node.start_byte, node.end_byte)]
        literal_roles.pop(p, None)
        if binding and lo <= binding.node.start_byte < hi:
            continue  # Existing window-local alpha roles belong to the kernel.
        role = ('parameter', record['test']['parameters'].index(source.text(node))) if (
            binding and binding.kind == 'parameter' and source.text(node) in record['test']['parameters']) else ('window_external', label)
        labels[p] = role
        external.append({'name': source.text(node), 'span': _span(source, node), 'binding': label,
                         'role': role, 'status': status, 'reason': reason, 'declaration': declaration(source, binding)})
    return dict(record, bindings=labels, literal_roles=literal_roles, external_environment=external)


def _check_references(corpus, C, output, roles):
    text = render(output)
    path, lo, hi = C['span']['path'], C['span']['start_byte'], C['span']['end_byte']
    raw, replacement = corpus['sources'][path]['code'].encode(), text.encode()
    source = Source(path, (raw[:lo] + replacement + raw[hi:]).decode(), corpus['language'])
    if source.root.has_error:
        return {'status': 'invalid', 'reason': 'edited_source_parse_error'}
    index, by_span = _Index(source), {}
    delta = len(replacement) - (hi - lo)
    undo = lambda offset: offset - delta if offset >= lo + len(replacement) else offset

    def spans(node, path=(), start=lo):
        end = start
        for i, nested in enumerate(node.children):
            end = spans(nested, path + (i,), end)
        if not node.children and node.atom is not None:
            end += len(str(node.atom).encode())
        if path in roles and node.kind in {'identifier', 'shorthand_property_identifier'}:
            by_span[(start, end)] = roles[path]
        return end

    spans(output)
    checked, unknowns = [], []
    for node in walk(source.root):
        if not (lo <= node.start_byte < node.end_byte <= lo + len(replacement)) or not _value_reference(index, node):
            continue
        role = by_span.get((node.start_byte, node.end_byte))
        actual, binding, status, reason = _external_identity(source, index, node, undo)
        valid = role is not None and status != 'invalid'
        if valid and role[0] == 'window_external':
            valid = actual == role[1]
        elif valid and role[0] == 'parameter':
            valid = bool(binding and binding.kind == 'parameter' and
                         binding.node.start_byte < lo and
                         source.text(node) == C['test']['parameters'][role[1]])
        elif valid and role[0] in {'single_scope_local', 'aligned_local', 'unaligned_local'}:
            valid = bool(binding and lo <= binding.node.start_byte < lo + len(replacement))
        else:
            valid = False
        if not valid:
            return {'status': 'invalid', 'reason': 'window_reference_capture_or_missing_binding',
                    'name': source.text(node), 'role': role, 'actual_binding': actual}
        checked.append({'name': source.text(node), 'role': role, 'binding': actual, 'status': status})
        if status != 'available':
            unknowns.append({'name': source.text(node), 'reason': reason})
    return {'status': 'unknown' if unknowns else 'compatible', 'references': checked, 'unknowns': unknowns,
            'unproved': ['state_equivalence', 'aliasing', 'liveout_effects', 'oracle_validity']}


def _check_protected_gaps(C, result):
    """Check exact C gap units even when they are common alignment anchors."""
    origin = _parts(C['tree'])
    output = _parts(SourceTerm(result.output, {}))
    crows = result.provenance['source_occurrences']['C']
    edits = [row for row in result.provenance['source_occurrences']['B'] if row['role'] == 'edit']
    residuals = [row for row in crows if row['role'] == 'residual']

    def unit(parts, index):
        return ''.join(render(parts['items'][i][1]) for i in parts['units'][index])

    checked = []
    for index in C['protected_gap_indices']:
        row = next(r for r in crows if r['statement'] == index)
        if row['role'] == 'anchor':
            anchor = row['anchor']
            position = anchor + sum(r['gap'] <= anchor for r in residuals + edits)
        else:
            gap = row['gap']
            position = gap + sum(r['gap'] < gap for r in residuals + edits)
            position += [r['statement'] for r in residuals if r['gap'] == gap].index(index)
        if position >= len(output['units']) or unit(origin, index) != unit(output, position):
            return None
        checked.append({'source_statement': index, 'output_statement': position, 'alignment_role': row['role']})
    if [r['output_statement'] for r in checked] != sorted({r['output_statement'] for r in checked}):
        return None
    return checked


def compose(corpus, A, B, C, *, max_nodes=1500, max_holes=32, refine=_refine,
            mechanical_cache=None, source_cache=None):
    if len({r['instance_id'] for r in (A, B, C)}) != 3:
        return {'status': 'unsupported', 'reason': 'three_distinct_windows_required'}
    try:
        records = [refine(r, max_nodes) for r in (A, B, C)]
        result = align_analogy(*(r['tree'] for r in records), roles=_roles(*records),
                               max_nodes=max_nodes, max_holes=max_holes)
    except BudgetExceeded:
        return {'status': 'unsupported', 'reason': 'window_node_budget'}
    if result.status != 'hypothesis':
        return {'status': 'unsupported', 'reason': result.reason}
    protected_gaps = _check_protected_gaps(records[2], result)
    if protected_gaps is None:
        return {'status': 'unsupported', 'reason': 'protected_C_gap_changed_or_reordered'}
    lexical = _check_references(corpus, C, result.output, result.output_roles)
    if lexical['status'] == 'invalid':
        return {'status': 'unsupported', 'reason': lexical['reason'], 'lexical_check': lexical}
    after = render(result.output)
    mechanical_cache = {} if mechanical_cache is None else mechanical_cache
    source_cache = {} if source_cache is None else source_cache
    path = C['span']['path']
    if path not in source_cache:
        source_cache[path] = Source(path, corpus['sources'][path]['code'], corpus['language'])
    key = (C['parent_test_id'], C['span']['start_byte'], C['span']['end_byte'], after)
    if key not in mechanical_cache:
        mechanical_cache[key] = analyze_bindings(source_cache[path], corpus['language'], C['span']['start_byte'], after,
                                                end_byte=C['span']['end_byte'])
    mechanical = mechanical_cache[key]
    if mechanical['status'] == 'invalid':
        return {'status': 'unsupported', 'reason': 'mechanically_invalid_window', 'binding_analysis': mechanical}
    rid = _id('assertion_window_analogy', [r['instance_id'] for r in (A, B, C)])
    sources = {name: {'test_id': r['parent_test_id'], 'instance_id': r['instance_id'], 'span': r['span'], 'text': r['text'],
                      'required_statement_indices': r['required_statement_indices'], 'protected_gap_indices': r['protected_gap_indices']}
               for name, r in zip('ABC', (A, B, C))}
    candidate = {'id': _id(rid, after), 'base_test_id': C['parent_test_id'],
                 'source_test_ids': list(dict.fromkeys(r['parent_test_id'] for r in (A, B))),
                 'language': corpus['language'], 'kind': 'assertion_window_analogy', 'rule_id': rid, 'imports': [],
                 'edits': [{'span': C['span'], 'before': source_text(corpus, C['span']), 'after': after}],
                 'oracle': {'mode': 'transport_from_source', 'source_test_id': B['parent_test_id'],
                            'binding_source_test_id': C['parent_test_id'], 'assertion_ids': B['capsule_ids'],
                            'semantic_status': 'requires_admission'},
                 'provenance': dict(result.provenance, sources=sources, binding_analysis=mechanical,
                                    lexical_check=lexical, C_protected_gaps_preserved_exactly_once_in_order=True,
                                    protected_gap_witnesses=protected_gaps,
                                    source_environments={name: r['external_environment'] for name, r in zip('ABC', (A, B, C))})}
    rule = {'id': rid, 'kind': candidate['kind'], 'before_span': A['span'], 'after_span': B['span'],
            'semantic_status': 'hypothesis_from_test_edit'}
    return {'status': 'hypothesis', 'candidate': candidate, 'rule': rule}
