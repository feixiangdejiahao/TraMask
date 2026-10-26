"""Independent v2: bounded lexical caches plus Python bound-receiver binding.

The frozen v1 implementation is unchanged.  ``disable_receiver_fix=True`` runs
its original binding rules with the caches, for exact source-evidence checks.
The only new functional rule transports a proved implicit first formal to
the concrete call receiver; it does not discard receiver dependencies or add
heap/effect summaries.  No subjects, labels, model answers or runtime are used.
"""
from __future__ import annotations

import hashlib
import posixpath

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import CALLS, call_parts, child, is_test_path, walk
from experimental.patch_observation_priority import (
    Analyzer as V1Analyzer, POLICY as V1_POLICY, _RESOLUTIONS, _module_writes, _sha,
)
from experimental.local_helper_evidence import _writes
from relational_gap.frontend import _parameters, _resolved_targets
from relation_search import semantic_selection
from relation_search.instrument import _program_edits


POLICY = dict(V1_POLICY, version='patch-observation-priority-v2',
              change='identity-scoped lexical/binding caches; proved Python implicit receiver transport')


class Analyzer(V1Analyzer):
    def __init__(self, corpus, frontend, patch, *, disable_receiver_fix=False):
        super().__init__(corpus, frontend, patch)
        self.disable_receiver_fix = disable_receiver_fix
        self._original_source_ids = {id(source) for source in self.index.sources.values()}
        self._module_cache = {}
        self._unit_cache = {}
        self._target_cache = {}

    def _variant(self, owner):
        # A modified owner gets a fresh index/flow, so no node IDs or bindings
        # can leak between candidates, including equal-length callee edits.
        self._unit_cache.clear()
        self._target_cache.clear()
        self._module_cache = {key: value for key, value in self._module_cache.items()
                              if key in self._original_source_ids}
        return super()._variant(owner)

    def _module_facts(self, source):
        key = id(source)
        if key not in self._module_cache:
            rows = _module_writes(source)
            # Retain the object so its identity cannot be recycled while cached.
            self._module_cache[key] = (source, rows, {name for name, _ in rows})
        _, rows, names = self._module_cache[key]
        return rows, names

    def _unit_facts(self, unit):
        key = id(unit)
        if key not in self._unit_cache:
            calls = {}; names = set()
            for node in walk(unit.body, stop_functions=True):
                if node.type in CALLS:
                    calls.setdefault((node.start_byte, node.end_byte), node)
                names.update(_writes(unit.source, node))
            self._unit_cache[key] = (unit, calls, names)
        _, calls, names = self._unit_cache[key]
        return calls, names

    def _target(self, index, unit, flow, call, *, exact_arguments=True):
        key = (id(index), id(unit), id(flow), call.node, exact_arguments)
        if key not in self._target_cache:
            self._target_cache[key] = self._bind_target(index, unit, flow, call,
                                                       exact_arguments=exact_arguments)
        return self._target_cache[key]

    def _implicit_receiver(self, target, call, reason, parameters):
        if (self.disable_receiver_fix or target.source.language != 'python'
                or not target.owner or not parameters or call.receiver is None):
            return False
        # Arbitrary decorators can alter descriptor binding.  Do not infer it.
        decorators = [text.strip().removeprefix('@') for text in target.decorators]
        if not decorators:
            return reason in {'source_constructor_receiver', 'source_this_receiver'}
        if decorators not in (['classmethod'], ['staticmethod']):
            return None
        _, written = self._module_facts(target.source)
        if decorators[0] in written or decorators[0] in target.source.imports:
            return None
        parent = target.node.parent
        while parent is not None and parent.type != 'class_definition':
            parent = parent.parent
        body = child(parent, 'body') if parent is not None else None
        if body is not None:
            names = {name for node in walk(body, stop_functions=True)
                     for name in _writes(target.source, node)}
            for statement in body.named_children:
                definition = child(statement, 'definition') if statement.type == 'decorated_definition' else statement
                if definition is not None:
                    names.update(_writes(target.source, definition))
            if decorators[0] in names:
                return None
        return decorators == ['classmethod']

    def _receiver_constructor_rebound(self, unit, flow, call, module_writes):
        if self.disable_receiver_fix or unit.source.language != 'python' or call.receiver is None:
            return False
        # A class-name assignment invalidates constructor provenance even when
        # the outer method receiver has a different spelling (e.g. instance).
        return any(flow.nodes[nid]['kind'] == 'call'
                   and flow.nodes[nid].get('call', '').split('.', 1)[0] in module_writes
                   for nid in flow.slice([call.receiver.id]))

    def _bind_target(self, index, unit, flow, call, *, exact_arguments):
        # Same lexical/resolution checks and order as frozen v1._target.
        calls, local_writes = self._unit_facts(unit)
        extent = flow.nodes[call.node]
        node = calls.get((extent['start_byte'], extent['end_byte']))
        if node is None:
            return None, 'call_source_node_unavailable'
        fn, args = call_parts(node)
        if any('spread' in arg.type or 'splat' in arg.type or 'variadic' in arg.type for arg in args):
            return None, 'spread_actual_unknown'
        name = unit.source.text(fn); root = name.split('.', 1)[0]
        _, module_writes = self._module_facts(unit.source)
        if root in unit.source.imports and root in module_writes:
            return None, 'module_import_rebound_unknown'
        rebound = root in unit.params or root in local_writes
        targets = _resolved_targets(index, unit, node, call)
        selected = [(uid, reason) for uid, reason in targets
                    if reason in _RESOLUTIONS or reason == 'package_symbol']
        if unit.source.language == 'go' and fn.type == 'identifier' and not rebound:
            package = index.go_packages.get(unit.source.path)
            local = [candidate for candidate in index.by_name.get(name, [])
                     if not candidate.owner and not candidate.test
                     and posixpath.dirname(candidate.source.path) == posixpath.dirname(unit.source.path)
                     and package and index.go_packages.get(candidate.source.path) == package]
            selected = [(candidate.id, 'same_directory_go_static_symbol') for candidate in local]
        if rebound:
            selected = [(uid, reason) for uid, reason in selected
                        if reason in {'source_constructor_receiver', 'source_this_receiver'}
                        or (not exact_arguments and unit.source.language == 'go'
                            and '.' in name and reason == 'receiver_type')]
        if len(selected) != 1:
            return None, 'callee_unresolved_or_ambiguous'
        uid, reason = selected[0]; target = index.units[uid]
        if (reason == 'source_constructor_receiver'
                and self._receiver_constructor_rebound(unit, flow, call, module_writes)):
            return None, 'receiver_constructor_module_binding_rebound_unknown'
        binding_name = target.owner or target.name
        rows, _ = self._module_facts(target.source)
        if any(written == binding_name
               and not (target.source.language == 'go' and target.owner
                        and statement.type in {'type_spec', 'type_alias'})
               and not (statement.start_byte <= target.node.start_byte
                        and target.node.end_byte <= statement.end_byte)
               for written, statement in rows):
            return None, 'target_module_binding_rebound_unknown'
        if reason == 'package_symbol':
            imported = unit.source.imports.get(root)
            expected = []
            if imported:
                for directory, module in self.resolution.get('go_modules', {}).items():
                    relative = posixpath.relpath(posixpath.dirname(target.source.lookup_path), directory or '.')
                    expected.append(module.rstrip('/') + ('/' + relative if relative != '.' else ''))
            if not imported or imported[0] not in expected:
                return None, 'go_import_path_not_proved'
        if target.test or is_test_path(target.source.path):
            return None, 'custom_test_helper_unsupported'
        parameters = _parameters(target)
        if not exact_arguments:
            return (target, {}, reason), None
        implicit = self._implicit_receiver(target, call, reason, parameters)
        if implicit is None:
            return None, 'decorator_binding_unknown'
        explicit = parameters[1:] if implicit else parameters
        if (any(p['name'] is None or p['default'] is not None or p['variadic'] for p in parameters)
                or (implicit and any(p['keyword_only'] for p in parameters))
                or call.keywords or len(call.args) != len(explicit)):
            return None, 'non_exact_argument_binding'
        target.params = [p['name'] for p in parameters]
        arguments = {p['name']: value.id for p, value in zip(explicit, call.args)}
        if implicit:
            arguments[parameters[0]['name']] = call.receiver.id
        return (target, arguments, reason), None


def select(corpus, frontend, candidates, patch, budget=16, *, mode='strict',
           disable_receiver_fix=False):
    """Same complete ordering as v1, with explicitly separable receiver repair."""
    if not isinstance(patch, str):
        raise ValueError('patch must be source text')
    if mode not in {'strict', 'may'}:
        raise ValueError('unknown priority mode')
    candidates = list(candidates)
    normalized = [dict(c, edits=_program_edits(c)) for c in candidates]
    baseline = semantic_selection.select(corpus, normalized, budget=budget)
    analyzer = Analyzer(corpus, frontend, patch, disable_receiver_fix=disable_receiver_fix)
    by_id = {c['id']: c for c in candidates}
    try:
        ranking = [dict(row, baseline_rank=row['rank'], evidence=analyzer.evidence(by_id[row['id']]))
                   for row in baseline['ranking']]
        priority = 'strong_priority' if mode == 'strict' else 'may_priority'
        ranking.sort(key=lambda row: (not row['evidence'][priority], row['baseline_rank']))
        for rank, row in enumerate(ranking, 1):
            row.update(rank=rank, selected=rank <= budget)
        policy = dict(POLICY, receiver_fix_enabled=not disable_receiver_fix)
        return dict(selected=[by_id[row['id']] for row in ranking if row['selected']], ranking=ranking,
                    unselected_ids=[row['id'] for row in ranking if not row['selected']], budget=budget,
                    input_count=len(candidates), selected_count=min(budget, len(candidates)), policy=policy,
                    policy_sha256=_sha(policy), patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                    patch_unknowns=analyzer.patch_unknowns, mode=mode,
                    priority_candidates=sum(row['evidence'][priority] for row in ranking),
                    strong_candidates=sum(row['evidence']['strong_priority'] for row in ranking),
                    may_candidates=sum(row['evidence']['may_priority'] for row in ranking))
    finally:
        for method in (Index.module_paths, Index.reach, Index.field_factors):
            method.cache_clear()
