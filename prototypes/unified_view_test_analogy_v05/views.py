"""Try raw and aligned views within one triple, without learning new oracles."""
from dataclasses import replace

from prototypes.test_edit_analogy_allow_erasing_v02_01.analogy import analogy
from prototypes.test_edit_analogy_v02.generate import _callee
from prototypes.statement_aligned_test_analogy_v03.alignment import AlignmentResult, _key, _parts, align_analogy


def _frontier(capsule):
    """First actual-value calls and field projections; never expected values."""
    facts = capsule['bindings']
    nodes = {n['id']: n for n in facts['slice_nodes']}
    edges = {}
    for edge in facts['slice_edges']:
        if edge['kind'] == 'value':
            edges.setdefault(edge['from'], []).append(edge['to'])
    actuals = [capsule['observed']['span']] if capsule.get('observed') else []
    origins = [b['actual']['span'] for h in capsule.get('helper_assertions', [])
               for b in h.get('observed_parameter_origins', [])]
    if origins:
        actuals = origins
    spans = {(s['start_byte'], s['end_byte']) for s in actuals}
    pending = [(n['id'], ()) for n in nodes.values()
               if (n['start_byte'], n['end_byte']) in spans
               and n['kind'] not in {'assertion', 'unknown', 'join', 'parameter', 'receiver', 'may_effect'}]
    calls = {(c['span']['start_byte'], c['span']['end_byte']): c for c in capsule['calls']}
    seen, result = set(), set()
    while pending:
        nid, projection = pending.pop()
        if (nid, projection) in seen:
            continue
        seen.add((nid, projection))
        if len(seen) > 8192:
            return None
        node = nodes[nid]
        if node['kind'] == 'field_read':
            projection += (('field', node.get('field', '')),)
        elif node['kind'] in {'index_expression', 'subscript_expression', 'subscript'}:
            projection += (('index', node['kind']),)
        if node['kind'] == 'call':
            call = calls.get((node['start_byte'], node['end_byte']))
            if call is not None:
                result.add((_callee(call), projection))
            continue
        pending.extend((other, projection) for other in edges.get(nid, ()) if other in nodes)
    return tuple(sorted(result, key=repr)) or None


def observer_keys(record, capsules):
    """Refine only capsule-bearing statements, retaining other source shapes."""
    tree = record['tree']
    parts = _parts(tree)
    keys, evidence = [], []
    for unit, statement in zip(parts['units'], parts['statements']):
        path, _ = parts['items'][unit[0]]
        position = tree.spans[path]
        observations = []
        for capsule in capsules:
            span = capsule['assertion_span']
            if position.start_byte <= span['start_byte'] and span['end_byte'] <= position.end_byte:
                frontier = _frontier(capsule)
                if frontier:
                    observations.append((capsule['predicate'], frontier))
                    evidence.append({'assertion_span': span, 'actual_frontier': frontier})
        if observations:
            keys.append(('actual_observer', _key(statement)[0], tuple(sorted(observations, key=repr))))
        else:
            keys.append(('statement_shape', _key(statement)))
    return keys, evidence


def _raw(A, B, C, options):
    result = analogy(A['tree'].term, B['tree'].term, C['tree'].term, **options)
    compact = {k: v for k, v in result.provenance.items()
               if k not in {'source_substitutions', 'target_substitutions'}}
    witness = {'checks': compact.get('checks', {}), 'alignment': {}, 'gap_order': 'raw',
               'has_shared_gap': False, 'view': 'raw',
               'kernel': 'test_edit_analogy_v2_1_allow_erasing_rhs', 'analogy': compact,
               'unproved': ['syntax_validity', 'context_admissibility', 'bindings_and_capture', 'effects', 'oracle_validity']}
    return AlignmentResult(result.status, result.output, witness, result.reason)


def compose_views(A, B, C, *, capsules, roles=None, max_nodes=1500, max_holes=32):
    """Return raw plus preferred aligned candidates; one driver triple budget.

    Precise observation labels are an alignment preference. If their embedding
    or analogy is unsupported, the unchanged shape/call-head alignment is tried.
    Neither label matching nor raw erasure proves a semantic precondition.
    """
    options = dict(roles=roles, max_nodes=max_nodes, max_holes=max_holes)
    raw = _raw(A, B, C, options)
    records = (A, B, C)
    extracted = [observer_keys(record, facts) for record, facts in zip(records, capsules)]
    evidence = dict(zip('ABC', [item[1] for item in extracted]))
    keys = [item[0] for item in extracted]
    first = align_analogy(*(r['tree'] for r in records), anchor_keys=keys, **options)
    preferred = {'status': first.status, 'reason': first.reason}
    fallback = first.status != 'hypothesis'
    if fallback:
        first = align_analogy(*(r['tree'] for r in records), **options)
    aligned = [first]
    if first.provenance.get('has_shared_gap'):
        aligned.append(align_analogy(*(r['tree'] for r in records),
                                    anchor_keys=None if fallback else keys, order='edit_first', **options))
    results = [raw]
    seen = {raw.output} if raw.status == 'hypothesis' else set()
    for result in aligned:
        witness = dict(result.provenance, view='aligned_fallback' if fallback else 'aligned_observer',
                       preferred_observer_attempt=preferred, observer_evidence=evidence,
                       observer_precision='first_actual_value_calls_and_field_names; index_values_and_effects_unknown')
        # Deduplication also occurs in the shared driver; do it here so one
        # program reached by both views does not consume a second output slot.
        if result.status == 'hypothesis' and result.output in seen:
            continue
        if result.status == 'hypothesis':
            seen.add(result.output)
        results.append(replace(result, provenance=witness))
    return results
