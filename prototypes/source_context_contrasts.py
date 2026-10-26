"""Exact source-context contrasts, for optional oracle-review evidence only.

Two existing observations qualify only when their complete source prefixes,
checker, and actual projection coincide after masking the declaration/test
label, exactly one closed input literal, and the target expected literal.
Earlier assertions, argument order, local names, setup, and operations remain.
Source expectations are unvalidated claims: no value is generated or proved.

Candidate hints require an exact already-observed prefix, not extrapolation
through extra operations, object bindings, or observation stages. Custom helper
roles are not inferred. Missing roles, parameterized tests, scripts, and source
ambiguities remain unknown. This module neither ranks nor executes candidates.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
from itertools import combinations
import json
import math

from anchor_retrieval.syntax import Source, call_parts, child, json_safe, literal, walk
from relation_search.instrument import _program_edits


POLICY = dict(version='exact-source-context-contrasts-v1',
    matching='same source/scope/imports and complete AST prefix; only test name, one literal input, target literal expected are holes',
    roles='existing frontend observed/expected spans; no inferred helper roles or local alpha-renaming',
    hint='exact candidate prefix equals the other already-observed input point while retaining the base expectation',
    meaning='source expectation contrast and review hint; never a correct oracle or behavioral equivalence proof',
    forbidden_inputs=['issue text', 'patch targets', 'target labels', 'oracle answers', 'runtime outcomes', 'provider'])


class Unknown(ValueError):
    pass


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _extent(extent):
    return {key: extent[key] for key in ('path', 'start_byte', 'end_byte')}


def _key(extent):
    return extent['path'], extent['start_byte'], extent['end_byte']


def _inside(inner, outer):
    return (inner['path'] == outer['path'] and
            outer['start_byte'] <= inner['start_byte'] < inner['end_byte'] <= outer['end_byte'])


def _overlap(left, right):
    return (left['path'] == right['path'] and left['start_byte'] < right['end_byte']
            and right['start_byte'] < left['end_byte'])


def _node(source, extent, kind=None):
    if extent['path'] != source.path:
        raise Unknown('source_path_mismatch')
    # Each Source here is owned by this module. Cache immutable syntax facts by
    # source-object identity, never share bindings across modified candidates.
    if not hasattr(source, '_source_contrast_node_index'):
        indexed = defaultdict(list)
        for node in walk(source.root):
            indexed[node.start_byte, node.end_byte].append(node)
        source._source_contrast_node_index = indexed
    found = [node for node in source._source_contrast_node_index.get(
             (extent['start_byte'], extent['end_byte']), ())
             if kind is None or node.type == kind]
    if len(found) != 1:
        raise Unknown('source_node_ambiguous_or_missing')
    return found[0]


def _scalar(source, row):
    if not row or not row.get('span') or not row.get('literal_known'):
        raise Unknown('closed_scalar_literal_unavailable')
    node = _node(source, row['span'], row.get('kind'))
    code = source.text(node)
    if row.get('text') != code:
        raise Unknown('frontend_literal_source_mismatch')
    try:
        value = literal(code)
    except ValueError:
        raise Unknown('closed_scalar_literal_unavailable') from None
    if not (value is None or type(value) in {bool, int, float, str, bytes}):
        raise Unknown('non_scalar_literal')
    if type(value) is float and not math.isfinite(value):
        raise Unknown('non_finite_literal')
    value_type = type(value).__name__
    # Do not collapse Go rune/string or JS null/undefined distinctions.
    if source.language == 'go' and node.type == 'rune_literal':
        value_type = 'go_rune'
    if value is None:
        value_type += ':' + node.type
    return dict(code=code, value=json_safe(value), type=value_type, span=_extent(row['span'])), node


def _name_node(source, test):
    definition = _node(source, test.get('definition_span', test['span']))
    name = child(definition, 'name')
    if name is not None:
        return name
    # Frontend has already identified this registration as a source test. Only
    # its explicit closed title is normalized; no call head is guessed here.
    if source.language == 'typescript' and definition.type == 'call_expression':
        _, args = call_parts(definition)
        if args:
            try:
                title = literal(source.text(args[0]))
            except ValueError:
                title = None
            if type(title) is str and title == test.get('name'):
                return args[0]
    raise Unknown('explicit_test_name_unavailable')


def _normal(source, test_node, cutoff, name, expected, observed, max_nodes):
    """Return a prefix term and exact source-node paths in that term."""
    holes = {(name.start_byte, name.end_byte, name.type): 'test_name',
             (expected.start_byte, expected.end_byte, expected.type): 'expected'}
    locations, seen = {}, set()
    count = 0

    def visit(node, path):
        nonlocal count
        if node.start_byte >= cutoff:
            return None
        count += 1
        if count > max_nodes:
            raise Unknown('prefix_node_budget')
        key = node.start_byte, node.end_byte, node.type
        locations[key] = path
        if key in holes:
            seen.add(holes[key])
            return ('hole:' + holes[key], '', (), False)
        is_observed = node == observed
        if is_observed:
            seen.add('observed')
        children = []
        for nested in node.children:
            item = visit(nested, path + (len(children),))
            if item is not None:
                children.append(item)
        if children:
            return node.type, '', tuple(children), is_observed
        if node.end_byte > cutoff:
            raise Unknown('prefix_crosses_source_token')
        return node.type, source.text(node), (), is_observed

    result = visit(test_node, ())
    if seen != {'test_name', 'expected', 'observed'}:
        raise Unknown('source_role_not_in_prefix')
    return result, locations


def _replace(term, path):
    if not path:
        return ('hole:input', '', (), term[3])
    kind, text, children, observed = term
    modified = list(children)
    modified[path[0]] = _replace(modified[path[0]], path[1:])
    return kind, text, tuple(modified), observed


def _metadata(source, test):
    scope = test.get('enclosing_scope_span')
    if not scope or scope['path'] != source.path:
        raise Unknown('source_scope_unavailable')
    return dict(language=source.language, source_path=source.path,
                source_sha256=hashlib.sha256(source.data).hexdigest(),
                scope=_extent(scope), imports=sorted(source.imports.items()))


def _base(source, test, observation, max_nodes):
    if source.root.has_error:
        raise Unknown('source_parse_error')
    if test.get('owner_kind') == 'module_script':
        raise Unknown('module_script_not_supported')
    if (test.get('parameter_rows') or test.get('parameterization_status', 'none_detected') != 'none_detected'):
        raise Unknown('parameterized_source_not_supported')
    if observation.get('kind') != 'assertion' or observation.get('observation_type') == 'exception':
        raise Unknown('literal_expectation_role_unavailable')
    assertion = observation.get('assertion_span') or observation.get('span')
    if not assertion or not _inside(assertion, test['span']):
        raise Unknown('assertion_outside_source_test')
    expected, expected_node = _scalar(source, observation.get('expected'))
    observed_row = observation.get('observed') or {}
    if not observed_row.get('span') or not _inside(observed_row['span'], assertion) or not _inside(expected['span'], assertion):
        raise Unknown('observation_role_outside_assertion')
    observed = _node(source, observed_row['span'], observed_row.get('kind'))
    if source.text(observed) != observed_row.get('text'):
        raise Unknown('frontend_actual_source_mismatch')
    if _overlap(observed_row['span'], expected['span']):
        raise Unknown('observation_roles_overlap')
    test_node = _node(source, test['span'])
    name = _name_node(source, test)
    term, locations = _normal(source, test_node, assertion['end_byte'], name,
                              expected_node, observed, max_nodes)
    metadata = _metadata(source, test)
    return dict(term=term, locations=locations, metadata=metadata,
                concrete_id=_sha([metadata, term]), expected=expected, name=name,
                assertion=_extent(assertion), observed=_extent(observed_row['span']))


def build_catalogue(corpus, frontend, *, max_prefix_nodes=20000):
    """Return deterministic source points/contrasts; source roles stay hypotheses.

    Frontend unknown expected/helper roles are not completed by this analysis.
    Literal inputs need an existing frontend may link to this observation.
    """
    if type(max_prefix_nodes) is not int or max_prefix_nodes < 1:
        raise ValueError('max_prefix_nodes must be positive')
    sources = {path: Source(path, row['code'], row.get('language', corpus['language']))
               for path, row in sorted(corpus['sources'].items())}
    source_hashes = {path: hashlib.sha256(source.data).hexdigest() for path, source in sources.items()}
    calls = {row['id']: row for row in frontend.get('calls', [])}
    values = defaultdict(list)
    for value in frontend.get('values', []):
        values[value.get('test_id')].append(value)
    points, unknowns = [], []
    for observation in sorted(frontend.get('observations', []), key=lambda row: row['id']):
        identifier = observation['id']
        try:
            test = corpus['tests'][observation['test_id']]
            source = sources[test['span']['path']]
            base = _base(source, test, observation, max_prefix_nodes)
            inputs = []
            for value in values[observation['test_id']]:
                extent = value.get('span')
                if (not extent or not _inside(extent, test['span'])
                        or extent['end_byte'] > base['assertion']['end_byte']
                        or value.get('diagnostic') or value.get('oracle_dependency')
                        or value.get('expected_in') or value.get('role') == 'expected'):
                    continue
                linked = any(identifier in calls.get(port.get('call_id'), {}).get('observation_ids', [])
                             for port in value.get('input_slots', []) + value.get('argument_slots', []))
                if not linked:
                    continue
                try:
                    scalar, node = _scalar(source, value)
                except Unknown:
                    continue
                if _overlap(extent, base['expected']['span']):
                    continue
                path = base['locations'].get((node.start_byte, node.end_byte, node.type))
                if path is not None:
                    inputs.append((scalar, path))
            for scalar, path in sorted(inputs, key=lambda item: _key(item[0]['span'])):
                frame_id = _sha([base['metadata'], _replace(base['term'], path)])
                record = dict(observation_id=identifier, test_id=observation['test_id'],
                    input=scalar, expected=base['expected'], frame_id=frame_id,
                    concrete_id=base['concrete_id'], assertion_span=base['assertion'],
                    actual_span=base['observed'], name_span=dict(path=source.path, start_byte=base['name'].start_byte,
                        end_byte=base['name'].end_byte), prefix_span=dict(path=source.path,
                        start_byte=test['span']['start_byte'], end_byte=base['assertion']['end_byte']),
                    metadata=base['metadata'])
                record['id'] = _sha([identifier, scalar['span']])
                points.append(record)
            if not inputs:
                unknowns.append(dict(observation_id=identifier, reason='no_closed_observation_linked_input'))
        except (Unknown, KeyError, TypeError, IndexError, RecursionError, UnicodeError) as error:
            unknowns.append(dict(observation_id=identifier, reason=str(error)))
    points = sorted({point['id']: point for point in points}.values(), key=lambda point: point['id'])
    grouped = defaultdict(list)
    for point in points:
        grouped[point['frame_id']].append(point)
    pairs = []
    for frame_id, group in sorted(grouped.items()):
        by_input = defaultdict(set)
        for point in group:
            by_input[_sha([point['input']['type'], point['input']['value']])].add(
                _sha([point['expected']['type'], point['expected']['value']]))
        if any(len(expectations) > 1 for expectations in by_input.values()):
            unknowns.append(dict(frame_id=frame_id, reason='conflicting_source_expectations_at_same_input'))
            continue
        for left, right in combinations(group, 2):
            if ((left['input']['type'], left['input']['value']) == (right['input']['type'], right['input']['value'])
                    or (left['expected']['type'], left['expected']['value']) == (right['expected']['type'], right['expected']['value'])):
                continue
            pairs.append(dict(id=_sha([left['id'], right['id']]), frame_id=frame_id,
                              point_ids=[left['id'], right['id']], status='source_contrast_only_not_oracle_proof'))
    return dict(policy=copy.deepcopy(POLICY), policy_sha256=_sha(POLICY), source_sha256=source_hashes,
                max_prefix_nodes=max_prefix_nodes, points=points, pairs=sorted(pairs, key=lambda pair: pair['id']),
                unknowns=sorted(unknowns, key=lambda item: json.dumps(item, sort_keys=True)),
                stats=dict(observations=len(frontend.get('observations', [])), points=len(points),
                           contrast_pairs=len(pairs), contrast_frames=len({pair['frame_id'] for pair in pairs})))


def _map(extent, edits, *, contained=False):
    start, end = extent['start_byte'], extent['end_byte']
    delta_start = delta_end = 0
    for edit in edits:
        left, right = edit['span']['start_byte'], edit['span']['end_byte']
        if left == right and left in {start, end}:
            raise Unknown('insertion_on_observation_boundary')
        if left < end and start < right:
            if not contained or left < start or right > end:
                raise Unknown('source_role_edited_or_crossed')
        delta = len(edit['after'].encode()) - (right - left)
        if right <= start:
            delta_start += delta
        if right <= end:
            delta_end += delta
    return dict(path=extent['path'], start_byte=start + delta_start, end_byte=end + delta_end)


def candidate_hints(corpus, frontend, candidates, *, catalogue=None, max_prefix_nodes=20000):
    """Exact already-observed source contrasts, never an oracle edit proposal."""
    catalogue = catalogue if catalogue is not None else build_catalogue(corpus, frontend, max_prefix_nodes=max_prefix_nodes)
    actual_hashes = {path: hashlib.sha256(row['code'].encode()).hexdigest() for path, row in corpus['sources'].items()}
    if actual_hashes != catalogue['source_sha256']:
        raise ValueError('source catalogue changed')
    points = {point['id']: point for point in catalogue['points']}
    paired = defaultdict(list)
    for pair in catalogue['pairs']:
        left, right = pair['point_ids']
        paired[left].append((pair, points[right])); paired[right].append((pair, points[left]))
    by_test = defaultdict(list)
    for point_id in paired:
        by_test[points[point_id]['test_id']].append(points[point_id])
    observations = {row['id']: row for row in frontend.get('observations', [])}
    hints, unknowns = [], []
    for candidate in sorted(candidates, key=lambda row: row['id']):
        try:
            test = corpus['tests'][candidate['base_test_id']]
            if not by_test[candidate['base_test_id']]:
                raise Unknown('no_source_contrast_for_base_test')
            path = test['span']['path']; original = corpus['sources'][path]['code'].encode()
            if candidate.get('imports'):
                raise Unknown('added_import_context_not_supported')
            edits = sorted(_program_edits(candidate), key=lambda edit: (edit['span']['start_byte'], edit['span']['end_byte']))
            prior_end = -1
            for edit in edits:
                extent = edit['span']
                if (extent['path'] != path or not test['span']['start_byte'] <= extent['start_byte'] <= extent['end_byte'] <= test['span']['end_byte']):
                    raise Unknown('candidate_edit_outside_source_test')
                if extent['start_byte'] < prior_end:
                    raise Unknown('candidate_edits_overlap')
                prior_end = extent['end_byte']
                if original[extent['start_byte']:extent['end_byte']].decode() != edit['before']:
                    raise Unknown('candidate_edit_source_mismatch')
            modified = original
            for edit in reversed(edits):
                extent = edit['span']
                modified = modified[:extent['start_byte']] + edit['after'].encode() + modified[extent['end_byte']:]
            source = Source(path, modified.decode(), corpus['sources'][path].get('language', corpus['language']))
            if source.root.has_error:
                raise Unknown('modified_source_parse_error')
            queries = {}
            for point in by_test[candidate['base_test_id']]:
                oid = point['observation_id']
                if oid not in queries:
                    try:
                        expected = _map(point['expected']['span'], edits)
                        name = _map(point['name_span'], edits)
                        assertion = _map(point['assertion_span'], edits, contained=True)
                        observed = _map(point['actual_span'], edits, contained=True)
                        whole = _map(test['span'], edits, contained=True)
                        original_q = observations[oid]
                        expected_node = _node(source, expected, original_q['expected']['kind'])
                        actual_node = _node(source, observed, original_q['observed']['kind'])
                        name_node = _node(source, name)
                        if source.text(expected_node) != point['expected']['code']:
                            raise Unknown('source_expectation_not_retained')
                        term, _ = _normal(source, _node(source, whole), assertion['end_byte'], name_node,
                            expected_node, actual_node, catalogue['max_prefix_nodes'])
                        queries[oid] = _sha([point['metadata'], term])
                    except (Unknown, KeyError, TypeError, IndexError, RecursionError, UnicodeError) as error:
                        queries[oid] = None
                        unknowns.append(dict(candidate_id=candidate['id'], observation_id=oid, reason=str(error)))
                for pair, other in paired[point['id']]:
                    if queries[oid] == other['concrete_id']:
                        hints.append(dict(candidate_id=candidate['id'], observation_id=oid,
                            source_pair_id=pair['id'], retained_source_point_id=point['id'],
                            corresponding_source_point_id=other['id'], retained_expected=point['expected'],
                            corresponding_expected=other['expected'],
                            status='review_source_expectation_contrast_not_automatic_revision'))
        except (Unknown, KeyError, TypeError, IndexError, RecursionError, UnicodeError) as error:
            unknowns.append(dict(candidate_id=candidate['id'], reason=str(error)))
    return dict(hints=sorted(hints, key=lambda row: (row['candidate_id'], row['observation_id'], row['source_pair_id'])),
                unknowns=sorted(unknowns, key=lambda row: json.dumps(row, sort_keys=True)),
                stats=dict(candidate_count=len(candidates), hinted_candidates=len({row['candidate_id'] for row in hints}),
                           hint_count=len(hints)), oracle_correctness_proved=False, candidate_ranking_unchanged=True)
