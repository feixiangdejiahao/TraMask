"""Preserve unmatched target setup with explicit, independently named gaps.

This module aligns one direct statement list. It never flattens control flow,
infers an oracle, runs a program or proves effect commutativity. It adds empty
rendering syntax nodes, then invokes the unchanged test-edit analogy core.
"""
from dataclasses import dataclass, field
from functools import lru_cache

from experimental.generic_v21.analogy import analogy
from generic_composition.terms import BudgetExceeded, SourceTerm, Term, at, render, subterms


@dataclass(frozen=True)
class AlignmentResult:
    status: str
    output: Term | None = None
    provenance: dict = field(default_factory=dict)
    reason: str | None = None
    output_roles: dict = field(default_factory=dict, repr=False)


_LISTS = {'module', 'program', 'block', 'statement_block'}
_SEPARATORS = {'#trivia', 'comment', '{', '}', ';'}
_CALLS = {'call', 'call_expression'}


def _parts(source):
    if not isinstance(source, SourceTerm) or source.term.kind not in _LISTS:
        raise ValueError('expected_direct_statement_list_SourceTerm')
    items = []
    transparent = None
    for i, node in enumerate(source.term.children):
        if node.kind == 'statement_list':
            if transparent is not None:
                raise ValueError('multiple_transparent_statement_lists')
            transparent = (i, len(source.term.children) - i - 1, node.kind)
            items.extend(((i, j), child) for j, child in enumerate(node.children))
        else:
            items.append(((i,), node))
    children = tuple(node for _, node in items)
    starts = [i for i, node in enumerate(children) if node.kind not in _SEPARATORS]
    if not starts:
        raise ValueError('empty_statement_list')
    end = len(children)
    while end > starts[-1] and children[end - 1].kind == '}':
        end -= 1
    boundaries = [*starts, end]
    return {'items': items, 'transparent': transparent,
            'prefix': tuple(range(starts[0])), 'suffix': tuple(range(end, len(children))),
            'units': [tuple(range(a, b)) for a, b in zip(boundaries, boundaries[1:])],
            'statements': [children[i] for i in starts]}


def _key(statement):
    while statement.kind == 'expression_statement':
        meaningful = [c for c in statement.children if c.kind not in {'#trivia', ';'}]
        if len(meaningful) != 1:
            break
        statement = meaningful[0]
    # Direct language assertions stay anchors when their expected expression or
    # observed projection changes; their contents still undergo anti-unification.
    if statement.kind == 'assert_statement':
        return statement.kind, frozenset()
    calls = set()
    for _, node in subterms(statement):
        if node.kind in _CALLS:
            children = [c for c in node.children if c.kind != '#trivia']
            if children:
                calls.add(render(children[0]))
    return statement.kind, frozenset(calls)


def _unique_embedding(A, other, compatible):
    """Count monotone full embeddings up to two; never choose a greedy match."""
    @lru_cache(None)
    def solve(i, start):
        if i == len(A):
            return ((),)
        found = []
        for j in range(start, len(other) - (len(A) - i) + 1):
            if compatible(A[i], other[j]):
                for suffix in solve(i + 1, j + 1):
                    found.append((j,) + suffix)
                    if len(found) == 2:
                        return tuple(found)
        return tuple(found)
    return solve(0, 0)


def _augment(source, parts, mapping, role, order):
    original = tuple(node for _, node in parts['items'])
    children, path_map, occurrences, residual_slots = [], {}, [], {}

    def append(kind, indices):
        location = len(children)
        children.append(Term(kind, children=tuple(original[i] for i in indices)))
        for offset, old_index in enumerate(indices):
            for path, _ in subterms(original[old_index]):
                path_map[parts['items'][old_index][0] + path] = (location, offset) + path
        return location

    append('aligned_prefix', parts['prefix'])
    previous = -1
    for gap in range(len(mapping) + 1):
        following = mapping[gap] if gap < len(mapping) else len(parts['units'])
        unmatched = list(range(previous + 1, following))
        for side in order:
            present = unmatched if role == side else []
            indices = [child for statement in present for child in parts['units'][statement]]
            location = append(f'aligned_gap_{gap}_{side}', indices)
            if side == 'residual':
                residual_slots[gap] = location
            occurrences.extend({'statement': i, 'slot': location, 'role': side, 'gap': gap} for i in present)
        if gap < len(mapping):
            location = append(f'aligned_anchor_{gap}', parts['units'][following])
            occurrences.append({'statement': following, 'slot': location, 'role': 'anchor', 'anchor': gap})
            previous = following
    append('aligned_suffix', parts['suffix'])
    return Term('aligned_statement_list', children=tuple(children)), path_map, occurrences, residual_slots


def _restore(term, original, parts, labels):
    """Remove only the adapter nodes and restore transparent grammar wrapping."""
    children, mappings = [], {}
    for i, wrapper in enumerate(term.children):
        for j, node in enumerate(wrapper.children):
            offset = len(children)
            children.append(node)
            for path, _ in subterms(node):
                mappings[(i, j) + path] = (offset,) + path
    transparent = parts['transparent']
    if transparent is not None:
        prefix, suffix, kind = transparent
        end = len(children) - suffix
        output = Term(original.kind, children=(*children[:prefix],
            Term(kind, children=tuple(children[prefix:end])), *children[end:]))
        for path, mapped in list(mappings.items()):
            i, tail = mapped[0], mapped[1:]
            mappings[path] = ((i,) + tail if i < prefix else
                              (prefix, i - prefix) + tail if i < end else
                              (prefix + 1 + i - end,) + tail)
    else:
        output = Term(original.kind, original.atom, tuple(children))
    return output, {mappings[p]: label for p, label in labels.items() if p in mappings}


def _transport_roles(B, C, transfers):
    output = dict(B)
    for row in transfers:
        destination, origin = tuple(row['b_path']), tuple(row['c_paths'][0])
        output = {p: role for p, role in output.items() if p[:len(destination)] != destination}
        output.update({destination + p[len(origin):]: role for p, role in C.items() if p[:len(origin)] == origin})
    return output


def _aligned_local_roles(views, maps):
    """Rebase supplied unique-local identities onto aligned declaration sites.

    This consumes the caller's restricted binding labels; it does not resolve
    arbitrary names, properties, nested scopes or captures by spelling.
    """
    result = []
    declarations = {'assignment', 'short_var_declaration', 'variable_declarator', 'var_spec'}
    patterns = {'identifier', 'tuple', 'list', 'pattern_list', 'expression_list', 'tuple_pattern', 'list_pattern'}
    for source_index, (view, labels) in enumerate(zip(views, maps)):
        replacement = {}
        for path, node in subterms(view[0]):
            if node.kind not in declarations or not path:
                continue
            anchor_kind = view[0].children[path[0]].kind
            if not anchor_kind.startswith('aligned_anchor_'):
                continue
            target_index = next((i for i, child in enumerate(node.children) if child.kind != '#trivia'), None)
            if target_index is None:
                continue
            target_path = path + (target_index,)
            pending = [(target_path, node.children[target_index])]
            while pending:
                position, target = pending.pop()
                if target.kind not in patterns:
                    continue
                if target.kind == 'identifier':
                    label = labels.get(position)
                    if label and label[0] == 'single_scope_local':
                        replacement[label] = ('aligned_local', anchor_kind, position[1:])
                else:
                    pending.extend((position + (i,), child) for i, child in enumerate(target.children))
        result.append({path: replacement.get(label, ('unaligned_local', source_index, label))
                       if label and label[0] == 'single_scope_local' else label
                       for path, label in labels.items()})
    return result


def align_analogy(A, B, C, *, anchor_keys=None, roles=None, order='residual_first',
                  max_statements=64, max_nodes=2000, max_holes=32):
    """Return one bounded syntactic hypothesis with source-occurrence witnesses.

    Inputs are SourceTerms for module/program/block/statement_block nodes.
    ``anchor_keys`` may provide three lists of externally resolved anchor labels;
    otherwise statement outer kind and overlapping call heads propose alignment.
    ``roles`` are optional original-path maps consumed by the unchanged core.
    ``order`` chooses which source's additions come first within a shared gap.
    Both choices preserve the internal order of C's residuals and B's additions;
    neither choice is a proof that their effects or bindings are compatible.
    The erasing-RHS v2.1 kernel is used; omitted parameters remain explicit.
    """
    if order not in {'residual_first', 'edit_first'}:
        raise ValueError('order must be residual_first or edit_first')
    if any(type(n) is not int or n < 1 for n in (max_statements, max_nodes, max_holes)):
        raise ValueError('budgets must be positive integers')
    sources = (A, B, C)
    try:
        parts = [_parts(source) for source in sources]
        if any(len(p['units']) > max_statements for p in parts):
            return AlignmentResult('unsupported', reason='statement_budget')
        for source in sources:
            list(subterms(source.term, max_nodes=max_nodes))
        if anchor_keys is None:
            keys = [[_key(statement) for statement in p['statements']] for p in parts]
            compatible = lambda a, b: a[0] == b[0] and (bool(a[1] & b[1]) if a[1] and b[1] else a[1] == b[1])
            anchor_precision = 'outer_statement_kind_and_overlapping_call_head_spelling'
        else:
            if len(anchor_keys) != 3 or any(len(k) != len(p['units']) for k, p in zip(anchor_keys, parts)):
                raise ValueError('anchor_keys must label every direct statement in A, B and C')
            keys, compatible = anchor_keys, lambda a, b: a == b
            anchor_precision = 'caller_supplied_labels'
        embedded = [_unique_embedding(keys[0], keys[i], compatible) for i in (1, 2)]
        for label, choices in zip(('B', 'C'), embedded):
            if len(choices) != 1:
                return AlignmentResult('unsupported', reason='ambiguous_alignment' if choices else 'missing_anchor',
                                       provenance={'source': label, 'alignment_count_capped_at_two': len(choices)})
        mappings = [tuple(range(len(keys[0]))), embedded[0][0], embedded[1][0]]
        ordering = ('residual', 'edit') if order == 'residual_first' else ('edit', 'residual')
        augmented = [_augment(source, p, mapping, role, ordering)
                     for source, p, mapping, role in zip(sources, parts, mappings, ('base', 'edit', 'residual'))]
        checks = {f'{name}_source_bytes_preserved': render(view[0]) == render(source.term)
                  for name, source, view in zip('ABC', sources, augmented)}
        checks.update({f'{name}_each_statement_once_in_order':
                       [row['statement'] for row in view[2]] == list(range(len(p['units'])))
                       for name, p, view in zip('ABC', parts, augmented)})
        if not all(checks.values()):
            return AlignmentResult('unsupported', reason='alignment_reconstruction_failed', provenance={'checks': checks})
        if roles is not None:
            if len(roles) != 3:
                raise ValueError('roles must contain three original source-path maps')
            transported_roles = [{view[1][path]: label for path, label in labels.items() if path in view[1]}
                                 for view, labels in zip(augmented, roles)]
            transported_roles = _aligned_local_roles(augmented, transported_roles)
        else:
            transported_roles = None
        result = analogy(*(view[0] for view in augmented), roles=transported_roles,
                         max_nodes=max_nodes, max_holes=max_holes)
        witness = {'checks': checks, 'alignment': {'A_to_B': list(mappings[1]), 'A_to_C': list(mappings[2])},
                   'anchor_precision': anchor_precision, 'gap_order': order,
                   'binding_correspondence': 'supplied_unique_local_identities_at_aligned_declaration_paths; parameters_keep_slot',
                   'source_occurrences': dict(zip('ABC', [view[2] for view in augmented])),
                   'has_shared_gap': bool({r['gap'] for r in augmented[1][2] if r['role'] == 'edit'} &
                                          {r['gap'] for r in augmented[2][2] if r['role'] == 'residual'}),
                   'unproved': ['syntax_validity', 'context_admissibility', 'bindings_and_capture', 'effects', 'oracle_validity'],
                   'kernel': 'test_edit_analogy_v2_1_allow_erasing_rhs',
                   'analogy': {k: v for k, v in result.provenance.items()
                               if k not in {'source_substitutions', 'target_substitutions'}}}
        if result.status != 'hypothesis':
            return AlignmentResult('unsupported', reason='analogy:' + result.reason, provenance=witness)
        residual_checks = {str(gap): at(result.output, (slot,)) == augmented[2][0].children[slot]
                           for gap, slot in augmented[2][3].items()}
        witness['checks']['C_residual_slots_preserved_exactly'] = all(residual_checks.values())
        witness['residual_slots'] = residual_checks
        if not all(residual_checks.values()):
            return AlignmentResult('unsupported', reason='residual_preservation_failed', provenance=witness)
        output_labels = _transport_roles(*(transported_roles or ({}, {}, {}))[1:],
                                         result.provenance['transfers'])
        output, output_labels = _restore(result.output, C.term, parts[2], output_labels)
        witness['checks']['adapter_removal_preserves_output_bytes'] = render(output) == render(result.output)
        return AlignmentResult('hypothesis', output, witness, output_roles=output_labels)
    except BudgetExceeded:
        return AlignmentResult('unsupported', reason='node_or_depth_budget')
