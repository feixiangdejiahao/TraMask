"""Field-value replacement candidates, grouped by closed literal syntax.

The destination key is never replaced. Grouping equivalent source spellings
collects provenance; applying one group at two destinations still evaluates
two literal expressions. Candidate ranking establishes no type or API contract.
"""
from collections import defaultdict, deque
import hashlib
import json
from pathlib import PurePosixPath

from .alignment import Term, anti_unify, term_key
from .behavior import FRESH
from .evidence import CALLS, FUNCTION_NODES, IDENTS, MEMBERS, STRINGS
from .regions import COMMENTS, FIELDS, OBJECTS, SEQUENCES


PRIMITIVES = {'integer', 'int_literal', 'float', 'float_literal', 'number',
              'true', 'false', 'none', 'null', 'nil', 'boolean_literal'}
UNARY = {'unary_operator', 'unary_expression'}
PARENTHESES = {'parenthesized_expression'}
CATEGORIES = ('primitive', 'object', 'sequence')


def _value_region(regions, region):
    """Resolve a field's complete value using its parser-owned field roles."""
    if region['kind'] != 'field':
        return region
    document, node = regions._nodes[region['id']]
    value = node.child_by_field_name('value')
    if value is None:
        raise ValueError('A replacement field must have an explicit value: ' + region['id'])
    return regions._node_regions[document, value.id]


def _syntax(regions, region):
    document_id, root = regions._nodes[region['id']]
    document = regions._documents[document_id]
    raw = document['raw']
    suffix = PurePosixPath(regions.graph.source['path']).suffix
    language = document['language'] or ('python' if suffix == '.py' else
                                       'go' if suffix == '.go' else
                                       'rust' if suffix == '.rs' else 'javascript')
    fresh = FRESH['.py'] if language == 'python' else FRESH['.js'] if language in {'javascript', 'json'} else set()
    terms, shapes = {}, {}
    unknowns, free_bindings = set(), set()
    allocations, node_count = [], 0
    pending = [(root, False)]
    while pending:
        node, ready = pending.pop()
        text = raw[node.start_byte:node.end_byte].decode()
        children = [child for child in node.children if child.type not in COMMENTS]
        literal = node.type in PRIMITIVES | STRINGS
        if children and not literal and not ready:
            pending.append((node, True))
            pending.extend((child, False) for child in reversed(children))
            continue
        span = tuple(regions._mapped_span(document, node.start_byte, node.end_byte))
        node_count += 1
        parent = node.parent
        fixed_key = (language != 'python' and parent is not None and parent.type in FIELDS
                     and node in [parent.child_by_field_name(name) for name in ('key', 'field', 'name')]
                     and node.type in IDENTS)
        if node.is_named:
            if node.type in STRINGS:
                descendants = list(node.named_children)
                while descendants:
                    child = descendants.pop()
                    if child.type in {'interpolation', 'template_substitution'}:
                        unknowns.add('interpolated_value')
                    descendants.extend(child.named_children)
            elif node.type in IDENTS and not fixed_key:
                unknowns.add('free_binding')
                free_bindings.add(text)
            elif node.type in CALLS:
                unknowns.add('call_in_value')
            elif node.type in MEMBERS:
                unknowns.add('dynamic_attribute_access')
            elif node.type in FUNCTION_NODES:
                unknowns.add('callable_or_scope_value')
            elif node.type in {'computed_property_name', 'subscript', 'subscript_expression'}:
                unknowns.add('dynamic_key_or_index')
            elif node.type in {'spread_element', 'dictionary_splat', 'list_splat'}:
                unknowns.add('expanded_value')
            elif node.type in UNARY:
                operator = ''.join(raw[c.start_byte:c.end_byte].decode() for c in node.children if not c.is_named)
                if operator not in {'+', '-'} or len(node.named_children) != 1 or node.named_children[0].type not in PRIMITIVES:
                    unknowns.add('nonliteral_unary_expression')
            elif node.type not in PRIMITIVES | OBJECTS | SEQUENCES | FIELDS | PARENTHESES and not fixed_key:
                unknowns.add('expression_is_not_a_supported_literal')
        if node.type in fresh:
            allocations.append(list(span))
        if literal or not children:
            terms[node.id] = Term(node.type, text, span)
            shapes[node.id] = Term(node.type, '*' if literal else text, span)
        else:
            parts, shape_parts, counts = [], [], defaultdict(int)
            for position, child in enumerate(node.children):
                if child.type in COMMENTS:
                    continue
                role = node.field_name_for_child(position) or ('named' if child.is_named else child.type)
                label = role + ':' + str(counts[role])
                counts[role] += 1
                parts.append((label, terms[child.id]))
                shape_parts.append((label, shapes[child.id]))
            terms[node.id] = Term(node.type, '', span, tuple(parts))
            shapes[node.id] = Term(node.type, '', span, tuple(shape_parts))
    category = ('object' if root.type in OBJECTS else 'sequence' if root.type in SEQUENCES else
                'primitive' if root.type in PRIMITIVES | STRINGS | UNARY else 'expression')
    return {'term': terms[root.id], 'shape': shapes[root.id], 'language': language,
            'category': category, 'closed': not unknowns, 'unknowns': sorted(unknowns),
            'free_bindings': sorted(free_bindings), 'node_count': node_count,
            'fresh_allocation_ranges': sorted(allocations), 'document': document_id}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def value_candidates(index, source, selection):
    """Return separately ranked recipes for one field or its complete value.

    Coordinates use the same source bytes as ``RegionAlignmentIndex``. Closed
    literals merge only when language, ordered AST structure and all literal
    spellings agree. Open expressions stay separate per source occurrence.
    ``origins`` retains both field and literal region provenance where present.
    """
    if len(selection['selected']) != 1:
        raise ValueError('Value recipes require one field or its complete value.')
    regions = index.regions[source]
    selected = selection['selected'][0]
    if selected['kind'] == 'field':
        destination_field = selected
    elif selected['role'] == 'field_value':
        destination_field = regions.by_id[selected['parent']]
    else:
        raise ValueError('The selected region is not a field or its complete value.')
    destination = _value_region(regions, destination_field)
    original = _syntax(regions, destination)
    original_key = term_key(original['term'])
    grouped = {}
    syntax_cache = {}
    for key, region in sorted(index.pool.items(), key=lambda item: (
            item[0][0], tuple(item[1]['range']), item[0][1])):
        if region['kind'] not in {'field', 'object_literal', 'sequence_literal', 'composite_literal'}:
            continue
        candidate_regions = index.regions[key[0]]
        value = _value_region(candidate_regions, region)
        if key[0] == source and value['range'] == destination['range']:
            continue
        occurrence = key[0], value['id']
        if occurrence not in syntax_cache:
            syntax_cache[occurrence] = _syntax(candidate_regions, value)
        syntax = syntax_cache[occurrence]
        full_key = term_key(syntax['term'])
        group = (('closed_literal', syntax['language'], full_key) if syntax['closed'] else
                 ('source_occurrence', *occurrence))
        origin = {'key': list(key), 'range': value['range']}
        if group in grouped:
            grouped[group]['origins'].append(origin)
            continue
        difference = anti_unify(original['term'], syntax['term'])
        structure = anti_unify(original['shape'], syntax['shape'])
        edit_bytes = sum(span[1] - span[0] for hole in difference['holes']
                         for span in (hole['left'], hole['right']) if span is not None)
        unknowns = set(syntax['unknowns']) | set(region['unknowns'])
        unknowns.update({'destination_type_and_contract_not_validated',
                         'field_spelling_does_not_establish_semantic_role'})
        if syntax['document'] != 'native' or original['document'] != 'native':
            unknowns.add('embedded_literal_source_encoding_not_validated')
        row = {'destination_source': source, 'destination_range': destination['range'],
               'destination_field_range': destination_field['range'], 'key_preserved': True,
               'source': key[0], 'replacement_range': value['range'], 'origins': [origin],
               'category': syntax['category'], 'closed': syntax['closed'],
               'term_key': _digest([syntax['language'], full_key]),
               'shape': _digest([syntax['language'], term_key(syntax['shape'])]),
               'syntax_language': syntax['language'], 'node_count': syntax['node_count'],
               'changes_value': original['language'] != syntax['language'] or original_key != full_key,
               'structural_difference_count': len(structure['holes']),
               'difference_count': len(difference['holes']), 'edit_bytes': edit_bytes,
               'fresh_allocation_count': len(syntax['fresh_allocation_ranges']) if syntax['closed'] else None,
               'allocation_syntax_count': len(syntax['fresh_allocation_ranges']),
               'fresh_allocation_ranges': syntax['fresh_allocation_ranges'],
               'instantiation': 'evaluate_literal_separately_at_each_destination',
               'grouping': 'closed_literal_structure_and_values' if syntax['closed'] else 'same_source_occurrence_only',
               'free_bindings': syntax['free_bindings'], 'unknowns': sorted(unknowns)}
        grouped[group] = row
    queues = defaultdict(list)
    for row in grouped.values():
        row['origins'].sort(key=lambda origin: (origin['key'][0], tuple(origin['range']), origin['key'][1]))
        row['origin_occurrence_count'] = len({(origin['key'][0], tuple(origin['range'])) for origin in row['origins']})
        queues[row['category']].append(row)
    for category in queues:
        queues[category] = deque(sorted(queues[category], key=lambda row: (
            not row['closed'], not row['changes_value'], row['structural_difference_count'],
            row['edit_bytes'], row['node_count'], row['source'], tuple(row['replacement_range']), row['term_key'])))
    result = []
    while any(queues[category] for category in CATEGORIES):
        for category in CATEGORIES:
            if queues[category]:
                row = queues[category].popleft()
                row['rank'] = len(result) + 1
                result.append(row)
    for row in queues['expression']:
        row['rank'] = len(result) + 1
        result.append(row)
    return result
