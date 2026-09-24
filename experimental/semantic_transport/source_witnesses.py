"""Attach existing input/expectation examples to a proposed literal relation.

This is a source consistency check, not an oracle proof. It never executes the
subject. A witness is used only when before/after/target assertions have the same
AST prefix, including setup, parameters and decorators, after replacing the test
name and the explicit input/whole-expected holes. Expected constructors are not
invertible in general, so their internal literal holes are not witness values.
Parameter rows and helper oracle conversions are outside this initial fragment.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import copy

from anchor_retrieval.syntax import Source, child, walk
from generic_composition import engine
from . import oracle
from .proposals import _expected


def _key(span):
    return span['start_byte'], span['end_byte']


def _inside(inner, outer):
    return (inner['path'] == outer['path']
            and outer['start_byte'] <= inner['start_byte'] < inner['end_byte'] <= outer['end_byte'])


def attach(corpus, candidates):
    """Return copies carrying zero or one exact-frame source witness each."""
    donors = {d['id']: d for d in engine.expanded_donors(corpus)}
    capsules = {c['id']: c for c in corpus['capsules']}
    by_test = defaultdict(list)
    for c in corpus['capsules']:
        by_test[c['test_id']].append(c)
    parsed, nodes, cached = {}, {}, {}
    skipped, output = Counter(), []

    def frame(donor, capsule):
        cache_key = donor['id'], capsule['id']
        if cache_key in cached:
            return cached[cache_key]
        cached[cache_key] = None
        parent = corpus['tests'][capsule['test_id']]
        if (donor.get('parameter_row') or not donor.get('literal_known')
                or capsule.get('helper_assertions') or parent.get('parameter_rows')
                or parent.get('parameterization_status', 'none_detected') != 'none_detected'):
            return None
        position = donor['span']
        assertion = capsule['assertion_span']
        if not _inside(position, assertion):
            return None
        path = position['path']
        if path not in parsed:
            parsed[path] = Source(path, corpus['sources'][path]['code'], corpus['language'])
            nodes[path] = {(n.start_byte, n.end_byte): n for n in walk(parsed[path].root)}
        source = parsed[path]
        try:
            expected, value, evidence = _expected(corpus, capsule, source, {})
        except (KeyError, TypeError, ValueError):
            return None
        if evidence['kind'] != 'literal':
            return None
        if not _inside(expected, assertion) or _inside(expected, position) or _inside(position, expected):
            return None
        node = nodes[path].get(_key(parent['span']))
        definition = nodes[path].get(_key(parent.get('definition_span', parent['span'])))
        name = child(definition, 'name') if definition is not None else None
        if node is None or definition is None:
            return None
        holes = {_key(position): 'input', _key(expected): 'expected'}
        if name is not None:
            holes[name.start_byte, name.end_byte] = 'test_name'
        seen = set()

        def normalize(current):
            where = current.start_byte, current.end_byte
            if current.start_byte >= assertion['end_byte']:
                return None
            if where in holes:
                seen.add(holes[where])
                return ('hole', holes[where])
            if current.type == 'comment':
                return None
            if not current.children:
                return current.type, source.text(current)
            return current.type, tuple(v for child in current.children
                                       if (v := normalize(child)) is not None)

        tree = normalize(node)
        if not {'input', 'expected'} <= seen:
            return None
        record = {'shape': tree, 'value': value, 'expected_span': expected,
                  'capsule_id': capsule['id'], 'test_id': capsule['test_id']}
        cached[cache_key] = record
        return record

    for candidate in candidates:
        row = copy.deepcopy(candidate)
        context = candidate['context']
        provenance = context.get('provenance', {})
        ids = provenance.get('source_donor_ids', [])
        if (context['kind'] not in {'literal_difference', 'local_literal_context'}
                or len(ids) != 2 or len(candidate.get('arg', [])) != 1
                or len(candidate.get('pre', [])) != 1 or candidate.get('projection')):
            output.append(row)
            continue
        target = donors.get(provenance.get('target_donor_id'))
        before, after = (donors.get(i) for i in ids)
        if not target or not before or not after:
            skipped['donor_unavailable'] += 1
            output.append(row)
            continue
        after_input = oracle.parse_source_literal(after['text'], corpus['language'])
        if isinstance(after_input, oracle.Unknown):
            skipped['source_input_not_statically_available'] += 1
            output.append(row)
            continue
        # File and enclosing lexical scope fix nonlocal callee/name meanings.
        parents = [corpus['tests'][d['test_id']] for d in (target, before, after)]
        scopes = [(p['span']['path'], p.get('enclosing_scope_span')) for p in parents]
        base = frame(target, capsules[candidate['capsule_id']])
        if base is None or any(s != scopes[0] for s in scopes[1:]):
            skipped['target_frame_or_scope_not_available'] += 1
            output.append(row)
            continue
        left = [f for c in by_test[before['test_id']] if (f := frame(before, c)) is not None
                and f['shape'] == base['shape']]
        right = [f for c in by_test[after['test_id']] if (f := frame(after, c)) is not None
                 and f['shape'] == base['shape']]
        if len(left) != 1 or len(right) != 1:
            skipped['source_frame_not_unique'] += 1
            output.append(row)
            continue
        row['witnesses'] = [{'pre': [oracle.encode_value(left[0]['value'])],
                             'arg': [oracle.encode_value(after_input)],
                             'after': oracle.encode_value(right[0]['value']), 'observe': 0,
                             'source_before': copy.deepcopy(before['span']),
                             'source_after': copy.deepcopy(after['span']),
                             'source_capsule_ids': [left[0]['capsule_id'], right[0]['capsule_id']],
                             'evidence': 'same_source_test_prefix_with_input_and_whole_expected_holes',
                             'limitations': 'Source examples constrain a relation; they do not prove applicability, purity, or its universal validity.'}]
        output.append(row)
    return {'candidates': output, 'attached': sum(bool(c.get('witnesses')) for c in output),
            'skipped': dict(skipped)}
