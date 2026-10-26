"""Materialize coupled literal pytest rows without duplicating parameter reads.

This is a framework syntax adapter, not an oracle or subject-library model.
Each parameter gets one assignment before the unchanged body, preserving uses
of that object within the test. The emitted decorator selects one source row.
"""
from collections import Counter

from anchor_retrieval.syntax import child, walk
from generic_composition.terms import BudgetExceeded, SourceTerm, Span, Term, from_source, render, subterms


def instantiate(record, source, body_node, *, max_nodes):
    test = record['test']
    rows = test.get('parameter_rows', [])
    if source.language != 'python' or not rows or len({r['table'] for r in rows}) != 1:
        return [], Counter({'parameter_table_form_unsupported': 1})
    # Rebinding/shadowing parameters needs flow-sensitive binding analysis.
    if any(n.type in {'function_definition', 'lambda', 'class_definition',
                      'for_statement', 'list_comprehension', 'set_comprehension',
                      'dictionary_comprehension', 'generator_expression'}
           for n in walk(body_node) if n != body_node):
        return [], Counter({'parameter_nested_binding_unsupported': 1})
    names = set(rows[0]['bindings'])
    for node in walk(body_node):
        if node.type in {'assignment', 'augmented_assignment', 'named_expression'}:
            target = child(node, 'left', 'name')
            if target is not None and any(n.type == 'identifier' and source.text(n) in names
                                          for n in walk(target)):
                return [], Counter({'parameter_rebinding_unsupported': 1})
    index = {(n.start_byte, n.end_byte): n for n in walk(source.root)}
    body_start = body_node.start_byte
    line_start = source.data.rfind(b'\n', 0, body_start) + 1
    indent = source.data[line_start:body_start].decode()
    output, skipped = [], Counter()
    for row in rows:
        if set(row['binding_sources']) != names:
            skipped['parameter_cell_source_missing'] += 1
            continue
        row_span = row['row_span']
        row_node = index.get((row_span['start_byte'], row_span['end_byte']))
        table = row_node.parent if row_node is not None else None
        if table is None or table.type not in {'list', 'tuple'} or table.start_byte >= test['definition_span']['start_byte']:
            skipped['parameter_table_source_unsupported'] += 1
            continue
        if table.parent is not None and any(
                arg.type == 'keyword_argument' and source.text(child(arg, 'name')) == 'indirect'
                and source.text(child(arg, 'value')) != 'False' for arg in table.parent.named_children):
            skipped['parameter_indirect_fixture_unsupported'] += 1
            continue
        table_span = dict(row_span, start_byte=table.start_byte, end_byte=table.end_byte)
        extra_edits = [{'span': table_span, 'before': source.text(table),
                        'after': '[' + source.text(row_node) + ']'}]
        # Literal explicit IDs must shrink along with the row table.
        ids_ok = True
        if table.parent is not None:
            for arg in table.parent.named_children:
                if arg.type == 'keyword_argument' and source.text(child(arg, 'name')) == 'ids':
                    value = child(arg, 'value')
                    if value is None or value.type not in {'list', 'tuple'}:
                        ids_ok = False
                        break
                    cells = [n for n in value.named_children if n.type != 'comment']
                    if row['row'] >= len(cells):
                        ids_ok = False
                        break
                    extra_edits.append({'span': dict(row_span, start_byte=value.start_byte, end_byte=value.end_byte),
                                        'before': source.text(value), 'after': '[' + source.text(cells[row['row']]) + ']'})
        if not ids_ok:
            skipped['parameter_ids_unsupported'] += 1
            continue
        children, spans, bindings, roles = [], {(): record['tree'].spans[()]}, {}, {}
        try:
            for slot, (name, expression) in enumerate(row['binding_sources'].items()):
                if not expression.get('literal_known'):
                    raise ValueError('parameter_nonliteral_cell')
                position = expression['span']
                cell_node = index.get((position['start_byte'], position['end_byte']))
                if cell_node is None:
                    raise ValueError('parameter_cell_source_missing')
                cell = from_source(source, cell_node, max_nodes=max_nodes)
                assignment = Term('expression_statement', children=(Term('assignment', children=(
                    Term('identifier', name), Term('#trivia', ' '), Term('=', '='),
                    Term('#trivia', ' '), cell.term)),))
                offset = len(children)
                children.extend((assignment, Term('#trivia', '\n' + indent)))
                default = Span(position['start_byte'], position['end_byte'])
                for path, _ in subterms(assignment, max_nodes=max_nodes):
                    spans[(offset,) + path] = default
                spans[(offset + 1,)] = default
                bindings[(offset, 0, 0)] = ('parameter', test['parameters'].index(name))
                for path, _ in subterms(cell.term, max_nodes=max_nodes):
                    location = (offset, 0, 4) + path
                    spans[location] = cell.spans[path]
                    roles[location] = (('row_parameter', slot),)
            shift = len(children)
            children.extend(record['tree'].term.children)
            for path, span in record['tree'].spans.items():
                if path:
                    spans[(path[0] + shift,) + path[1:]] = span
            for source_map, destination in ((record['bindings'], bindings), (record['literal_roles'], roles)):
                destination.update({(p[0] + shift,) + p[1:]: role for p, role in source_map.items() if p})
            tree = SourceTerm(Term(record['tree'].term.kind, children=tuple(children)), spans, source.path)
            list(subterms(tree.term, max_nodes=max_nodes))
        except (BudgetExceeded, ValueError) as exc:
            skipped['parameter_row_node_budget' if isinstance(exc, BudgetExceeded) else str(exc)] += 1
            continue
        output.append(dict(record, instance_id=f"{test['id']}:row:{row['table']}:{row['row']}",
                           tree=tree, text=render(tree.term), bindings=bindings, literal_roles=roles,
                           extra_edits=extra_edits,
                           instantiation={'table': row['table'], 'row': row['row'], 'row_span': row_span,
                                          'bindings': row['binding_sources'],
                                          'mode': 'one_assignment_per_parameter_then_original_body'}))
    return output, skipped
