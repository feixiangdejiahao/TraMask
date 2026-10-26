"""Open helper-call instances, isolated from the frozen literal-only adapter.

Structural extraction and candidate format mirror v1; source argument closure
is replaced by actual lexical environments plus output origin-binding checks.
"""
from collections import Counter
from anchor_retrieval.syntax import CALLS, Source, walk
from experimental.generic_v2.bindings import _Index, analyze_bindings
from experimental.generic_v2.generate import _binding_labels, _refine, _roles
from experimental.generic_v3.alignment import align_analogy
from experimental.assertion_instances.core import _id, _span, _contains, _one_statement_tree, _helper_binding_reason
from generic_composition.corpus import source_text
from generic_composition.terms import BudgetExceeded, render, subterms
from .environment import collect, corresponding, check_output


def extract(corpus, *, max_instances=4096, max_nodes=1500):
    """Return private instance records plus explicit unsupported reasons.

    ``tree`` is a SourceTerm for composition, not JSON; ``helper_assertions`` and
    ``ports`` retain JSON source evidence from the existing corpus. Instance IDs
    distinguish calls even when A/B/C have exactly the same parent test ID.
    """
    if type(max_instances) is not int or max_instances < 1:
        raise ValueError('max_instances must be positive')
    cache, records, rejected, skipped, seen = {}, [], [], Counter(), set()
    capsules = sorted(corpus['capsules'], key=lambda c: (
        c.get('retrieval_rank') or 99999, c['test_id'], c['assertion_span']['start_byte']))
    for capsule in capsules:
        mappings = capsule.get('helper_assertions', [])
        if not mappings:
            continue
        test = corpus['tests'][capsule['test_id']]
        position = capsule['assertion_span']
        location = (test['id'], position['start_byte'], position['end_byte'])
        if location in seen:
            continue
        seen.add(location)

        def reject(reason):
            skipped[reason] += 1
            rejected.append({'capsule_id': capsule['id'], 'parent_test_id': test['id'],
                             'span': position, 'reason': reason})

        if len(records) >= max_instances:
            reject('instance_budget')
            continue
        metadata = corpus['sources'][position['path']]
        if not metadata.get('complete_file', True) or metadata.get('parse_error'):
            reject('incomplete_or_unparseable_source')
            continue
        if test.get('parameterization_status', 'none_detected') != 'none_detected':
            reject('parent_parameter_rows_require_instantiation')
            continue
        if any(m.get('binding_status') != 'resolved' for m in mappings):
            reject('helper_argument_binding_unknown')
            continue
        if position['path'] not in cache:
            source = Source(position['path'], metadata['code'], corpus['language'])
            nodes = {}
            for node in walk(source.root):
                nodes.setdefault((node.start_byte, node.end_byte), []).append(node)
            cache[position['path']] = source, nodes, _Index(source)
        source, nodes, bindings = cache[position['path']]
        call = next((n for n in nodes.get((position['start_byte'], position['end_byte']), [])
                     if n.type in CALLS), None)
        statement = call.parent if call is not None else None
        if statement is None or statement.type != 'expression_statement' or statement.named_children != [call]:
            reject('not_a_standalone_expression_statement')
            continue
        body_span = test['body_span']
        body = next((n for n in nodes.get((body_span['start_byte'], body_span['end_byte']), [])
                     if n.type in {'block', 'statement_block'}), None)
        parent = statement.parent
        if parent is not None and parent.type == 'statement_list':
            parent = parent.parent  # Transparent Go grammar node, not control flow.
        if body is None or parent != body:
            reject('not_a_direct_parent_test_statement')
            continue
        helper_reason = _helper_binding_reason(source, call, test, mappings, bindings)
        if helper_reason:
            reject(helper_reason)
            continue
        try:
            tree, original = _one_statement_tree(source, statement, max_nodes)
        except BudgetExceeded:
            reject('instance_node_budget')
            continue
        ports = []
        for mapping in mappings:
            observed = {b['parameter'] for b in mapping['observed_parameter_origins']}
            expected = {b['parameter'] for b in mapping['expected_parameter_origins']}
            for bound in mapping['argument_bindings']:
                roles = [role for role, names in [('observed', observed), ('expected', expected)]
                         if bound['parameter'] in names]
                ports.append({'helper_id': mapping['helper_id'], 'helper_assertion_span': mapping['assertion_span'],
                              'parameter': bound['parameter'], 'slot': bound['slot'], 'keyword': bound.get('keyword'),
                              'roles': roles or ['context'], 'actual': bound['actual']})
        role_map = {}
        for path, term in subterms(tree.term, max_nodes=max_nodes):
            if term.kind.endswith("identifier"):
                continue
            span = tree.spans[path]
            roles = {(role, port['helper_id'], port['parameter']) for port in ports
                     if _contains(port['actual']['span'], span)
                     for role in port['roles'] if role != 'context'}
            if roles:
                role_map[path] = tuple(sorted(roles))
        scope = test['enclosing_scope_span']
        helper_ids = tuple(sorted({m['helper_id'] for m in mappings}))
        record = {'instance_id': _id('helper_assertion_instance', location, helper_ids),
                        'parent_test_id': test['id'], 'test': test, 'language': corpus['language'],
                        'span': _span(source, statement), 'call_span': _span(source, call),
                        'text': source.text(statement), 'tree': tree,
                        'capsule_ids': [capsule['id']], 'helper_ids': helper_ids,
                        'helper_assertions': mappings, 'ports': ports,
                        'bindings': {(0,) + p: label for p, label in
                                     _binding_labels(source, statement, original, test['parameters']).items()},
                        'literal_roles': role_map,
                        'group_key': (scope['path'], scope['start_byte'], scope['end_byte'],
                                      tuple(test['parameters']), helper_ids),
                        'unproved': ['helper_and_caller_parameter_effects', 'aliasing', 'oracle_applicability']}
        environment, error = collect(source, bindings, statement, tree, ports)
        if error:
            reject(error)
            continue
        record['environment'] = environment
        record['bindings'].update({tuple(row['path']): row['binding'] for row in environment['references']})
        records.append(record)
    return {'instances': records, 'unsupported': rejected, 'skipped': dict(skipped)}


def compose(corpus, A, B, C, *, max_nodes=1500, max_holes=32, refine=_refine,
            mechanical_cache=None, source_cache=None):
    """Use the existing v3 kernel and emit a replacement of C's statement only.

    This small adapter does not perform a new search. A driver may use the same
    ranked/budgeted triple enumeration over ``instance_id`` instead of test ID.
    """
    if len({r['instance_id'] for r in (A, B, C)}) != 3:
        return {'status': 'unsupported', 'reason': 'three_distinct_instances_required'}
    if A['group_key'] != B['group_key'] or A['group_key'] != C['group_key']:
        return {'status': 'unsupported', 'reason': 'different_helper_or_lexical_interface'}
    try:
        records = [refine(r, max_nodes) for r in (A, B, C)]
        records, pairs, error = corresponding(records)
        if error:
            return {'status': 'unsupported', 'reason': error}
        result = align_analogy(*(r['tree'] for r in records), roles=_roles(*records),
                               max_nodes=max_nodes, max_holes=max_holes)
    except BudgetExceeded:
        return {'status': 'unsupported', 'reason': 'instance_node_budget'}
    if result.status != 'hypothesis':
        return {'status': 'unsupported', 'reason': result.reason, 'provenance': result.provenance}
    lexical_check = check_output(corpus, C, result.output, result.output_roles, pairs)
    if lexical_check['status'] == 'invalid':
        return {'status': 'unsupported', 'reason': lexical_check['reason'], 'lexical_check': lexical_check}
    after = render(result.output)
    before = source_text(corpus, C['span'])
    mechanical_cache = {} if mechanical_cache is None else mechanical_cache
    source_cache = {} if source_cache is None else source_cache
    path = C['span']['path']
    if path not in source_cache:
        source_cache[path] = Source(path, corpus['sources'][path]['code'], corpus['language'])
    key = (C['parent_test_id'], C['span']['start_byte'], C['span']['end_byte'], after)
    if key not in mechanical_cache:
        mechanical_cache[key] = analyze_bindings(source_cache[path], corpus['language'], C['span']['start_byte'], after,
                                                end_byte=C['span']['end_byte'])
    mechanical = mechanical_cache[key]
    if mechanical['status'] == 'invalid':
        return {'status': 'unsupported', 'reason': 'mechanically_invalid_instance', 'binding_analysis': mechanical}
    triple = [r['instance_id'] for r in (A, B, C)]
    rid = _id('assertion_instance_analogy', triple)
    sources = {name: {'test_id': r['parent_test_id'], 'instance_id': r['instance_id'],
                      'span': r['span'], 'text': r['text']} for name, r in zip('ABC', (A, B, C))}
    candidate = {'id': _id(rid, after), 'base_test_id': C['parent_test_id'],
                 'source_test_ids': list(dict.fromkeys(r['parent_test_id'] for r in (A, B))),
                 'language': corpus['language'], 'kind': 'open_assertion_instance_analogy', 'rule_id': rid,
                 'imports': [], 'edits': [{'span': C['span'], 'before': before, 'after': after}],
                 'oracle': {'mode': 'transport_from_source', 'source_test_id': B['parent_test_id'],
                            'binding_source_test_id': C['parent_test_id'],
                            'assertion_ids': B['capsule_ids'], 'semantic_status': 'requires_admission'},
                 'provenance': dict(result.provenance, sources=sources,
                                    source_assertion_ports={name: r['ports'] for name, r in zip('ABC', (A, B, C))},
                                    binding_analysis=mechanical,
                                    lexical_check=lexical_check,
                                    binding_correspondences=list(pairs.values()),
                                    source_environments={name: r['environment'] for name, r in zip('ABC', (A, B, C))})}
    rule = {'id': rid, 'kind': candidate['kind'], 'before_span': A['span'], 'after_span': B['span'],
            'semantic_status': 'hypothesis_from_test_edit'}
    return {'status': 'hypothesis', 'candidate': candidate, 'rule': rule}
