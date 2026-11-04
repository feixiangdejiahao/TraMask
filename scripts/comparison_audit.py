"""Pilot-only baseline domains and counts; the current algorithm lives in eviweave."""
from collections import defaultdict

from eviweave.behavior_clusters import BehaviorClusterIndex,cluster_queries
from eviweave.behavior_deltas import BehaviorDeltaIndex
from eviweave.comparison import PARTITIONS
from eviweave.port_admission import admission_witnesses
from eviweave.relational_alignment import RelationalAlignmentIndex,view_pair_masks


def partition_records(index, records, views, field_names=(), *, modes=PARTITIONS):
    """Partition both admitted and original alignment domains without labels."""
    cluster = BehaviorClusterIndex(index, field_names)
    groups, ids, buckets = [], {}, defaultdict(set)
    clusters = {mode: {} for mode in modes}
    occurrences = {mode: defaultdict(set) for mode in modes}
    facts = {mode: defaultdict(set) for mode in modes}
    at = {mode: {} for mode in modes}
    for record in records:
        witnesses = admission_witnesses(record, 'two_edge')
        record_ids = {}
        for mode in modes:
            code = cluster.signature(record, mode)
            identity = clusters[mode].setdefault(code, len(clusters[mode]))
            record_ids[mode] = identity
            at[mode][record['view'], record['key']] = identity
            occurrences[mode][identity].add((record['view'], *record['key']))
            facts[mode][identity].update(cluster.facts(record))
        if not witnesses:
            continue
        signature = record['interface'], record['exact'], tuple(sorted(witnesses, key=repr))
        if signature not in ids:
            identity = len(groups)
            ids[signature] = identity
            groups.append({'record': record, 'members': set(), 'anchors': set(),
                           'parts': {mode: defaultdict(lambda: {'members': set(), 'anchors': set()}) for mode in modes}})
            for witness in witnesses:
                buckets[witness].add(identity)
        group = groups[ids[signature]]
        group['members'].add(record['view'])
        if record['anchor']:
            group['anchors'].add(record['view'])
        for mode in modes:
            part = group['parts'][mode][record_ids[mode]]
            part['members'].add(record['view'])
            if record['anchor']:
                part['anchors'].add(record['view'])
    edges = {mode: set() for mode in modes}
    raw_masks = defaultdict(int)
    baseline = 0
    subpairs = {mode: 0 for mode in modes}
    within = {mode: 0 for mode in modes}
    for g, group in enumerate(groups):
        if not group['anchors']:
            continue
        donor_ids = set().union(*(buckets[w] for w in admission_witnesses(group['record'], 'two_edge'))) - {g}
        for h in sorted(donor_ids):
            other = groups[h]
            if not any(other['members'] - {view} for view in group['anchors']):
                continue
            baseline += 1
            for view in group['anchors']:
                raw_masks[view] |= sum(1 << w for w in other['members'] - {view})
            for mode in modes:
                for left, a in group['parts'][mode].items():
                    if not a['anchors']:
                        continue
                    for right, b in other['parts'][mode].items():
                        if any(b['members'] - {view} for view in a['anchors']):
                            edges[mode].add((left, right))
                            subpairs[mode] += 1
                            within[mode] += left == right
    requests = {}
    for mode in modes:
        neighbors = defaultdict(set)
        for left, right in edges[mode]:
            neighbors[left].add(right)
        requests[mode] = sum(len(set().union(*(facts[mode][right] for right in right_ids)))
                             for right_ids in neighbors.values())
    selected = defaultdict(set)
    for view in views:
        selected[view['source']].update(view['nodes'])
    original = RelationalAlignmentIndex(index.sources, selected)
    old_groups, old_domains = original.grouped_view_domains(views)
    old_masks, _ = view_pair_masks(old_groups, old_domains)
    operation_sources = {operation: source for source, operation in index.operations}
    full_edges = {mode: set() for mode in modes}
    for mode in modes:
        parts = []
        for group in old_groups:
            member, anchor = defaultdict(set), defaultdict(set)
            for view, operation in group['members']:
                key = operation_sources[operation], operation
                key = index.aliases.get(key, key)
                member[at[mode][view, key]].add(view)
            for view, operation in group['anchors']:
                key = operation_sources[operation], operation
                key = index.aliases.get(key, key)
                anchor[at[mode][view, key]].add(view)
            parts.append((member, anchor))
        for domain in old_domains:
            for g in domain['anchor_groups']:
                for h in domain['groups']:
                    if g == h:
                        continue
                    for left, aa in parts[g][1].items():
                        for right, bb in parts[h][0].items():
                            if any(bb - {view} for view in aa):
                                full_edges[mode].add((left, right))
    lifted = {mode: full_edges[mode] | cluster_queries(index, records, {
        (view, *key): identity for (view, key), identity in at[mode].items()}) for mode in modes}
    metrics = {'fixed_slice_pairs': sum(mask.bit_count() for mask in raw_masks.values()),
               'old_profile_pairs': baseline,
               'original_slice_pairs': sum(mask.bit_count() for mask in old_masks.values()),
               'arms': {mode: {'clusters': len(clusters[mode]), 'cluster_pairs': len(edges[mode]),
                               'full_domain_cluster_pairs': len(full_edges[mode]),
                               'lifted_cluster_pairs': len(lifted[mode]), 'relational_requests': requests[mode],
                               'mapped_old_subpairs': subpairs[mode], 'same_cluster_old_subpairs': within[mode]}
                        for mode in modes}}
    return {'metrics': metrics, 'memberships': occurrences,
            'cluster_pairs': {'admitted': edges, 'original': full_edges, 'lifted': lifted},
            'admitted_view_pairs': raw_masks, 'original_view_pairs': old_masks}


def difference_domains(index, records):
    """Share role-local edit bundles over a fixed two-relation admission domain."""
    deltas = BehaviorDeltaIndex(index)
    # Keep each admitted profile's entire view and occurrence domain. This is
    # the previous admission grouping, not another rejection criterion.
    groups, ids, buckets = [], {}, defaultdict(set)
    for r in records:
        witnesses = admission_witnesses(r, 'two_edge')
        if not witnesses:
            continue
        signature = r['interface'], r['exact'], tuple(sorted(witnesses, key=repr))
        if signature not in ids:
            identity = len(groups); ids[signature] = identity
            groups.append({'record':r,'members':set(),'anchors':set()})
            for w in witnesses:
                buckets[w].add(identity)
        g = ids[signature]
        groups[g]['members'].add(r['view'])
        if r['anchor']:
            groups[g]['anchors'].add(r['view'])
    # Baseline and new schemes see identical old-profile pairs. No round of
    # admission or role matching is added inside the following comparison.
    raw_masks = defaultdict(int)
    operation_profile_pairs = concrete_plans = schema_plans = 0
    empty_local = payload_only = 0
    max_schemas = 0
    examples = []
    for g, group in enumerate(groups):
        if not group['anchors']:
            continue
        left = group['record']
        donor_ids = set().union(*(buckets[w] for w in admission_witnesses(left, 'two_edge'))) - {g}
        exact_classes, schema_classes = set(), set()
        for h in sorted(donor_ids):
            other = groups[h]
            # The old domain permits only distinct views; same-view local
            # transformations are a separate search channel.
            if not any(other['members'] - {v} for v in group['anchors']):
                continue
            for v in group['anchors']:
                raw_masks[v] |= sum(1 << w for w in other['members'] - {v})
            operation_profile_pairs += 1
            right = other['record']
            result = deltas.difference(left, right)
            if not result['addresses']:
                empty_local += 1
                # Unmodelled old context is retained as an explicit domain,
                # rather than erased by a coarser local representation.
                residual = ('unmodelled_context', left['exact'], right['exact'])
                exact_classes.add(residual); schema_classes.add(residual)
            else:
                exact_classes.add(result['exact']); schema_classes.add(result['schema'])
                payload_only += result['parameter_only']
                if len(examples) < 10:
                    examples.append({'left':left['key'],'right':right['key'],**result})
        concrete_plans += len(exact_classes); schema_plans += len(schema_classes)
        max_schemas = max(max_schemas, len(schema_classes))
    return {'metrics': {
        'old_operation_profile_pairs':operation_profile_pairs,
        'concrete_local_difference_domains':concrete_plans,
        'parameterised_difference_domains':schema_plans,
        'unchanged_local_relation_pairs_retained_as_residual':empty_local,
        'parameter_only_pairs':payload_only,'max_schemas_per_recipient_profile':max_schemas},
        'view_pairs':raw_masks,'examples':examples}
