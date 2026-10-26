"""Rank the two legs A->C and A->B using existing local dependence facts.

This is a search heuristic, not semantic admission. Every input neighbor remains
in the output, including unresolved callees, may-effects and unrelated edits.
"""
from collections import Counter, defaultdict

from generic_composition.terms import render, subterms
from prototypes.test_edit_analogy_v02.generate import _callee
from prototypes.unified_view_test_analogy_v05.views import _frontier


_RESOLVED = {'import_alias', 'local_symbol', 'package_symbol', 'import_symbol', 'fixture_binding'}
_LITERALS = {
    'integer': 'number', 'int_literal': 'number', 'float': 'number', 'float_literal': 'number',
    'number': 'number', 'string': 'string', 'interpreted_string_literal': 'string',
    'raw_string_literal': 'string', 'template_string': 'string', 'rune_literal': 'string',
    'true': 'boolean', 'false': 'boolean', 'none': 'null', 'nil': 'null', 'null': 'null',
}


def observation_keys(capsules):
    """Return weak and resolved nearest-call/field keys, excluding expecteds."""
    all_keys, resolved_keys = set(), set()
    for capsule in capsules:
        keys = _frontier(capsule) or ()
        identities = {(_callee(c), (c.get('callee_identity') or {}).get('resolution'))
                      for c in capsule['calls']}
        for key in keys:
            all_keys.add(key)
            if any(identity == key[0] and resolution in _RESOLVED for identity, resolution in identities):
                resolved_keys.add(key)
    return frozenset(all_keys), frozenset(resolved_keys)


def _dependence(capsules):
    nodes, edges, roots = {}, defaultdict(set), set()
    for capsule in capsules:
        graph = capsule['bindings']
        nodes.update((n['id'], n) for n in graph['slice_nodes'])
        for edge in graph['slice_edges']:
            edges[edge['from']].add((edge['to'], edge['kind']))
        actuals = [capsule['observed']['span']] if capsule.get('observed') else []
        origins = [b['actual']['span'] for h in capsule.get('helper_assertions', [])
                   for b in h.get('observed_parameter_origins', [])]
        positions = {(s['start_byte'], s['end_byte']) for s in (origins or actuals)}
        roots.update(n['id'] for n in graph['slice_nodes']
                     if (n['start_byte'], n['end_byte']) in positions
                     and n['kind'] not in {'assertion', 'unknown', 'join', 'parameter', 'receiver', 'may_effect'})

    def reachable(kinds):
        pending, seen = list(roots), set()
        while pending:
            nid = pending.pop()
            if nid in seen:
                continue
            seen.add(nid)
            pending.extend(other for other, kind in edges[nid] if kind in kinds)
        return seen

    value = reachable({'value'})
    may = reachable({'value', 'may_effect'})
    return nodes, value, may


def _shape(node):
    if node.kind in _LITERALS:
        return 'literal', _LITERALS[node.kind]
    if node.kind.endswith('identifier'):
        return node.kind, None
    return node.kind, node.atom, tuple(_shape(c) for c in node.children if c.kind != '#trivia')


def _binding_reads(record, path):
    return {label for position, label in record.get('bindings', {}).items()
            if position[:len(path)] == path and label and label[0] in {'single_scope_local', 'parameter'}}


def _features(record, capsules):
    tree = record['tree']
    nodes, value, may = _dependence(capsules)
    calls = {(c['span']['start_byte'], c['span']['end_byte']): c
             for capsule in capsules for c in capsule['calls']}
    graph_calls = {(n['start_byte'], n['end_byte']): nid for nid, n in nodes.items() if n['kind'] == 'call'}
    read_positions = {(nodes[n]['start_byte'], nodes[n]['end_byte']) for n in value if n in nodes
                      and nodes[n]['kind'] in {'read', 'global', 'parameter', 'receiver'}}
    observed_bindings = {label for path, label in record.get('bindings', {}).items()
                         if (tree.spans[path].start_byte, tree.spans[path].end_byte) in read_positions
                         and label and label[0] in {'single_scope_local', 'parameter'}}
    operations = []
    for path, node in subterms(tree.term):
        if node.kind not in {'call', 'call_expression'}:
            continue
        position = tree.spans[path]
        pair = position.start_byte, position.end_byte
        children = [c for c in node.children if c.kind != '#trivia']
        identity = _callee(calls[pair]) if pair in calls else 'unresolved:' + render(children[0])
        binding_related = bool(_binding_reads(record, path) & observed_bindings)
        shape = identity, tuple(_shape(c) for c in children[1:]), binding_related
        nid = graph_calls.get(pair)
        connection = 3 if nid in value else 2 if nid in may else 1 if binding_related else 0
        operations.append({'shape': shape, 'connection': connection,
                           'span': {'path': record['test']['span']['path'],
                                    'start_byte': pair[0], 'end_byte': pair[1]}})
    observations = Counter((capsule['predicate'], frontier)
                           for capsule in capsules if (frontier := _frontier(capsule)))
    return {'keys': observation_keys(capsules), 'operations': operations, 'observations': observations}


def target_priority(A, C):
    """2: resolved same observation; 1: spelling match; 0: unknown/mismatch."""
    if A['keys'][1] & C['keys'][1]:
        return 2
    return int(bool(A['keys'][0] & C['keys'][0]))


def edit_priority(A, B):
    """Return connection strength and compact, reproducible difference evidence."""
    old = Counter(operation['shape'] for operation in A['operations'])
    changes = []
    for operation in B['operations']:
        if old[operation['shape']]:
            old[operation['shape']] -= 1
        else:
            changes.append(dict(operation, side='B_added_or_changed'))
    for operation in A['operations']:
        if old[operation['shape']]:
            old[operation['shape']] -= 1
            changes.append(dict(operation, side='A_deleted_or_changed'))
    new_observations = sum((B['observations'] - A['observations']).values())
    connection = max([operation['connection'] for operation in changes] + [3 if new_observations else 0])
    return {'score': connection, 'kind': ('unrelated_or_unknown', 'shared_binding_unknown', 'may_effect', 'value')[connection],
            'new_observations': new_observations,
            'changed_calls': [{'span': operation['span'], 'connection': operation['connection'], 'side': operation['side']}
                              for operation in changes]}


def rank_neighbors(A, neighbors, *, capsules, phase, cache=None):
    """Stable optional ordering callback; no budget changes or filtering.

    ``capsules`` is the existing test-id -> capsule-list mapping. A per-generation
    cache may be supplied; instance IDs include parameter-row identity. Existing
    shape-distance order remains the tie-breaker. The caller retains its focus
    round-robin schedule and B-shape diversity schedule.
    """
    if phase not in {'target', 'edit'}:
        raise ValueError('phase must be target or edit')
    cache = {} if cache is None else cache

    def features(record):
        key = record['instance_id']
        if key not in cache:
            cache[key] = _features(record, capsules[record['test']['id']])
        return cache[key]

    source = features(A)
    decorated = []
    for index, record in enumerate(neighbors):
        other = features(record)
        if phase == 'target':
            key = -target_priority(source, other), index
        else:
            difference = edit_priority(source, other)
            key = -difference['score'], len(difference['changed_calls']) + difference['new_observations'], index
        decorated.append((key, record))
    return [record for _, record in sorted(decorated, key=lambda pair: pair[0])]
