"""Exchange source expressions that occupy a common resolved argument port.

Different constructors may implement the same argument contract. Requiring
identical producer names would miss those crossings. This module retains the
callee/position constraint and lexical closure; it does not infer that either
the old observation or expected value remains valid after an exchange.
"""
from collections import Counter, defaultdict, deque

from generic_composition import engine


def _subject_port(corpus, donor, port):
    for capsule in corpus['capsules']:
        if capsule['test_id'] != donor['test_id']:
            continue
        if engine.contained(port['call_span'], capsule['assertion_span']):
            observed = capsule.get('observed')
            if not observed or not engine.contained(port['call_span'], observed['span']):
                return False
    return True


def generate(corpus, *, top_k=10, max_candidates=128, max_attempts=4000):
    tests, skipped, groups = corpus['tests'], Counter(), defaultdict(list)
    ranked = sorted(tests.values(), key=lambda t: (t.get('retrieval_rank') or 99999, t['id']))
    seeds = {t['id'] for t in ranked if t.get('retrieval_rank') and t['retrieval_rank'] <= top_k}
    if not seeds:
        seeds = {t['id'] for t in ranked[:top_k]}
    for donor in engine.expanded_donors(corpus):
        if (donor['kind'] not in {'call', 'call_expression', 'new_expression', 'list', 'array', 'object', 'dictionary'}
                or donor.get('role') == 'expected' or engine.expected_only(donor)
                or engine._assertion_intersects(corpus, donor)):
            continue
        parent = tests[donor['test_id']]
        source = corpus['sources'][parent['span']['path']]
        if not source.get('complete_file', True) or source.get('parse_error') or len(donor['text'].encode()) > 1800:
            continue
        for port in engine.input_ports(donor):
            identity = port.get('callee_identity') or {}
            if not identity.get('canonical'):
                skipped['unresolved_call_port'] += 1
                continue
            if not _subject_port(corpus, donor, port):
                continue
            # Dependencies reaching a call through another expression are not
            # all interchangeable values at that port. Require the actual arg.
            if donor['span']['start_byte'] != port['argument_span']['start_byte'] or donor['span']['end_byte'] != port['argument_span']['end_byte']:
                continue
            groups[engine.slot_key(port)].append(donor)
    plans = defaultdict(list)
    for port, members in sorted(groups.items(), key=lambda item: repr(item[0])):
        if not any(d['test_id'] in seeds for d in members):
            continue
        unique = {}
        for d in sorted(members, key=lambda d: (d['test_id'] not in seeds, d['retrieval_rank'] or 99999, d['id'])):
            unique.setdefault((d['test_id'], d['text']), d)
        values = list(unique.values())[:96]
        for target in values:
            for origin in values:
                if (target['text'] == origin['text'] or target['test_id'] == origin['test_id']
                        or not {target['test_id'], origin['test_id']} & seeds):
                    continue
                plans[target['test_id']].append((port, target, origin))
    ordered = sorted(plans, key=lambda tid: (tests[tid].get('retrieval_rank') or 99999, tid))
    queues = {tid: deque(sorted(rows, key=lambda row: (len(row[2]['text']), row[1]['id'], row[2]['id'])))
              for tid, rows in plans.items()}
    candidates, seen, attempts = [], set(), 0
    while queues and len(candidates) < max_candidates and attempts < max_attempts:
        for tid in ordered:
            if tid not in queues:
                continue
            port, target, origin = queues[tid].popleft()
            if not queues[tid]:
                del queues[tid]
            attempts += 1
            names = set(origin.get('free_identifiers', [])) - set(origin.get('bound_identifiers', []))
            source_test = tests[origin['test_id']]
            source_imports = {row['name'] for row in source_test.get('support', {}).get('imports', [])}
            if names & (set(source_test.get('scope_bindings', [])) - source_imports):
                skipped['source_local_requires_dependency_slice'] += 1
                continue
            imports, unknown = engine._imports_for(corpus, origin, target, names)
            if unknown:
                skipped['source_expression_not_closed'] += 1
                continue
            mutation = {'span': target['span'], 'before': target['text'], 'after': origin['text']}
            cid = engine.stable_id('argument_port_exchange', tid, mutation, imports)
            if cid not in seen:
                seen.add(cid)
                candidates.append({'id': cid, 'base_test_id': tid, 'source_test_ids': [origin['test_id']],
                    'language': corpus['language'], 'kind': 'argument_port_exchange',
                    'rule_id': engine.stable_id('argument_port', port), 'edits': [mutation], 'imports': imports,
                    'provenance': {'target_donor_id': target['id'], 'source_donor_ids': [origin['id']],
                                   'argument_port': port, 'semantic_status': 'resolved_argument_port; generic_type_and_oracle_unproved'}})
            if len(candidates) >= max_candidates or attempts >= max_attempts:
                break
    return {'candidates': candidates, 'skipped': dict(skipped), 'attempts': attempts,
            'budget_exhausted': bool(queues) and attempts >= max_attempts}
