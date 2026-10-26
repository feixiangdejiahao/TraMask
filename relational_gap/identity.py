"""Source-bound shared-identity witnesses at controllable input slots.

Only existing local references are reused. Constructors are never re-evaluated,
objects are never synthesized, and equal variable spelling across tests is not
an identity proof. Type/constructor matching proposes a compatible carrier;
the inserted reference itself establishes the intended shared evaluation.
"""
from __future__ import annotations

from collections import defaultdict

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import CALLS, FUNCTIONS, call_parts, walk
from prototypes import observation_projection as projection
from generic_composition.corpus import expression, span
from generic_composition.engine import stable_id


def shared_identity_witnesses(corpus, donors, sources, *, frontend=None, max_references=24, max_alternatives=16):
    """Yield source edits with declaration/phase evidence, without oracle claims."""
    donors = [donor for donor in donors if donor.get('free_identifiers')]
    if not donors:
        return
    index = Index(list(sources.values()), '')
    for test in (frontend or {}).get('tests', []):
        unit = index.units.get(test['id'])
        if unit is not None:
            for parameter in test.get('parameters', []):
                name = parameter.get('name')
                if name and parameter.get('type'):
                    if name not in unit.params:
                        unit.params.append(name)
                    unit.param_types.setdefault(name, parameter['type'].lstrip(':').strip())
    groups = defaultdict(list)
    for donor in donors:
        test_id = donor['test_id']
        unit = index.units.get(test_id)
        if unit is None:
            continue
        source = unit.source
        cache = getattr(source, '_relation_node_map', None)
        if cache is None:
            cache = defaultdict(list)
            for node in walk(source.root):
                cache[(node.start_byte, node.end_byte)].append(node)
            source._relation_node_map = cache
        nodes = [node for node in cache.get((donor['span']['start_byte'], donor['span']['end_byte']), [])
                 if node.type == donor['kind']]
        if not nodes:
            continue
        nested = FUNCTIONS | {'arrow_function', 'function_expression', 'func_literal', 'lambda',
                              'list_comprehension', 'set_comprehension', 'dictionary_comprehension', 'generator_expression'}
        if any(node.type in nested for node in walk(nodes[0])):
            continue
        for reference in projection._reads(nodes[0]):
            if reference.type != 'identifier':
                continue
            fact = _fact(index, unit, reference)
            if fact is None:
                continue
            for port in donor['aligned_ports']:
                call = port['call_span']
                groups[(test_id, call['path'], call['start_byte'], call['end_byte'])].append(
                    {'reference': reference, 'fact': fact, 'donor': donor, 'port': port})
    ordered = sorted(groups.items(), key=lambda pair: (
        corpus['tests'][pair[0][0]].get('retrieval_rank') or 10**9, pair[0]))
    for key, members in ordered:
        test_id = key[0]
        unit = index.units[test_id]
        source = unit.source
        unique = {}
        for member in members:
            reference = member['reference']
            unique.setdefault((reference.start_byte, reference.end_byte), member)
        members = [unique[key] for key in sorted(unique)][:max_references]
        for target in members:
            alternatives = 0
            for origin in members:
                original_node, target_node = origin['reference'], target['reference']
                name = source.text(original_node)
                if name == source.text(target_node) or origin['fact']['token'] == target['fact']['token']:
                    continue  # The source already uses one binding/evaluation.
                if not projection._match(origin['fact'], target['fact']):
                    continue
                # An alias read elsewhere in setup can be stale after a rebind.
                # Verify the introduced name denotes that same source value at
                # the edit site, not just at the donor's old position.
                visible = _fact(index, unit, target_node, name=name)
                if visible is None or visible['token'] != origin['fact']['token']:
                    continue
                replacement = expression(source, original_node)
                replacement.update(id=stable_id('identity-reference', test_id, replacement['span']), test_id=test_id)
                edited = expression(source, target_node)
                edited.update(test_id=test_id, oracle_dependency=target['donor'].get('oracle_dependency', False))
                yield {'target': edited, 'after': name, 'origins': [replacement],
                       'relation': {'domain': 'shared_identity', 'cell': 'same_existing_value',
                                    'call_span': target['port']['call_span'],
                                    'source_reference_span': replacement['span'], 'target_reference_span': edited['span'],
                                    'source_argument_slot': origin['port']['argument_slot'],
                                    'target_argument_slot': target['port']['argument_slot'],
                                    'source_value_token': list(origin['fact']['token']),
                                    'replaced_value_token': list(target['fact']['token']),
                                    'types': sorted(set(origin['fact']['types']) & set(target['fact']['types'])),
                                    'constructor_origins': sorted(set(origin['fact']['origins']) & set(target['fact']['origins'])),
                                    'carrier_compatibility': [origin['fact']['precision'], target['fact']['precision']],
                                    'binding_precision': 'same_existing_lexical_value_at_edit_position',
                                    'phase': 'original_input_construction_and_call_phase',
                                    'runtime_obligation': 'confirm_identity_at_call_and_execute_original_observation'}}
                alternatives += 1
                if alternatives >= max_alternatives:
                    break


def _fact(index, unit, node, *, name=None, seen=()):
    """Use proven bindings where possible; source producer syntax stays unknown."""
    source = unit.source
    if name is None:
        name = source.text(node)
    if name in seen:
        return None
    fact = projection._object_fact(index, unit, node, name=name)
    if fact:
        return dict(fact, precision='source_constructor_or_type')
    if name in unit.params and unit.param_types.get(name):
        return {'token': ('parameter', unit.id, name), 'types': (unit.param_types[name],), 'origins': (),
                'precision': 'declared_formal_type'}
    rhs = projection._binding_rhs(unit, name, node)
    if rhs is None:
        return None
    if rhs.type == 'identifier':
        return _fact(index, unit, rhs, name=source.text(rhs), seen=(*seen, name))
    if rhs.type not in CALLS:
        return None
    function, _ = call_parts(rhs)
    if function is None:
        return None
    # A same-scope unresolved producer can still support a hypothesis. It is
    # not upgraded to resolved type equality merely because spellings match.
    producer = source.path + '::' + unit.id + '::' + source.text(function)
    return {'token': ('source_call', rhs.start_byte, rhs.end_byte), 'types': (), 'origins': (producer,),
            'precision': 'same_source_producer_syntax; return_type_unknown'}
