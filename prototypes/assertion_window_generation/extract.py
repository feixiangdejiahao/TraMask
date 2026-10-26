"""Source windows ending at an existing assertion, using local may-dependence.

A window includes every original direct statement between its first recorded
dependency and its assertion. It is not a sound executable program slice:
alias, global, fixture and helper effects may be absent from the existing graph.
"""
from collections import Counter
from types import SimpleNamespace

from anchor_retrieval.syntax import CALLS, Source, child, walk
from prototypes.helper_assertion_instances_v01.core import _helper_binding_reason, _id, _span
from prototypes.test_edit_analogy_v02.bindings import _Index
from prototypes.test_edit_analogy_v02.generate import _binding_labels, _literal_roles, _producers, _scope
from prototypes.unified_view_test_analogy_v05.views import _frontier
from generic_composition.corpus import _identifier_reads
from generic_composition.terms import BudgetExceeded, SourceTerm, Span, Term, from_source, render, subterms


def _inside(outer, inner):
    return outer['start_byte'] <= inner['start_byte'] <= inner['end_byte'] <= outer['end_byte']


def _window_tree(source, statements, max_nodes):
    start, end = statements[0].start_byte, statements[-1].end_byte
    children, positions, cursor = [], {(): Span(start, end)}, start
    for statement in statements:
        if cursor < statement.start_byte:
            positions[(len(children),)] = Span(cursor, statement.start_byte)
            children.append(Term('#trivia', source.data[cursor:statement.start_byte].decode()))
        converted = from_source(source, statement, max_nodes=max_nodes)
        positions.update({(len(children),) + path: span for path, span in converted.spans.items()})
        children.append(converted.term)
        cursor = statement.end_byte
    term = Term('module', children=tuple(children))
    list(subterms(term, max_nodes=max_nodes))
    text = source.data[start:end].decode()
    assert render(term) == text
    return SourceTerm(term, positions, source.path, text)


def _definition_values(source, read, index, body):
    """Follow the lexical variable, retaining conditional writes as may defs."""
    name = source.text(read)
    binding, _, _ = index.resolve(name, read)
    if binding is None or binding.kind not in {'local', 'var', 'parameter'}:
        return []
    scope = binding.scope
    assignments = {'assignment', 'augmented_assignment', 'named_expression', 'short_var_declaration',
                   'var_spec', 'const_spec', 'variable_declarator', 'assignment_expression', 'assignment_statement'}
    conditional = {'if_statement', 'for_statement', 'while_statement', 'for_in_statement',
                   'switch_statement', 'expression_switch_statement', 'try_statement'}
    writers = [b.node for b in scope.bindings.get(name, []) if b.available_from <= read.start_byte]
    for written_name, node, position in index.writes:
        target, _, _ = index.resolve(written_name, node)
        if written_name == name and position < read.start_byte and target is not None and target.scope is scope:
            writers.append(node)
    candidates = {}
    for writer in writers:
        node = writer
        while node is not None and node != body and node.type not in assignments:
            node = node.parent
        if node is None or node == body or node.end_byte > read.start_byte:
            continue
        value = child(node, 'right', 'value')
        if value is None or not body.start_byte <= node.start_byte < node.end_byte <= body.end_byte:
            continue
        may = node.type == 'augmented_assignment'
        ancestor = node.parent
        while ancestor is not None and ancestor != scope.node:
            may |= ancestor.type in conditional
            ancestor = ancestor.parent
        candidates[node.start_byte] = value, may
    result = []
    for _, (value, may) in sorted(candidates.items(), reverse=True):
        result.append(value)
        if not may:
            break
    return result


def _expected_definitions(source, expressions, body, nodes, index):
    """Expected-side lexical closure; it does not summarize heap/call effects."""
    pending = [nodes.get((e['span']['start_byte'], e['span']['end_byte'])) for e in expressions]
    seen, positions = set(), []
    while pending:
        node = pending.pop()
        if node is None or (node.start_byte, node.end_byte) in seen:
            continue
        seen.add((node.start_byte, node.end_byte))
        positions.append(_span(source, node))
        names = _identifier_reads(source, node)
        for read in walk(node):
            if read.type == 'identifier' and source.text(read) in names:
                pending.extend(_definition_values(source, read, index, body))
    return positions


def _ports(capsule):
    result = []
    for helper in capsule.get('helper_assertions', []):
        observed = {b['parameter'] for b in helper['observed_parameter_origins']}
        expected = {b['parameter'] for b in helper['expected_parameter_origins']}
        for bound in helper['argument_bindings']:
            result.append({'helper_id': helper['helper_id'], 'helper_assertion_span': helper['assertion_span'],
                           'parameter': bound['parameter'], 'slot': bound['slot'], 'keyword': bound.get('keyword'),
                           'roles': [role for role, names in [('observed', observed), ('expected', expected)]
                                     if bound['parameter'] in names] or ['context'], 'actual': bound['actual']})
    if not result:
        for role, expression in [('observed', capsule.get('observed')), ('expected', capsule.get('expected'))]:
            if expression:
                result.append({'roles': [role], 'actual': expression})
    return result


def extract(corpus, *, max_instances=4096, max_nodes=1500):
    """Return assertion-window instance records for the existing analogy driver."""
    if any(type(n) is not int or n < 1 for n in (max_instances, max_nodes)):
        raise ValueError('Extraction budgets must be positive integers')
    records, rejected, skipped, cache, seen = [], [], Counter(), {}, set()
    capsules = sorted(corpus['capsules'], key=lambda c: (
        c.get('retrieval_rank') or 99999, c['test_id'], c['assertion_span']['start_byte'], c['id']))
    for capsule in capsules:
        test, anchor = corpus['tests'][capsule['test_id']], capsule['assertion_span']

        def reject(reason):
            skipped[reason] += 1
            rejected.append({'capsule_id': capsule['id'], 'parent_test_id': test['id'],
                             'span': anchor, 'reason': reason})

        if len(records) >= max_instances:
            reject('instance_budget')
            continue
        metadata = corpus['sources'][anchor['path']]
        if not metadata.get('complete_file', True) or metadata.get('parse_error'):
            reject('incomplete_or_unparseable_source')
            continue
        if test.get('parameterization_status', 'none_detected') != 'none_detected':
            reject('parent_parameter_rows_require_instantiation')
            continue
        if not test.get('enclosing_scope_span'):
            reject('missing_parent_scope')
            continue
        if anchor['path'] not in cache:
            source = Source(anchor['path'], metadata['code'], corpus['language'])
            by_span, bodies = {}, {}
            for node in walk(source.root):
                by_span[(node.start_byte, node.end_byte)] = node
                if node.type in {'block', 'statement_block'}:
                    bodies[(node.start_byte, node.end_byte)] = node
            cache[anchor['path']] = source, by_span, bodies, _Index(source)
        source, nodes, bodies, binding_index = cache[anchor['path']]
        pos = test['body_span']
        body = bodies.get((pos['start_byte'], pos['end_byte']))
        if body is None:
            reject('body_statement_list_unsupported')
            continue
        container = next((n for n in body.named_children if n.type == 'statement_list'), body)
        statements = [n for n in container.named_children if n.type != 'comment']
        target = next((i for i, stmt in enumerate(statements)
                       if stmt.start_byte <= anchor['start_byte'] and anchor['end_byte'] <= stmt.end_byte), None)
        if target is None:
            reject('assertion_not_in_direct_parent_statement')
            continue
        helpers = capsule.get('helper_assertions', [])
        if any(h.get('binding_status') != 'resolved' for h in helpers):
            reject('helper_argument_binding_unknown')
            continue
        if helpers:
            call = nodes.get((anchor['start_byte'], anchor['end_byte']))
            if call is None or call.type not in CALLS:
                reject('helper_call_node_missing')
                continue
            reason = _helper_binding_reason(source, call, test, helpers, binding_index)
            if reason:
                reject(reason)
                continue
        ports = _ports(capsule)
        expected = _expected_definitions(source, [p['actual'] for p in ports if 'expected' in p['roles']],
                                         body, nodes, binding_index)
        dependency_spans = [n for n in capsule['bindings']['slice_nodes']
                            if n['kind'] not in {'parameter', 'receiver', 'unknown', 'join'}] + expected
        required = {target}
        for i, stmt in enumerate(statements[:target + 1]):
            if any(stmt.start_byte <= s['start_byte'] <= s['end_byte'] <= stmt.end_byte for s in dependency_spans):
                required.add(i)
        first = min(required)
        selected = statements[first:target + 1]
        span = dict(_span(source, selected[0]), end_byte=selected[-1].end_byte,
                    end_line=selected[-1].end_point.row + 1)
        key = (test['id'], span['start_byte'], span['end_byte'], capsule['predicate'])
        if key in seen:
            skipped['duplicate_window'] += 1
            continue
        try:
            tree = _window_tree(source, selected, max_nodes)
        except BudgetExceeded:
            reject('instance_node_budget')
            continue
        # Restrict local declarations to the window. References to declarations
        # outside it remain open, rather than receiving a fresh local ordinal.
        window_node = SimpleNamespace(type='block', named_children=selected, start_byte=span['start_byte'],
                                      end_byte=span['end_byte'], parent=body.parent)
        labels = _binding_labels(source, window_node, tree, test['parameters'])
        producers = _producers([capsule])
        record = {'instance_id': _id('assertion_window', key), 'parent_test_id': test['id'], 'test': test,
                  'language': corpus['language'], 'span': span, 'anchor_span': anchor, 'call_span': anchor,
                  'text': render(tree.term), 'original_text': render(tree.term), 'tree': tree, 'bindings': labels,
                  'capsule_ids': [c['id'] for c in capsules if c['test_id'] == test['id'] and _inside(span, c['assertion_span'])],
                  'helper_ids': tuple(sorted({h['helper_id'] for h in helpers})), 'helper_assertions': helpers,
                  'ports': ports, 'producers': producers, 'observer_keys': _frontier(capsule),
                  'predicate': capsule['predicate'], 'group_key': (*_scope(test), capsule['predicate']),
                  'required_statement_indices': sorted(i - first for i in required),
                  'protected_gap_indices': [i - first for i in range(first, target + 1) if i not in required],
                  'statement_spans': [_span(source, s) for s in selected],
                  'dependency_precision': 'local_may_graph_plus_lexical_expected_may_definitions',
                  'unproved': ['alias_and_global_effects', 'fixture_and_helper_effects', 'dependency_completeness',
                               'external_bindings_and_capture', 'liveout_effects', 'oracle_applicability']}
        record['literal_roles'] = _literal_roles(record, corpus, [capsule])
        terms = dict(subterms(tree.term))
        record['literal_roles'] = {path: role for path, role in record['literal_roles'].items()
                                   if not terms[path].kind.endswith('identifier')}
        observed = capsule.get('observation_value_sources', [])
        for path, term in subterms(tree.term):
            if term.children or term.kind == '#trivia' or term.kind.endswith('identifier'):
                continue
            p = tree.spans[path]
            location = {'start_byte': p.start_byte, 'end_byte': p.end_byte}
            roles = [('expected_definition',)] if any(_inside(s, location) for s in expected) else []
            if any(_inside(s, location) for s in observed):
                roles.append(('observed_definition',))
            if roles:
                record['literal_roles'][path] = tuple(roles)
        records.append(record)
        seen.add(key)
    return {'instances': records, 'unsupported': rejected, 'skipped': dict(skipped)}
