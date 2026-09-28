"""Prioritize source observations with a resolved path to changed code.

This is a ranking signal, not a relevance filter or a coverage proof. Unresolved
calls stay eligible. Only resolved call edges enter the shortest-path graph;
unique-name guesses do not become data-dependence evidence.
"""
from collections import defaultdict, deque


def rank_seeds(frontend, changed_lines, prior_ranks):
    functions = {f['id']: f for f in frontend.get('functions', ()) if f.get('production')}
    changed = set()
    for identifier, function in functions.items():
        span = function['span']
        if any(span['line'] <= line <= span['end_line']
               for line in changed_lines.get(span['path'], ())):
            changed.add(identifier)
    reverse = defaultdict(set)
    for call in frontend.get('production_calls', ()):
        caller = call.get('function_id')
        if caller not in functions:
            continue
        for target in call.get('targets', ()):
            if target.get('resolved') is True and target['function_id'] in functions:
                reverse[target['function_id']].add(caller)
    distances = {identifier: 0 for identifier in changed}
    queue = deque(sorted(changed))
    while queue:
        target = queue.popleft()
        for caller in sorted(reverse[target]):
            if caller not in distances:
                distances[caller] = distances[target] + 1
                queue.append(caller)
    by_test = defaultdict(list)
    for call in frontend.get('calls', ()):
        by_test[call['test_id']].append(call)
    q_calls = defaultdict(set)
    for observation in frontend.get('observations', ()):
        if observation.get('kind') == 'assertion':
            q_calls[observation['test_id']].update(observation.get('source_call_ids', ()))
    records = []
    for test in frontend.get('tests', ()):
        identifier = test['id']
        hits = []
        for call in by_test[identifier]:
            if call.get('role') != 'operation':
                continue
            for target in call.get('targets', ()):
                function_id = target['function_id']
                if target.get('resolved') is True and function_id in distances:
                    hits.append({'call_id': call['id'], 'function_id': function_id,
                                 'distance': distances[function_id],
                                 'feeds_observation': call['id'] in q_calls[identifier]})
        observed = [hit for hit in hits if hit['feeds_observation']]
        preferred = observed or hits
        distance = min((hit['distance'] for hit in preferred), default=None)
        records.append({'test_id': identifier, 'prior_rank': prior_ranks.get(identifier),
                        'relation': 'observed_changed_call' if observed else 'changed_call' if hits else 'unresolved_or_no_path',
                        'distance': distance, 'witnesses': sorted(hits, key=lambda x: (not x['feeds_observation'], x['distance'], x['call_id']))})
    order = {'observed_changed_call': 0, 'changed_call': 1, 'unresolved_or_no_path': 2}
    records.sort(key=lambda r: (order[r['relation']], r['distance'] if r['distance'] is not None else float('inf'),
                                r['prior_rank'] or float('inf'), r['test_id']))
    ranks = {row['test_id']: index + 1 for index, row in enumerate(records)}
    return {'ranks': ranks, 'records': records, 'changed_function_ids': sorted(changed),
            'status': 'ranking_only_unresolved_tests_retained', 'resolved_functions_reaching_change': len(distances)}
