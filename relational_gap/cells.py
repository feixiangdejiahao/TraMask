"""Observation-relative source cells and executable minimal input witnesses.

This is a bounded, syntactic abstraction. It deliberately does not call a
statically present assertion checked coverage. Bindings and call order are part
of the grouping key; runtime identity and feasibility remain obligations.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import copy

from anchor_retrieval.syntax import CALLS, Source, child, walk
from generic_composition.engine import expected_only, slot_key
from relational_gap.closure import ClosureBudget, canonical, identifier, missing_cells
from relational_gap.structured_ports import carrier_ports
from prototypes.test_action_and_oracle_transfer.oracle import parse_source_literal, Unknown


@dataclass(frozen=True)
class CellBudget:
    max_coordinates: int = 16
    max_cells_per_group: int = 256
    max_candidates: int = 128
    max_groups: int = 2048


def _pos(span):
    return span['path'], span['start_byte'], span['end_byte']


def _inside(inner, outer):
    return inner['path'] == outer['path'] and outer['start_byte'] <= inner['start_byte'] and inner['end_byte'] <= outer['end_byte']


def _nodes(source):
    return {(node.start_byte, node.end_byte): node for node in walk(source.root)}


def _fingerprint(node, source, locals_, *, erase_arguments=False):
    if node is None:
        return None
    if node.type == 'comment':
        return None
    if erase_arguments and node.type in {'argument_list', 'arguments'}:
        return ('inputs',)
    if not node.children:
        value = source.text(node)
        if node.type == 'identifier' and value in locals_:
            value = '$local' + str(locals_[value])
        return node.type, value
    return node.type, tuple(value for part in node.children
                            if (value := _fingerprint(part, source, locals_, erase_arguments=erase_arguments)) is not None)


def recover_rows(corpus, frontend, *, budget=CellBudget()):
    sources = {path: Source(path, value['code'], value['language'])
               for path, value in corpus['sources'].items()}
    maps, ports = {}, {}
    bindings = {row['id']: row for row in frontend.get('bindings', [])}
    calls = {item['id']: item for item in frontend['calls']}
    calls_by_test, bindings_by_test = defaultdict(list), defaultdict(list)
    for row in calls.values():
        calls_by_test[row['test_id']].append(row)
    for row in bindings.values():
        bindings_by_test[row['test_id']].append(row)
    observations = defaultdict(list)
    for item in frontend['observations']:
        if item['kind'] == 'assertion':
            observations[item['test_id']].append(item)
    donors_by_test = defaultdict(list)
    for item in corpus['donors']:
        if expected_only(item) or item.get('oracle_dependency') or item.get('free_identifiers'):
            continue
        if item.get('literal_known'):
            donors_by_test[item['test_id']].append(item)
    rows, details, groups = [], {}, defaultdict(list)
    for test_id, test in sorted(corpus['tests'].items(), key=lambda p: (p[1].get('retrieval_rank') or 10**9, p[0])):
        local_names = {name: n for n, name in enumerate(test.get('scope_bindings', []))}
        source = sources[test['span']['path']]
        local_frontend = {'calls': calls_by_test[test_id], 'bindings': bindings_by_test[test_id]}
        if source.path not in maps:
            maps[source.path] = _nodes(source)
        for obs in observations[test_id]:
            relevant = [calls[cid] for cid in obs['source_call_ids'] if cid in calls and calls[cid]['role'] == 'operation']
            # Calls inside the observed expression are relevant even when a
            # conservative def-use analysis stops at a callback boundary.
            relevant += [call for call in calls.values() if call['test_id'] == test_id and call['role'] == 'operation'
                         and _inside(call['span'], obs['observed']['span']) and call not in relevant]
            relevant.sort(key=lambda item: _pos(item['span']))
            roots, operations, coordinates, edits = {}, [], {}, {}
            for ordinal, call in enumerate(relevant):
                identity = call.get('callee_identity', {})
                receiver = call.get('receiver_binding') or {}
                binding = receiver.get('origin_binding_id') or receiver.get('binding_id')
                # Rebinding a local creates another root. Unknown identities
                # are not silently equated with known ones.
                root = roots.setdefault(binding, len(roots)) if binding else ('unknown' if call.get('receiver') else 'free')
                callee = identity.get('canonical') or identity.get('scope_key') or call['callee']
                operations.append([callee, root, [context.get('kind') for context in call.get('contexts', [])]])
                for argument in call['arguments']:
                    if argument.get('spread'):
                        continue
                    options = {}
                    for donor in donors_by_test[test_id]:
                        if donor['id'] not in ports:
                            ports[donor['id']] = carrier_ports(source, donor, local_frontend)
                        for port in ports[donor['id']]:
                            if _pos(port['call_span']) != _pos(call['span']) or port['argument_slot'] != argument['slot']:
                                continue
                            path = port.get('structural_path', [])
                            if not path and _pos(donor['span']) != _pos(argument['span']):
                                bound = argument.get('binding') or {}
                                origin = bindings.get(bound.get('origin_binding_id'))
                                value_span = (origin.get('value') or {}).get('span') if origin else None
                                if (not origin or bound.get('resolution') != 'local_value_binding' or origin.get('contexts')
                                        or not value_span or _pos(value_span) != _pos(donor['span'])):
                                    continue
                            key = canonical(path)
                            options.setdefault(key, {'path': path, 'donors': {}})['donors'][_pos(donor['span'])] = donor
                    # Prefer independent leaves over their enclosing record. A
                    # leaf's field/index path is part of its coordinate identity.
                    leaves = [row for row in options.values() if not any(
                        len(row['path']) < len(other['path']) and other['path'][:len(row['path'])] == row['path']
                        for other in options.values())]
                    for row in sorted(leaves, key=lambda item: canonical(item['path'])):
                        if len(row['donors']) != 1:
                            continue
                        donor = next(iter(row['donors'].values()))
                        axis = f'{ordinal}:{argument.get("keyword") or argument["slot"]}'
                        if row['path']:
                            axis += ':' + canonical(row['path'])
                        coordinates[axis] = donor['literal_value']
                        edits[axis] = donor
                        if len(coordinates) >= budget.max_coordinates:
                            break
                    if len(coordinates) >= budget.max_coordinates:
                        break
                if len(coordinates) >= budget.max_coordinates:
                    break
            span = obs['observed']['span']
            node = maps[source.path].get((span['start_byte'], span['end_byte']))
            q = _fingerprint(node, source, local_names, erase_arguments=True)
            if q is None or not coordinates:
                continue
            row = {'id': identifier(test_id, obs['id']), 'observation': q,
                   'carrier': operations, 'coordinates': coordinates,
                   'candidate_version': 'frozen_source_input', 'assertion_justified': False,
                   'executed_on_candidate': False}
            rows.append(row)
            details[row['id']] = {'test_id': test_id, 'observation_id': obs['id'],
                                  'edits': edits, 'retrieval_rank': test.get('retrieval_rank') or 10**9}
            groups[canonical([q, operations])].append(row)
    return rows, details, groups


def generate_cells(corpus, frontend, *, budget=CellBudget()):
    rows, details, groups = recover_rows(corpus, frontend, budget=budget)
    queues, stats = [], {'rows': len(rows), 'groups': len(groups), 'enumerated_cells': 0, 'unseen_cells': 0}
    ordered = sorted(groups.values(), key=lambda group: (min(details[row['id']]['retrieval_rank'] for row in group), group[0]['id']))
    for group in ordered[:budget.max_groups]:
        # A one-valued domain cannot contribute an unseen interaction.
        if len(group) < 2:
            continue
        closure = missing_cells(group, budget=ClosureBudget(arity=2, max_axes=budget.max_coordinates,
                                 max_cells=budget.max_cells_per_group, max_witnesses=budget.max_candidates))
        stats['enumerated_cells'] += closure['counts'].get('cells_enumerated', 0)
        stats['unseen_cells'] += closure['counts'].get('unseen_cells', 0)
        proposals = []
        for cell in closure['gaps']:
            seed = details[cell['seed_id']]
            changes, parents, witnesses = [], {seed['test_id']}, []
            for coordinate in cell['edits']:
                axis = coordinate['axis']
                original = seed['edits'].get(axis)
                donor = details[coordinate['donor_id']]['edits'].get(axis)
                if original is None or donor is None:
                    changes = []
                    break
                changes.append({'span': original['span'], 'before': original['text'], 'after': donor['text']})
                parents.add(details[coordinate['donor_id']]['test_id'])
                witnesses.append(donor['span'])
            if not changes or any(_inside(a['span'], b['span']) for i, a in enumerate(changes) for j, b in enumerate(changes) if i != j):
                continue
            proposals.append({'id': 'cell_' + cell['id'], 'kind': 'observation_relation_cell',
                              'base_test_id': seed['test_id'], 'focus_test_id': seed['test_id'],
                              'source_test_ids': sorted(parents), 'edits': changes, 'imports': [],
                              'relation': {'domain': 'observation_relative_input_tuple',
                                           'constraints': cell['constraints'], 'source_observation_id': seed['observation_id'],
                                           'carrier': cell['carrier'], 'static_status': 'unseen_cell',
                                           'identity_and_phase_status': 'source_binding_and_lexical_order_only'},
                              'oracle': {'status': 'requires_independent_admission'},
                              'provenance': {'source_spans': witnesses},
                              'selection': {'focus_order': seed['retrieval_rank'], 'edit_size': len(changes)}})
        if proposals:
            queues.append(deque(proposals))
    candidates = []
    while queues and len(candidates) < budget.max_candidates:
        for queue in list(queues):
            candidates.append(queue.popleft())
            if not queue:
                queues.remove(queue)
            if len(candidates) >= budget.max_candidates:
                break
    return {'candidates': candidates, 'counts': dict(stats, candidates=len(candidates)),
            'rows': rows, 'budget': asdict(budget), 'status': 'static_hypotheses_not_checked_gaps'}


def annotate_novelty(corpus, frontend, candidates, *, budget=CellBudget()):
    """Deprioritize exact source-value duplicates under the same q/carrier.

    This never calls a static row checked coverage and never removes a
    candidate. It is a finite source novelty heuristic, not a feasibility test.
    """
    rows, details, groups = recover_rows(corpus, frontend, budget=budget)
    by_test = defaultdict(list)
    for row in rows:
        by_test[details[row['id']]['test_id']].append(row)
    output = []
    for original in candidates:
        candidate = copy.deepcopy(original)
        novel, seen, unknown = [], [], []
        if candidate['kind'] != 'aligned_input_substitution':
            candidate['static_novelty'] = {'status': 'relation_hypothesis', 'checked_coverage': False}
            output.append(candidate)
            continue
        for row in by_test[candidate['base_test_id']]:
            coordinates = dict(row['coordinates'])
            axes = {_pos(value['span']): axis for axis, value in details[row['id']]['edits'].items()}
            touched = False
            for edit in candidate['edits']:
                axis = axes.get(_pos(edit['span']))
                if axis is None:
                    continue
                try:
                    value = parse_source_literal(edit['after'], corpus['language'])
                    if isinstance(value, Unknown):
                        continue
                    # Reject non-JSON finite values from this source domain.
                    canonical(value)
                except (ValueError, TypeError):
                    continue
                coordinates[axis] = value
                touched = True
            if not touched:
                continue
            members = groups[canonical([row['observation'], row['carrier']])]
            witness = next((member for member in members if canonical(member['coordinates']) == canonical(coordinates)), None)
            observation = details[row['id']]['observation_id']
            if witness:
                seen.append({'observation_id': observation, 'source_witness_row': witness['id']})
            else:
                novel.append(observation)
        status = 'unseen_source_tuple' if novel else 'already_present_source_tuple' if seen else 'unknown'
        candidate['static_novelty'] = {'status': status, 'new_observation_ids': novel,
                                       'seen_observations': seen, 'checked_coverage': False}
        output.append(candidate)
    return output


def merge_candidates(primary, cells, *, limit=512):
    """Fair domain allocation, never target-dependent priority or filtering."""
    groups, seen = defaultdict(deque), set()
    priority = {'relation_hypothesis': 0, 'unseen_source_tuple': 0, 'unknown': 1, 'already_present_source_tuple': 2}
    primary = sorted(primary, key=lambda item: priority.get(item.get('static_novelty', {}).get('status'), 1))
    for item in [*cells, *primary]:
        signature = canonical([item['base_test_id'], item['edits']])
        if signature not in seen:
            groups[item['kind']].append(item)
            seen.add(signature)
    result = []
    while groups and len(result) < limit:
        for kind in sorted(list(groups)):
            result.append(groups[kind].popleft())
            if not groups[kind]:
                del groups[kind]
            if len(result) >= limit:
                break
    return result
