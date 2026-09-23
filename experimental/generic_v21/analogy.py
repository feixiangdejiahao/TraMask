"""v2.1 erasing-RHS ablation, isolated from the frozen v2 kernel.

A:B :: C:D by syntax reconstruction, never by executing a subject program.

The caller supplies ground terms and, optionally, three exact-path maps of
stable correspondence/binding labels for A, B and C. Labels are consumed as
given; names, binding scopes, semantic roles and test oracles are not inferred.
An output is a hypothesis requiring independent semantic admission.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from generic_composition.terms import (
    BudgetExceeded, Hole, Node, Term, anti_unify, substitute, subterms,
)


@dataclass(frozen=True)
class AnalogyResult:
    status: str
    output: Term | None = None
    before_pattern: Node | None = None
    after_pattern: Node | None = None
    provenance: dict = field(default_factory=dict)
    reason: str | None = None


class _Unsupported(Exception):
    def __init__(self, reason, **details):
        self.reason, self.details = reason, details


def analogy(A: Term, B: Term, C: Term, *, roles=None,
            max_nodes=512, max_holes=16) -> AnalogyResult:
    """Transport A->B to C, producing D and an executable reconstruction witness.

    P,sA,sC = anti_unify(A,C); abstract matching sA subtrees in B to obtain Q;
    require P[sA]=A, P[sC]=C and Q[sA]=B; return Q[sC]. Equal source subtrees
    with different target images, including unchanged occurrences, are ambiguous.
    Exact-path role labels may disambiguate them. Missing labels never authorize
    a bare identifier rename. A/C difference parameters may be erased by Q and are reported explicitly.

    Fixed output syntax comes from B; substituted subtrees come from C. This
    establishes origin and reconstruction, not scope safety or oracle validity.
    """
    labels = ({}, {}, {}) if roles is None else roles
    if len(labels) != 3:
        raise ValueError('roles must contain the A, B and C exact-path maps')
    for mapping in labels:
        for path, label in mapping.items():
            if not isinstance(path, tuple) or any(type(i) is not int or i < 0 for i in path):
                raise ValueError('Role paths must be tuples of nonnegative integers')
            hash(label)
    P = Q = None
    try:
        for term in (A, B, C):
            if not isinstance(term, Term):
                raise TypeError('analogy expects three ground Terms')
            if any(isinstance(n, Hole) for _, n in subterms(term, max_nodes=max_nodes)):
                raise _Unsupported('non_ground_source')
        if A == B or A == C:
            raise _Unsupported('no_edit_or_no_target_change')
        au = anti_unify(A, C, max_nodes=max_nodes, max_holes=max_holes)
        P, sA, sC = au
        hole_pairs = {(sA[h], sC[h]): h for h in sA}
        source_values = set(sA.values())
        occurrences = {value: [] for value in source_values}

        def corresponding(path):
            pattern, target = P, C
            for index in path:
                if isinstance(pattern, Hole):
                    return None  # Descendants of a whole-subtree change are unaligned.
                pattern, target = pattern.children[index], target.children[index]
            return target

        for path, node in subterms(A, max_nodes=max_nodes):
            if node not in source_values:
                continue
            target = corresponding(path)
            a_label, c_label = labels[0].get(path), labels[2].get(path)
            if target is not None and a_label is not None and c_label is not None and a_label != c_label:
                raise _Unsupported('inconsistent_correspondence_labels', a_path=list(path))
            occurrences[node].append((path, target, a_label, c_label))

        transfers, unchanged_roles = [], []

        def abstract(node, path):
            if node in occurrences:
                b_label = labels[1].get(path)
                matches = occurrences[node]
                if b_label is not None:
                    matches = [row for row in matches if row[2] == b_label]
                    if not matches:
                        unchanged_roles.append(list(path))
                        return node  # Explicitly distinct B-role: keep source-B syntax.
                images = {row[1] for row in matches}
                if None in images:
                    raise _Unsupported('unaligned_source_occurrence', b_path=list(path),
                                       a_paths=[list(row[0]) for row in matches])
                if len(images) != 1:
                    raise _Unsupported('ambiguous_source_subtree', b_path=list(path),
                                       a_paths=[list(row[0]) for row in matches])
                image = next(iter(images))
                if image == node:
                    return node
                if node.kind.endswith('identifier') and not (
                    b_label is not None and all(row[2] == b_label == row[3] for row in matches)
                ):
                    raise _Unsupported('unresolved_identifier_binding', b_path=list(path))
                hole = hole_pairs[(node, image)]
                transfers.append({'b_path': list(path), 'output_path': list(path), 'hole': hole.id,
                                  'a_paths': [list(row[0]) for row in matches],
                                  'c_paths': [list(row[0]) for row in matches],
                                  'correspondence_label': b_label})
                return hole
            return Term(node.kind, node.atom, tuple(abstract(child, path + (i,))
                                                   for i, child in enumerate(node.children)))

        Q = abstract(B, ())
        used = {n for _, n in subterms(Q, max_nodes=max_nodes) if isinstance(n, Hole)}
        # Ordinary rewrite RHS terms may discard source variables. This
        # ablation exposes that choice to admission instead of rejecting it.
        omitted_holes = [h.id for h in sA if h not in used]
        checks = {'P_sA_equals_A': substitute(P, sA, max_nodes=max_nodes) == A,
                  'P_sC_equals_C': substitute(P, sC, max_nodes=max_nodes) == C,
                  'Q_sA_equals_B': substitute(Q, sA, max_nodes=max_nodes) == B}
        if not all(checks.values()):
            raise _Unsupported('source_reconstruction_failed', checks=checks)
        D = substitute(Q, sC, max_nodes=max_nodes)
        if D in (A, B, C):
            raise _Unsupported('no_new_combination')
        return AnalogyResult('hypothesis', D, P, Q, {
            'checks': checks, 'fixed_syntax_from': 'B', 'substituted_syntax_from': 'C',
            'source_substitutions': dict(sA), 'target_substitutions': dict(sC),
            'transfers': transfers, 'explicit_distinct_B_roles': unchanged_roles,
            'omitted_holes': omitted_holes,
            'coverage_policy': 'source_reconstruction_with_erasing_rhs',
            'unproved': ['context_admissibility', 'bindings_and_capture', 'effects', 'oracle_validity'],
        })
    except _Unsupported as exc:
        return AnalogyResult('unsupported', before_pattern=P, after_pattern=Q,
                             provenance=exc.details, reason=exc.reason)
    except BudgetExceeded:
        return AnalogyResult('unsupported', before_pattern=P, after_pattern=Q,
                             reason='syntax_budget_exceeded')
