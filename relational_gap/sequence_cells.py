"""Line-edit interval hypotheses from three source string versions.

Carrier syntax supplies version coordinates, not semantic roles. A common base
is a source member whose two exact single-hunk diffs can be reconstructed. Its
role remains a hypothesis even when this syntactic choice is unique. New
versions reuse the two source replacement fragments and vary bounded base
intervals; every reported Allen relation is checked again by an exact re-diff.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import difflib
import heapq
import json

from anchor_retrieval.syntax import Source
from generic_composition.corpus import source_text
from generic_composition.edits import encode_literal
from generic_composition.engine import expected_only, stable_id
from .structured_ports import carrier_ports, structural_slot_key


@dataclass(frozen=True)
class SequenceBudget:
    max_candidates: int = 128
    max_triples: int = 64
    max_pair_plans: int = 1024
    max_attempts: int = 8192
    max_lines: int = 32
    max_string_bytes: int = 8192
    max_observations: int = 2


def allen_relation(left, right):
    """The thirteen directed relations between nonempty half-open intervals."""
    a, b = left
    c, d = right
    if not (a < b and c < d):
        raise ValueError('Allen cells require nonempty intervals')
    if b < c: return 'before'
    if b == c: return 'meets'
    if d < a: return 'after'
    if d == a: return 'met_by'
    if a == c:
        return 'equal' if b == d else 'starts' if b < d else 'started_by'
    if b == d:
        return 'finishes' if a > c else 'finished_by'
    if a < c:
        return 'overlaps' if b < d else 'contains'
    return 'overlapped_by' if b > d else 'during'


def _position(row):
    position = row.get('span', row)
    return position['path'], position['start_byte'], position['end_byte']


def _round_robin(streams):
    queue = deque(iter(stream) for stream in streams)
    while queue:
        stream = queue.popleft()
        item = next(stream, None)
        if item is not None:
            queue.append(stream)
            yield item


def line_edit(base, version):
    """One deterministic, reconstructible, nonempty source-relative edit."""
    before, after = base.splitlines(keepends=True), version.splitlines(keepends=True)
    changed = [row for row in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes()
               if row[0] != 'equal']
    if len(changed) != 1:
        return None
    kind, start, end, lo, hi = changed[0]
    if start == end:
        return None
    payload = after[lo:hi]
    if before[:start] + payload + before[end:] != after:
        return None
    offsets = [0]
    for line in after:
        offsets.append(offsets[-1] + len(line.encode()))
    return {'kind': kind, 'interval': [start, end], 'replacement_lines': payload,
            'replacement': ''.join(payload), 'source_version_lines': [lo, hi],
            'source_version_bytes': [offsets[lo], offsets[hi]], 'exact_source_reconstruction': True}


def _receiver_key(call):
    binding = call.get('receiver_binding') or {}
    identity = binding.get('origin_binding_id') or binding.get('binding_id')
    if identity:
        return 'source_binding', identity
    receiver = call.get('receiver')
    return ('unknown_receiver', receiver.get('text')) if receiver else ('free_call',)


def _triples(corpus, frontend, budget, skipped):
    sources = {path: Source(path, metadata['code'], metadata.get('language', corpus['language']))
               for path, metadata in corpus['sources'].items()
               if metadata.get('complete_file', True) and not metadata.get('parse_error')}
    call_map = {_position(call): call for call in frontend.get('calls', ())}
    direct, successive = defaultdict(list), defaultdict(list)
    seen = set()
    for donor in corpus.get('donors', ()):
        if (donor['test_id'] not in corpus['tests'] or donor['span']['path'] not in sources
                or donor.get('diagnostic') or donor.get('role') == 'expected' or expected_only(donor)
                or not donor.get('literal_known') or type(donor.get('literal_value')) is not str):
            continue
        value = donor['literal_value']
        lines = value.splitlines(keepends=True)
        if len(lines) < 3 or len(set(lines)) < 3:
            continue
        if len(lines) > budget.max_lines or len(value.encode()) > budget.max_string_bytes:
            skipped['source_sequence_size_budget'] += 1
            continue
        if source_text(corpus, donor['span']) != donor.get('text'):
            skipped['non_source_expanded_sequence'] += 1
            continue
        for port in carrier_ports(sources[donor['span']['path']], donor, frontend):
            call_position = _position(port['call_span'])
            call = call_map.get(call_position)
            if call is None or call.get('role') != 'operation':
                continue
            key = donor['test_id'], _position(donor), structural_slot_key(port), call_position
            if key in seen:
                continue
            seen.add(key)
            item = {'donor': donor, 'port': port, 'call': call}
            path = json.dumps(port.get('structural_path', []), sort_keys=True, ensure_ascii=True)
            direct[donor['test_id'], call_position, path].append(item)
            successive[donor['test_id'], structural_slot_key(port), _receiver_key(call)].append(item)
    parents, triple_seen = defaultdict(list), set()

    def add(test_id, items, kind, alignment):
        if len({_position(item['donor']) for item in items}) != 3:
            return
        if len({item['donor']['literal_value'] for item in items}) != 3:
            return
        key = test_id, tuple(_position(item['donor']) for item in items)
        if key in triple_seen:
            return
        triple_seen.add(key)
        parents[test_id].append({'test_id': test_id, 'members': items, 'carrier_kind': kind,
                                 'alignment': alignment})

    for (test_id, call_position, path), members in sorted(direct.items(), key=lambda item: repr(item[0])):
        members = sorted(members, key=lambda item: (item['port']['argument_slot'], _position(item['donor'])))
        for start in range(max(0, len(members) - 2)):
            selected = members[start:start + 3]
            if len({item['port']['argument_slot'] for item in selected}) == 3:
                add(test_id, selected, 'three_source_argument_coordinates',
                    {'call_span': selected[0]['call']['span'], 'structural_path': json.loads(path)})
    for (test_id, key, receiver), members in sorted(successive.items(), key=lambda item: repr(item[0])):
        members = sorted(members, key=lambda item: (_position(item['call']), _position(item['donor'])))
        for start in range(max(0, len(members) - 2)):
            selected = members[start:start + 3]
            if len({_position(item['call']) for item in selected}) == 3:
                add(test_id, selected, 'successive_source_versions_at_structural_port',
                    {'structural_slot': list(key), 'receiver_alignment': list(receiver),
                     'structural_path': selected[0]['port'].get('structural_path', [])})
    tests = corpus['tests']
    ordered = sorted(parents, key=lambda key: (tests[key].get('retrieval_rank') or 10**9, _position(tests[key])))
    for index, triple in enumerate(_round_robin(parents[key] for key in ordered)):
        if index >= budget.max_triples:
            skipped['source_triple_budget'] += 1
            break
        yield triple


def _base_hypotheses(triple, skipped):
    members = triple['members']
    found = []
    for base_index in range(3):
        base = members[base_index]['donor']['literal_value']
        lines = base.splitlines(keepends=True)
        if len(set(lines)) != len(lines):
            skipped['base_line_context_not_unique'] += 1
            continue
        sides = [index for index in range(3) if index != base_index]
        edits = [line_edit(base, members[index]['donor']['literal_value']) for index in sides]
        if any(edit is None for edit in edits):
            skipped['base_diffs_not_two_single_nonempty_hunks'] += 1
            continue
        found.append({'base_index': base_index, 'side_indices': sides, 'base': base, 'lines': lines,
                      'source_edits': edits, 'source_relation': allen_relation(*(edit['interval'] for edit in edits))})
    for hypothesis in found:
        yield dict(hypothesis, base_status='unique_source_single_hunk_base' if len(found) == 1
                   else 'multiple_source_single_hunk_base_hypotheses')


def _interval_pairs(hypothesis, budget):
    """Best-first finite endpoint changes; at most max_pair_plans are visited."""
    intervals = [(start, end) for start in range(len(hypothesis['lines']))
                 for end in range(start + 1, len(hypothesis['lines']) + 1)]
    originals = [tuple(edit['interval']) for edit in hypothesis['source_edits']]
    def distance(interval, original):
        return int(interval != original), abs(interval[0] - original[0]) + abs(interval[1] - original[1])
    choices = [sorted(intervals, key=lambda interval: (*distance(interval, original), interval)) for original in originals]
    def priority(i, j):
        a, b = distance(choices[0][i], originals[0]), distance(choices[1][j], originals[1])
        # Nearby two-version changes must remain reachable when neither source
        # one-line footprint alone can realize a strict partial overlap.
        return a[1] + b[1], a[0] + b[0], choices[0][i], choices[1][j], i, j
    queue, queued = [priority(0, 0)], {(0, 0)}
    for _ in range(budget.max_pair_plans):
        if not queue:
            break
        delta, changed, left, right, i, j = heapq.heappop(queue)
        yield left, right, {'changed_version_count': changed, 'endpoint_distance': delta}
        for a, b in ((i + 1, j), (i, j + 1)):
            if a < len(choices[0]) and b < len(choices[1]) and (a, b) not in queued:
                queued.add((a, b))
                heapq.heappush(queue, priority(a, b))


def _observers(triple, capsules, bindings, budget):
    last = max(item['call']['span']['end_byte'] for item in triple['members'])
    calls = {item['call']['id'] for item in triple['members']}
    choices = []
    for q in capsules[triple['test_id']]:
        position = q.get('assertion_span')
        if not position or position['end_byte'] < last:
            continue
        observed = q.get('observed') or {}
        bound = q.get('observed_binding') or {}
        binding = bindings.get(bound.get('binding_id'))
        visited = set()
        while (observed.get('kind') == 'identifier' and binding is not None
               and not binding.get('contexts') and binding['id'] not in visited):
            visited.add(binding['id'])
            observed = binding.get('value') or {}
            if observed.get('kind') != 'identifier':
                break
            previous = [b for b in bindings.values() if b['test_id'] == triple['test_id']
                        and b.get('simple_name') and b['name'] == observed.get('text')
                        and b['definition_end'] <= binding['span']['start_byte']]
            binding = max(previous, key=lambda b: b['definition_end']) if previous else None
        if visited and observed.get('span', {}).get('end_byte', last) < last:
            continue  # The assertion would read a snapshot predating the triple.
        overlap = bool(calls & set(q.get('source_call_ids', ())))
        if position['start_byte'] < last and not overlap:
            continue
        choices.append((not overlap, position['start_byte'], q['id'], q))
    return [row[-1] for row in sorted(choices)[:budget.max_observations]]


def generate_sequence_cells(corpus, frontend, *, budget: SequenceBudget | None = None):
    budget = budget or SequenceBudget()
    if any(type(value) is not int or value < 1 for value in asdict(budget).values()) or budget.max_lines < 3:
        raise ValueError('Sequence budgets must be positive integers and max_lines at least three')
    skipped, candidates, seen, attempts = Counter(), [], set(), 0
    capsules, plans = defaultdict(list), defaultdict(list)
    for q in corpus.get('capsules', ()):
        capsules[q['test_id']].append(q)

    def result(exhausted=False):
        return {'candidates': candidates, 'skipped': dict(sorted(skipped.items())), 'attempts': attempts,
                'budget_exhausted': exhausted or bool(skipped['pair_plan_budget'] or skipped['source_triple_budget']),
                'budget': asdict(budget), 'domain': 'sequence_edit_relation'}

    if corpus['language'] not in {'python', 'typescript', 'go'}:
        skipped['sequence_literal_language_not_supported'] += 1
        return result()
    for triple in _triples(corpus, frontend, budget, skipped):
        observers = _observers(triple, capsules, {b['id']: b for b in frontend.get('bindings', ())}, budget)
        if not observers:
            skipped['following_source_observation_not_recovered'] += 1
            continue
        for hypothesis in _base_hypotheses(triple, skipped):
            for q in observers:
                plans[triple['test_id']].append((triple, hypothesis, q))

    def proposals(triple, hypothesis, q):
        nonlocal attempts
        relations = {hypothesis['source_relation']}
        plan_count = 0
        for left, right, cost in _interval_pairs(hypothesis, budget):
            if attempts >= budget.max_attempts:
                return
            attempts += 1
            plan_count += 1
            relation = allen_relation(left, right)
            if relation in relations:
                continue
            changed, rematched, edits = [], [], []
            for side, interval in enumerate((left, right)):
                source_edit = hypothesis['source_edits'][side]
                value = ''.join(hypothesis['lines'][:interval[0]] + source_edit['replacement_lines']
                                + hypothesis['lines'][interval[1]:])
                rematch = line_edit(hypothesis['base'], value)
                if (rematch is None or rematch['interval'] != list(interval)
                        or rematch['replacement'] != source_edit['replacement']):
                    skipped['generated_diff_did_not_match_planned_footprint'] += 1
                    break
                if len(value.encode()) > budget.max_string_bytes:
                    skipped['generated_sequence_size_budget'] += 1
                    break
                rematched.append(rematch)
                item = triple['members'][hypothesis['side_indices'][side]]['donor']
                if value != item['literal_value']:
                    edits.append({'span': item['span'], 'before': item['text'],
                                  'after': encode_literal(value, corpus['language'], item['text'])})
                changed.append(value)
            if len(rematched) != 2 or not edits:
                continue
            if allen_relation(*(edit['interval'] for edit in rematched)) != relation:
                skipped['generated_relation_rematch_failed'] += 1
                continue
            relations.add(relation)
            yield triple, hypothesis, q, relation, edits, rematched, cost
            if len(relations) == 13:
                return
        if plan_count >= budget.max_pair_plans:
            skipped['pair_plan_budget'] += 1

    tests = corpus['tests']
    ordered = sorted(plans, key=lambda key: (tests[key].get('retrieval_rank') or 10**9, _position(tests[key])))
    streams = [_round_robin(proposals(*plan) for plan in plans[test_id]) for test_id in ordered]
    for triple, hypothesis, q, relation, edits, rematched, cost in _round_robin(streams):
        identifier = stable_id('sequence_edit_relation', triple['test_id'], q['id'], edits,
                               hypothesis['base_index'], hypothesis['side_indices'])
        if identifier in seen:
            continue
        seen.add(identifier)
        members = triple['members']
        candidates.append({
            'id': identifier, 'base_test_id': triple['test_id'], 'source_test_ids': [triple['test_id']],
            'language': corpus['language'], 'kind': 'sequence_edit_relation', 'edits': edits, 'imports': [],
            'source_observation_id': q['id'], 'target_capsule_id': q['id'],
            'relation': {'domain': 'sequence_edit_relation',
                         'cell': {'allen_relation': relation, 'left_interval': rematched[0]['interval'],
                                  'right_interval': rematched[1]['interval'], 'units': 'base_line_boundaries'},
                         'source_relation': hypothesis['source_relation'], 'source_base_index': hypothesis['base_index'],
                         'source_side_indices': hypothesis['side_indices'], 'base_status': hypothesis['base_status'],
                         'base_role_semantics': 'unknown_source_version_hypothesis',
                         'carrier_kind': triple['carrier_kind'], 'alignment': triple['alignment'],
                         'status': 'statically_constructed_runtime_unconfirmed',
                         'coverage_status': 'relation_absent_from_this_source_triple; no_execution_claim',
                         'observation_relevance': 'source_call_dependence_or_following_observation; state_effects_unknown',
                         'runtime_obligation': 'confirm_version_roles_and_existing_q_applicability'},
            'oracle': {'mode': 'retain_all', 'source_test_id': triple['test_id'], 'assertion_ids': [q['id']],
                       'applicability': 'requires_independent_admission', 'basis': None},
            'provenance': {'source_spans': [item['donor']['span'] for item in members],
                           'source_calls': [item['call']['span'] for item in members],
                           'source_structural_paths': [item['port'].get('structural_path', []) for item in members],
                           'source_base_span': members[hypothesis['base_index']]['donor']['span'],
                           'source_edit_footprints': hypothesis['source_edits'],
                           'rematched_edit_footprints': rematched,
                           'replacement_source_spans': [members[index]['donor']['span'] for index in hypothesis['side_indices']],
                           'source_observation_span': q['assertion_span'],
                           'checks': {'unique_base_line_context': True, 'both_source_versions_reconstructed': True,
                                      'replacement_fragments_unchanged': True, 'generated_footprints_rematched_exactly': True,
                                      'allen_relation_rematched': True},
                           'diff': {'algorithm': 'difflib.SequenceMatcher', 'autojunk': False,
                                    'unit': 'splitlines_keepends', 'scope': 'one_nonempty_edit_per_version'},
                           'unproved': ['semantic_version_roles', 'consumer_edit_semantics', 'runtime_aliases', 'oracle_transport']},
            'selection': {'base_retrieval_rank': tests[triple['test_id']].get('retrieval_rank'),
                          'schedule': 'parent_then_source_triple_and_relation_round_robin',
                          'edit_cost': cost, 'minimality': 'best_first_endpoint_distance_then_changed_versions_within_plan_budget'},
        })
        if len(candidates) >= budget.max_candidates:
            skipped['candidate_budget'] += 1
            return result(True)
    if attempts >= budget.max_attempts:
        skipped['attempt_budget'] += 1
        return result(True)
    return result()
