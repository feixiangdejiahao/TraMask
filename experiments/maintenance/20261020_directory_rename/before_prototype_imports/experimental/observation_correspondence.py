"""Source identity for an assertion whose actual input is edited in place.

This establishes correspondence, never oracle correctness or executability.
No statement ordinal, variable spelling, target or model answer is consulted.
"""
from __future__ import annotations

from anchor_retrieval.syntax import Source, walk
from experimental.modified_observation_impact import map_unchanged_span


def enclosing_span(extent, changes):
    """Map half-open UTF-8 boundaries through edits wholly inside an extent.

    An edit crossing either boundary is unknown. Insertions at the start
    precede the old extent; insertions at the end follow it.
    """
    start, end = extent['start_byte'], extent['end_byte']
    before_delta = inside_delta = 0
    relevant = sorted((c for c in changes if c['original_span']['path'] == extent['path']),
                      key=lambda c: (c['original_span']['start_byte'], c['original_span']['end_byte']))
    previous = -1
    for change in relevant:
        old = change['original_span']; left, right = old['start_byte'], old['end_byte']
        if left < previous or right < left or right - left != len(change['before'].encode()):
            return None
        previous = right
        delta = len(change['after'].encode()) - (right - left)
        if right <= start:
            before_delta += delta
        elif left >= end:
            continue
        elif left < start or right > end:
            return None
        else:
            inside_delta += delta
    return dict(path=extent['path'], start_byte=start + before_delta,
                end_byte=end + before_delta + inside_delta)


def _contains(outer, inner):
    return (outer['path'] == inner['path']
            and outer['start_byte'] <= inner['start_byte'] <= inner['end_byte'] <= outer['end_byte'])


def _bytes(source, extent):
    return source.data[extent['start_byte']:extent['end_byte']]


def _node(source, extent):
    matches = [node for node in walk(source.root)
               if node.start_byte == extent['start_byte'] and node.end_byte == extent['end_byte']]
    # Same-span expression wrappers have distinct types. Keep all types to
    # validate the old statement rather than picking an arbitrary wrapper.
    return {node.type for node in matches}


def correspond(original: Source, modified: Source, observation, changes):
    """Return transported spans or an explicit bounded source unknown.

    A changed assertion qualifies only if edits occur inside its actual-value
    expression, its surrounding statement bytes are identical, and its new
    statement and actual spans still denote parsed AST nodes. An unchanged
    expectation in a changed context may still be wrong: review is required.
    """
    old = observation.get('assertion_span') or observation['span']
    if old['path'] != original.path or modified.path != original.path:
        return dict(status='unknown', reason='observation_source_path_mismatch')
    unchanged = map_unchanged_span(old, changes)
    if unchanged is not None and _bytes(original, old) == _bytes(modified, unchanged):
        result = dict(status='corresponding', basis='unchanged_statement_bytes', span=unchanged)
        for field in ('observed', 'expected'):
            extent = (observation.get(field) or {}).get('span')
            if extent is not None:
                result['actual_span' if field == 'observed' else 'expected_span'] = map_unchanged_span(extent, changes)
        return result
    actual = (observation.get('observed') or {}).get('span')
    if actual is None or not _contains(old, actual) or actual['start_byte'] == actual['end_byte']:
        return dict(status='unknown', reason='original_actual_span_unavailable')
    touched = []
    for change in changes:
        edit = change['original_span']
        if edit['path'] != old['path']:
            continue
        left, right = edit['start_byte'], edit['end_byte']
        intersects = (left < old['end_byte'] and old['start_byte'] < right
                      or left == right and old['start_byte'] < left < old['end_byte'])
        if not intersects:
            continue
        if (change.get('role') == 'semantic_expected' or not _contains(actual, edit)
                or left == right and left in {actual['start_byte'], actual['end_byte']}):
            return dict(status='unknown', reason='edit_not_strictly_in_actual_expression')
        touched.append(change)
    if not touched:
        return dict(status='unknown', reason='statement_bytes_changed_without_actual_edit')
    current, current_actual = enclosing_span(old, changes), enclosing_span(actual, changes)
    if current is None or current_actual is None or not _contains(current, current_actual):
        return dict(status='unknown', reason='crossing_observation_edit_boundary')
    if original.root.has_error or modified.root.has_error:
        return dict(status='unknown', reason='observation_source_parse_error')
    expected = (observation.get('expected') or {}).get('span')
    # Frontends can retain an entire composite predicate as the observation.
    # Its comparator/expectation is then inside the alleged actual span. Such
    # a span cannot certify checker preservation merely by its outer bytes.
    compound = {'comparison_operator', 'boolean_operator', 'not_operator',
                'unary_operator', 'binary_expression', 'unary_expression',
                'conditional_expression', 'ternary_expression'}
    if expected is None and _node(original, actual) & compound:
        return dict(status='unknown', reason='actual_and_checker_roles_not_separated')
    if not (_node(original, old) & _node(modified, current)) or not _node(modified, current_actual):
        return dict(status='unknown', reason='modified_observation_ast_identity_unknown')
    prefix = original.data[old['start_byte']:actual['start_byte']]
    suffix = original.data[actual['end_byte']:old['end_byte']]
    if (prefix != modified.data[current['start_byte']:current_actual['start_byte']]
            or suffix != modified.data[current_actual['end_byte']:current['end_byte']]):
        return dict(status='unknown', reason='observation_checker_bytes_changed')
    mapped_expected = None
    if expected is not None:
        mapped_expected = map_unchanged_span(expected, changes)
        if (mapped_expected is None or _bytes(original, expected) != _bytes(modified, mapped_expected)
                or not _contains(current, mapped_expected)):
            return dict(status='unknown', reason='observation_expectation_bytes_changed')
    return dict(status='corresponding', basis='actual_edit_with_unchanged_checker_bytes',
                span=current, actual_span=current_actual,
                expected_span=mapped_expected,
                oracle_status='original_expectation_requires_semantic_review')
