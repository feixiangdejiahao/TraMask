"""A bounded may-dependence priority across local values and receiver setup.

This module allocates review effort. It does not admit tests or certify any
oracle. It extends the existing call prior without importing evaluation labels,
runtime failures, production bodies, or model completions.
"""
from __future__ import annotations

import re

from anchor_retrieval.syntax import ATTRS, CALLS, attr_parts, call_parts, child, walk
from relation_search import edited_contract_call_priority as base
from relation_search import semantic_selection
from relation_search.edited_contract_call_priority import (
    FUNCTIONS, _binding, _chain, _extent, _identity_names, _inside, _mapped,
    _overlap, _read_names, _scope, _statement,
)

POLICY = dict(base.POLICY,
    version='transitive-edited-contract-call-priority.v1',
    issue_names='v1 code names plus exact source API identifiers containing an internal capital or underscore in issue prose',
    input_reach='bounded backward local assignment closure, zero-argument local function bodies, and receiver constructor arguments',
    receiver='unchanged frontend class constructor binding with edits confined to constructor arguments; no factory-return guess',
    limits=dict(max_reach_nodes=64, max_reach_depth=12),
    claim='may dependence for ranking only; no execution, validity, path feasibility, purity, or runtime dispatch proof',
    unknown='cyclic or exhausted reach does not receive priority; unresolved dispatch stays in baseline order')

digest = base.digest


def issue_names(issue, functions):
    names = set(base.issue_names(issue))
    tokens = set(re.findall(r'(?<![\w$])[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?![\w$])', issue))
    for function in functions:
        if not function.get('production'):
            continue
        name = function['name']
        candidates = [name]
        if function.get('owner'):
            candidates.append(function['owner'] + '.' + name)
        for value in candidates:
            # A common word such as read/get/call is not enough without code
            # markup. Matching is exact and remains case sensitive.
            if value in tokens and ('.' in value or '_' in value or re.search(r'[a-z][A-Z]', value)):
                names.add(value)
    return sorted(names)


class Analyzer(base.Analyzer):
    def __init__(self, corpus, frontend, issue):
        super().__init__(corpus, frontend, issue)
        self.names = issue_names(issue, frontend.get('functions', []))
        self.reach_unknowns = set()

    def _resolve(self, source, call, assignments, original_calls, changes):
        old_result = super()._resolve(source, call, assignments, original_calls, changes)
        if old_result:
            return old_result
        fn, _ = call_parts(call)
        parts = _chain(source, fn)
        if not parts or len(parts) != 2:
            return None
        matches = original_calls.get(_extent(call), [])
        if len(matches) != 1 or matches[0].get('callee') != source.text(fn):
            return None
        old = matches[0]
        targets = [row for row in old.get('targets', []) if row.get('resolved')
                   and row.get('reason') == 'source_constructor_receiver']
        if len(targets) != 1 or len({row['function_id'] for row in old.get('targets', [])
                                   if row.get('resolved')}) != 1:
            return None
        function = self.functions.get(targets[0]['function_id'])
        binding = _binding(assignments, parts[0], call)
        if function is None or not function.get('owner') or binding is None:
            return None
        value = binding['value']
        if not (value.type == 'new_expression' or source.language == 'python' and value.type == 'call'):
            return None
        constructor, arguments = call_parts(value)
        if constructor is None:
            return None
        changed = [row for row in changes if _overlap(row['new'], _extent(binding['node']))]
        if not changed or not all(any(_inside(_extent(arg), row['new']) for arg in arguments)
                                  for row in changed):
            return None
        # A changed constructor callee, assignment target, or declaration header
        # cannot retain the original receiver-class evidence.
        if any(_overlap(row['new'], _extent(constructor)) for row in changes):
            return None
        name = function['owner'] + '.' + function['name']
        canonical = (old.get('callee_identity') or {}).get('canonical') or name
        return dict(identity=canonical, names=sorted(_identity_names(name) | _identity_names(canonical)),
                    basis='unchanged_class_constructor_with_argument_only_edits')

    def _reach(self, source, node, assignments, inputs):
        """Over-approximate local value influence; leave uncertain joins alone."""
        active, seen, hits = set(), set(), set()
        consumed = 0

        def visit(value, depth):
            nonlocal consumed
            key = _extent(value)
            if key in active:
                raise ValueError('cyclic_local_reach')
            if key in seen:
                return
            consumed += 1
            if consumed > POLICY['limits']['max_reach_nodes'] or depth > POLICY['limits']['max_reach_depth']:
                raise ValueError('local_reach_budget')
            active.add(key)
            hits.update(edit['index'] for edit in inputs if _overlap(edit['new'], key))
            for name in sorted(_read_names(source, value)):
                binding = _binding(assignments, name, value)
                if binding is not None:
                    visit(binding['value'], depth + 1)
                    continue
                # A named, zero-argument local function can supply a generator
                # or computed value. Its body is may-dependence evidence only.
                for invocation in walk(value):
                    if invocation.type not in CALLS:
                        continue
                    callee, arguments = call_parts(invocation)
                    if callee is None or source.text(callee) != name or arguments:
                        continue
                    definitions = [part for part in walk(source.root)
                        if part.type in {'function_definition', 'function_declaration'}
                        and source.text(child(part, 'name')) == name
                        and part.end_byte <= invocation.start_byte and _scope(part) == _scope(invocation)
                        and _statement(part).parent == _statement(invocation).parent]
                    if len(definitions) != 1:
                        continue
                    if any(row['name'] == name and row['scope'] == _scope(invocation) for row in assignments):
                        continue
                    declaration = definitions[0]
                    parameters = child(declaration, 'parameters')
                    if parameters is None or parameters.named_children:
                        continue
                    body = child(declaration, 'body')
                    if body is not None:
                        visit(body, depth + 1)
            active.remove(key)
            seen.add(key)

        try:
            visit(node, 0)
        except ValueError as error:
            self.reach_unknowns.add(str(error))
            return set()
        return hits

    def _affected(self, source, call, assignments, inputs):
        fn, arguments = call_parts(call)
        expressions = [(slot, node, 'transitive_local_argument_may_reach')
                       for slot, node in enumerate(arguments)]
        if fn is not None and fn.type in ATTRS:
            receiver, _ = attr_parts(fn)
            if receiver is not None:
                expressions.append((-1, receiver, 'receiver_value_may_reach'))
        by_index = {row['index']: row for row in inputs}
        affected = []
        for slot, expression, basis in expressions:
            for index in sorted(self._reach(source, expression, assignments, inputs)):
                affected.append((by_index[index], slot, basis))
        return affected

    def evidence(self, raw):
        self.reach_unknowns = set()
        result = super().evidence(raw)
        result['unknowns'].extend(sorted(self.reach_unknowns))
        return result


def select(corpus, frontend, candidates, issue, *, budget=16):
    baseline = semantic_selection.select(corpus, candidates, budget=budget)
    analyzer = Analyzer(corpus, frontend, issue)
    by_id = {row['id']: row for row in candidates}
    evidence = {row['id']: analyzer.evidence(row) for row in candidates}
    ranking = sorted(baseline['ranking'], key=lambda row: (not evidence[row['id']]['feature'], row['rank']))
    rows = [dict(row, shape_rank=row['rank'], rank=i + 1, selected=i < budget,
                 contract_call=evidence[row['id']]) for i, row in enumerate(ranking)]
    return dict(selected=[by_id[row['id']] for row in rows[:budget]], ranking=rows,
                issue_names=analyzer.names, policy=POLICY, policy_sha256=digest(POLICY),
                baseline_policy_sha256=baseline['policy_sha256'], input_count=len(candidates),
                selected_count=min(len(candidates), budget))
