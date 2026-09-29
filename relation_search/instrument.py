"""Attach source-stable runtime probes and extend measured search parents.

Instrumentation never supplies an oracle.  Original controls are not modified;
additional ``is_source_profile`` test clones measure the corresponding seed
under the same source role/cut identifiers as the edited test.  Helper files are
returned separately, to be added only after test-harness discovery.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
import copy
import hashlib
import itertools
import json

from .runtime import prepare_python_probes


class Unsupported(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _id(*parts):
    return hashlib.sha256(_canonical(parts).encode()).hexdigest()[:24]


def _position(span):
    return span['path'], span['start_byte'], span['end_byte']


def _source_span(span):
    if not isinstance(span, dict):
        return None
    return {key: span[key] for key in ('path', 'start_byte', 'end_byte') if key in span}


def _source_probe(base_test_id, probe):
    """The mutated expression and candidate ID cannot create a new window."""
    anchor = _source_span(probe['insert_before'])
    roles = sorted(((role['name'], _source_span(role.get('origin_span'))) for role in probe['roles']), key=lambda item: item[0])
    descriptor = {'base_test_id': base_test_id, 'cut': anchor, 'roles': roles}
    return {**copy.deepcopy(probe),
            'source_window': _id('source-observation-window-v1', descriptor),
            'probe_id': _id('source-observation-probe-v1', descriptor)}


def _control_probes(candidate):
    explicit = candidate.get('control_runtime_probes')
    if explicit is not None:
        return copy.deepcopy(explicit)
    result = copy.deepcopy(candidate.get('runtime_probes', []))
    for probe in result:
        for role in probe.get('roles', []):
            if 'control_expression' in role:
                role['expression'] = role['control_expression']
    return result


def _program_edits(candidate):
    # A composed candidate stores an input-only snapshot in program_edits.
    # Later oracle revisions live in edits and must reach the emitted test.
    # Only an already instrumented candidate needs the pre-probe snapshot,
    # so repeated instrumentation does not insert each logger twice.
    if candidate.get('instrumentation', {}).get('status') == 'instrumented':
        return copy.deepcopy(candidate['program_edits'])
    return copy.deepcopy(candidate.get('edits', []))


def _probe_insertions(source, path, candidate_id, base_test_id, probes):
    insertions, metadata, helpers, normalized = {}, [], {}, []
    for raw in probes:
        probe = _source_probe(base_test_id, raw)
        normalized.append(probe)
        result = prepare_python_probes(source, path, candidate_id, probe['source_window'], [probe])
        for edit in result['edits']:
            key = _position(edit['span'])
            if key not in insertions:
                insertions[key] = {**edit, 'role': 'relation_runtime_probe'}
            else:
                insertions[key]['after'] += edit['after']
        metadata.extend({**row, 'source_window': probe['source_window']} for row in result['probes'])
        for item in result['helper_files']:
            if item['path'] in helpers and helpers[item['path']] != item:
                raise Unsupported('conflicting_probe_helper_source')
            helpers[item['path']] = item
    return list(insertions.values()), metadata, list(helpers.values()), normalized


def _merge_insertions(source, test, edits, insertions):
    """Prefix a replacement at its own boundary; never guess internal offsets."""
    data = source.encode()
    path = test['span']['path']
    lower, upper = test['span']['start_byte'], test['span']['end_byte']
    result = copy.deepcopy(edits)
    for edit in result:
        span = edit['span']
        if span['path'] != path or not lower <= span['start_byte'] <= span['end_byte'] <= upper:
            raise Unsupported('program_edit_outside_source_test')
        if data[span['start_byte']:span['end_byte']].decode() != edit['before']:
            raise Unsupported('program_edit_before_mismatch')
    ordered = sorted(result, key=lambda edit: _position(edit['span']))
    for left, right in zip(ordered, ordered[1:]):
        a, b = left['span'], right['span']
        if a['end_byte'] > b['start_byte'] or a['start_byte'] == a['end_byte'] == b['start_byte']:
            raise Unsupported('overlapping_source_program_edits')
    for insertion in insertions:
        span = insertion['span']
        position = span['start_byte']
        if span['path'] != path or not lower <= position <= upper:
            raise Unsupported('probe_outside_source_test')
        inside = [edit for edit in result if edit['span']['start_byte'] < position < edit['span']['end_byte']]
        if inside:
            raise Unsupported('probe_inside_replaced_source_span')
        same_start = [edit for edit in result if edit['span']['start_byte'] == position]
        if len(same_start) > 1:
            raise Unsupported('ambiguous_probe_prefix_boundary')
        if same_start:
            same_start[0]['after'] = insertion['after'] + same_start[0]['after']
            same_start[0]['instrumented_prefix'] = True
        else:
            result.append(copy.deepcopy(insertion))
    return sorted(result, key=lambda edit: _position(edit['span']))


def _instrument_one(corpus, candidate):
    original = copy.deepcopy(candidate)
    if corpus.get('language') != 'python' or candidate.get('language', 'python') != 'python':
        return original, [], {'candidate_id': candidate['id'], 'status': 'unsupported_language'}
    probes = candidate.get('runtime_probes', [])
    if not probes:
        return original, [], {'candidate_id': candidate['id'], 'status': 'no_probes'}
    edits = _program_edits(candidate)
    try:
        test = corpus['tests'][candidate['base_test_id']]
        path = test['span']['path']
        record = corpus['sources'][path]
        inserts, metadata, helpers, normalized = _probe_insertions(
            record['code'], path, candidate['id'], candidate['base_test_id'], probes)
        merged = _merge_insertions(record['code'], test, edits, inserts)
    except (Unsupported, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        # Retain the hypothesis unchanged.  An unavailable probe is not a
        # reason to remove a test or manufacture an observed state.
        return original, [], {'candidate_id': candidate['id'], 'status': 'unsupported_probe',
                              'reason': str(error), 'candidate_preserved': True}
    original['program_edits'] = edits
    original['edits'] = merged
    original['runtime_probes'] = normalized
    original['instrumentation'] = {'status': 'instrumented', 'probe_count': len(metadata),
                                   'windows': sorted({row['source_window'] for row in metadata})}
    return original, helpers, {'candidate_id': candidate['id'], 'status': 'instrumented',
                               'is_source_profile': bool(candidate.get('is_source_profile')),
                               'probes': metadata}


def _source_profile(candidate, probes):
    canonical_probes = [_source_probe(candidate['base_test_id'], probe) for probe in probes]
    identity = [{'phase': probe['phase'], 'cut': _source_span(probe['insert_before']),
                 'roles': [{key: role.get(key) for key in ('name', 'expression', 'origin_span')}
                           for role in probe['roles']]} for probe in canonical_probes]
    identifier = 'source_profile_' + _id('source-profile-test-v1', candidate['base_test_id'], identity)
    return {'id': identifier, 'base_test_id': candidate['base_test_id'], 'source_test_ids': [],
            'language': 'python', 'kind': 'source_profile', 'is_source_profile': True,
            'static_parent_id': identifier, 'execution_lane': candidate.get('execution_lane', 'relation_search'),
            'edits': [], 'program_edits': [], 'imports': [],
            'runtime_probes': canonical_probes, 'source_profile_for': [candidate['id']],
            'relation': {'domain': 'original_source_observation', 'status': 'runtime_unconfirmed'},
            'oracle': {'mode': 'retain_all', 'applicability': 'original_source_context'},
            'provenance': {'base_test_id': candidate['base_test_id'],
                           'purpose': 'measure_seed_with_unchanged_inputs_and_assertions'}}


def instrument_candidates(corpus, candidates):
    """Return instrumented hypotheses, seed profiles, helpers and a full ledger.

    ``candidates`` begins with deduplicated source-profile clones, followed by
    the supplied hypotheses in input order. Unsupported hypotheses remain in
    the output unchanged. ``helper_files`` must bypass harness discovery.
    The caller should register source-profile events before judging novelty of
    generated events, regardless of the test runner's discovery order.
    """
    profiles, generated, records, helpers = {}, [], [], {}
    profile_ids = defaultdict(list)
    for candidate in candidates:
        if corpus.get('language') == 'python' and not candidate.get('is_source_profile'):
            probes = _control_probes(candidate)
            if probes:
                try:
                    profile = _source_profile(candidate, probes)
                except (KeyError, TypeError, ValueError) as error:
                    records.append({'candidate_id': candidate['id'], 'status': 'unsupported_source_profile',
                                    'reason': str(error)})
                else:
                    identifier = profile['id']
                    if identifier not in profiles:
                        profiles[identifier] = profile
                    elif candidate['id'] not in profiles[identifier]['source_profile_for']:
                        profiles[identifier]['source_profile_for'].append(candidate['id'])
                    profile_ids[candidate['id']].append(identifier)
        generated.append(copy.deepcopy(candidate))
    supplied_profiles = {row['id'] for row in generated if row.get('is_source_profile')}
    output = []
    for candidate in [*[row for key, row in profiles.items() if key not in supplied_profiles], *generated]:
        transformed, additions, metadata = _instrument_one(corpus, candidate)
        if profile_ids[candidate['id']]:
            transformed['source_profile_ids'] = profile_ids[candidate['id']]
        output.append(transformed)
        records.append(metadata)
        for item in additions:
            if item['path'] in helpers and helpers[item['path']] != item:
                raise ValueError('conflicting runtime helper files')
            helpers[item['path']] = item
    return {'candidates': output, 'helper_files': list(helpers.values()),
            'metadata': {'records': records, 'counts': dict(Counter(row['status'] for row in records)),
                         'source_profile_count': sum(bool(row.get('is_source_profile')) for row in output),
                         'source_profiles_must_seed_seen_before_generated_events': True}}


def _runtime_parent(item, strategy='profile'):
    if 'candidate' in item:
        candidate, feedback = item['candidate'], item.get('feedback', {})
    else:
        candidate, feedback = item, item.get('runtime_feedback', {})
    if (feedback.get('candidate_id', candidate['id']) != candidate['id']
            or candidate.get('is_source_profile') or feedback.get('parent_eligible') is False):
        return None
    if strategy == 'profile':
        if (feedback.get('status') != 'runtime_observed' or feedback.get('retained') is not True
                or not feedback.get('measured_profiles') or feedback.get('profile_baseline_measured') is False):
            return None
    elif strategy == 'rotation':
        if feedback.get('executed') is not True or feedback.get('parent_eligible') is not True:
            return None
    else:
        raise ValueError('Unknown search strategy')
    return candidate, feedback


def _search_edits(candidate):
    return [edit for edit in _program_edits(candidate)
            if edit.get('role') not in {'semantic_expected', 'semantic_observation', 'relation_runtime_probe'}]


def _edit_key(edit):
    return {'span': _source_span(edit['span']), 'before': edit['before'], 'after': edit['after']}


def _edits_key(base_test_id, edits):
    return _id(base_test_id, [_edit_key(edit) for edit in sorted(edits, key=lambda edit: _position(edit['span']))])


def _conflict(left, right):
    a, b = left['span'], right['span']
    if a['path'] != b['path']:
        return False
    if a['start_byte'] == a['end_byte']:
        return b['start_byte'] <= a['start_byte'] < b['end_byte'] or b['start_byte'] == b['end_byte'] == a['start_byte']
    if b['start_byte'] == b['end_byte']:
        return a['start_byte'] <= b['start_byte'] < a['end_byte']
    return a['start_byte'] < b['end_byte'] and b['start_byte'] < a['end_byte']


def _merge_probes(left, right):
    result, seen = [], set()
    for probe in [*left, *right]:
        key = _canonical(probe)
        if key not in seen:
            seen.add(key)
            result.append(copy.deepcopy(probe))
    return result


def _expr_equal(left, right):
    try:
        return ast.dump(ast.parse(left, mode='eval'), include_attributes=False) == ast.dump(ast.parse(right, mode='eval'), include_attributes=False)
    except (ValueError, SyntaxError, TypeError):
        return left == right


def _probe_pair_key(probe):
    return _position(probe['insert_before']), tuple(role['name'] for role in probe['roles'])


def _project_actual(expression, actual, merged):
    exact = next((edit for edit in merged if _position(edit['span']) == _position(actual)), None)
    if exact is not None:
        return exact['after']
    relevant = [edit for edit in merged if _conflict(edit, {'span': actual})]
    if not relevant:
        return expression
    raw = expression.encode()
    if actual['end_byte'] - actual['start_byte'] != len(raw):
        raise Unsupported('composed_input_subedit_has_no_exact_source_expression')
    for edit in sorted(relevant, key=lambda row: row['span']['start_byte'], reverse=True):
        start, end = edit['span']['start_byte'] - actual['start_byte'], edit['span']['end_byte'] - actual['start_byte']
        if not 0 <= start <= end <= len(raw) or raw[start:end].decode() != edit['before']:
            raise Unsupported('composed_input_subedit_has_no_exact_source_expression')
        raw = raw[:start] + edit['after'].encode() + raw[end:]
    return raw.decode()


def _composed_probes(candidate, merged):
    """Re-evaluate input projections against the composed actual arguments.

    A source-variable observation remains a source-variable observation. An
    explicit input projection needs the original actual's span: reading the
    old projected Name after another argument edit would misreport coverage.
    """
    controls = {_probe_pair_key(probe): probe for probe in _control_probes(candidate)}
    own = _search_edits(candidate)
    extras = [edit for edit in merged if _canonical(_edit_key(edit)) not in {_canonical(_edit_key(old)) for old in own}]
    changed, originals, skipped = [], [], []
    for raw in candidate.get('runtime_probes', []):
        source = controls.get(_probe_pair_key(raw))
        if source is None:
            skipped.append({'reason': 'composed_probe_has_no_matching_source_probe', 'cut': raw.get('insert_before')})
            continue
        probe, original = copy.deepcopy(raw), copy.deepcopy(source)
        kept, kept_control = [], []
        baseline_roles = {role['name']: role for role in source['roles']}
        for role in probe['roles']:
            baseline = baseline_roles[role['name']]
            expression = baseline['expression']
            actual = role.get('input_span')
            if actual is None:
                # A uniquely matching source edit can recover an already
                # changed projection; it cannot recover unrelated input roles.
                matches = [edit for edit in own if _expr_equal(edit['before'], expression)
                           and _expr_equal(edit['after'], role['expression'])]
                if not _expr_equal(expression, role['expression']) and len(matches) == 1:
                    actual = matches[0]['span']
            if actual is None:
                origin = role.get('origin_span')
                exact = [edit for edit in merged if origin and _position(origin) == _position(edit['span'])
                         and _expr_equal(edit['before'], expression)]
                if len(exact) == 1:
                    actual = exact[0]['span']
            if actual is not None:
                try:
                    role['expression'] = _project_actual(expression, actual, merged)
                except Unsupported as error:
                    skipped.append({'reason': str(error), 'cut': raw['insert_before'], 'role': role['name']})
                    continue
                role['input_span'] = actual
            else:
                origin = role.get('origin_span') or {}
                direct_read = origin.get('end_byte', 0) - origin.get('start_byte', 0) == len(expression.encode())
                if not direct_read and any(_expr_equal(edit['before'], expression) for edit in extras):
                    skipped.append({'reason': 'composed_input_projection_missing_actual_span',
                                    'cut': raw['insert_before'], 'role': role['name']})
                    continue
            kept.append(role)
            kept_control.append(copy.deepcopy(baseline))
        if kept:
            probe['roles'], original['roles'] = kept, kept_control
            changed.append(probe)
            originals.append(original)
    return changed, originals, skipped


def compose_neighbors(retained_candidates, source_pool, max_edits=4, budget=128, strategy='profile'):
    """Append compatible source edits to eligible actually executed parents.

    Parents carry ``runtime_feedback`` equal to Frontier.observe's result, or
    use ``{candidate, feedback}`` wrappers. Input spans remain coordinates of
    the original source. Oracle revisions and instrumentation never become
    search edits. The profile strategy requires measured retention. The explicit
    rotation control uses all executed eligible parents with the same constructor
    and never manufactures profile feedback. Every combination needs fresh execution.
    """
    if strategy not in {'profile', 'rotation'}:
        raise ValueError('Unknown search strategy')
    if type(max_edits) is not int or max_edits < 1 or type(budget) is not int or budget < 0:
        raise ValueError('max_edits must be positive and budget nonnegative')
    pools = defaultdict(list)
    existing = set()
    for source in source_pool:
        if source.get('is_source_profile'):
            continue
        edits = _search_edits(source)
        pools[source['base_test_id']].append((source, edits))
        existing.add(_edits_key(source['base_test_id'], edits))
    streams = []
    for item in retained_candidates:
        parent = _runtime_parent(item, strategy)
        if parent is None:
            continue
        candidate, feedback = parent
        edits = _search_edits(candidate)
        if not edits or len(edits) >= max_edits:
            continue
        additions = []
        for donor, donated in pools[candidate['base_test_id']]:
            if donor['id'] == candidate['id'] or not donated:
                continue
            extra = [edit for edit in donated if _canonical(_edit_key(edit)) not in {_canonical(_edit_key(old)) for old in edits}]
            if not extra or len(edits) + len(extra) > max_edits:
                continue
            merged = [*copy.deepcopy(edits), *copy.deepcopy(extra)]
            if any(_conflict(a, b) for a, b in itertools.combinations(merged, 2)):
                continue
            merged.sort(key=lambda edit: _position(edit['span']))
            key = _edits_key(candidate['base_test_id'], merged)
            if key in existing:
                continue
            existing.add(key)
            row = copy.deepcopy(candidate)
            left_probes, left_controls, left_skipped = _composed_probes(candidate, merged)
            right_probes, right_controls, right_skipped = _composed_probes(donor, merged)
            row.update(id='composed_' + key, kind='executed_parent_extension',
                       operator='executed_parent_extension', edits=merged, program_edits=copy.deepcopy(merged),
                       source_test_ids=sorted(set(candidate.get('source_test_ids', [])) | set(donor.get('source_test_ids', []))),
                       imports=list({ _canonical(value): value for value in [*candidate.get('imports', []), *donor.get('imports', [])] }.values()),
                       parent_candidate_ids=[candidate['id'], donor['id']],
                       parent_candidate_id=candidate['id'], static_parent_id='composed_' + key,
                       execution_lane='relation_search',
                       runtime_parent_id=candidate['id'],
                       runtime_probes=_merge_probes(left_probes, right_probes),
                       control_runtime_probes=_merge_probes(left_controls, right_controls))
            for field in ('instrumentation', 'source_profile_ids', 'semantic_admission', 'semantic_revision',
                          'semantic_model_judgment', 'runtime_feedback'):
                row.pop(field, None)
            row['relation'] = {'domain': 'executed_parent_extension',
                               'status': 'statically_composed_runtime_unconfirmed',
                               'parents': [candidate.get('relation'), donor.get('relation')]}
            row['oracle'] = {**candidate.get('oracle', {}), 'applicability': 'unknown_requires_fresh_admission'}
            row['provenance'] = {**candidate.get('provenance', {}),
                                 'composition': {'parents': [candidate['id'], donor['id']],
                                                 'runtime_parent_feedback': copy.deepcopy(feedback),
                                                 'selection_strategy': strategy,
                                                 'rule': 'same_base_nonoverlapping_original_source_edits',
                                                 'unavailable_probe_roles': [*left_skipped, *right_skipped],
                                                 'added_edit_count': len(extra)}}
            additions.append(row)
        streams.append(iter(additions))
    result, pending = [], deque(streams)
    while pending and len(result) < budget:
        stream = pending.popleft()
        candidate = next(stream, None)
        if candidate is not None:
            result.append(candidate)
            pending.append(stream)
    return result
