"""Cache-only assertion lookup for the frozen patch-observation selector.

Each modified test owner builds a lazy index in the original assertion order.
The original adapter computes each entry, so expected/actual roles, source
matching, first-match selection and unknown rules are unchanged.  No semantic
rule, candidate filtering, model request or subject execution is added.

The defaults match v2 with ``disable_receiver_fix=True``.  ``work_counts`` is
external instrumentation, never included in evidence or selection output.
"""
from __future__ import annotations

import hashlib

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Unit
from prototypes.modified_observation_impact import map_unchanged_span
from prototypes.patch_observation_priority import (
    _SYNTHETIC, _assertion_nodes, _extent, _flow_for_test, _modified_sources,
    _scope_unknown, _sha, _test_walk, span,
)
from prototypes.patch_observation_priority_v2 import Analyzer as V2Analyzer, POLICY
from relation_search import semantic_selection
from relation_search.instrument import _program_edits


VERSION = 'patch-observation-assertion-cache-v1'


class _AssertionLookup:
    """Memoize adapter results; preserve the earliest statement-span match."""
    def __init__(self, source, unit, flow, counts):
        self.source = source
        self.unit = unit
        self.pending = iter(flow.assertions)
        self.by_span = {}
        self.counts = counts
        counts['assertion_lookup_builds'] += 1

    def find(self, extent):
        key = (extent['start_byte'], extent['end_byte'])
        self.counts['assertion_lookup_queries'] += 1
        if key in self.by_span:
            self.counts['assertion_index_hits'] += 1
            return self.by_span[key]
        for assertion in self.pending:
            self.counts['assertion_adapter_computations'] += 1
            statement, actual, _, _ = _assertion_nodes(self.source, assertion, self.unit)
            if statement is not None:
                found = (statement.start_byte, statement.end_byte)
                self.by_span.setdefault(found, (assertion, actual))
                if found == key:
                    return self.by_span[key]
        return None


class Analyzer(V2Analyzer):
    def __init__(self, corpus, frontend, patch, *, disable_receiver_fix=True):
        super().__init__(corpus, frontend, patch, disable_receiver_fix=disable_receiver_fix)
        self.work_counts = dict(assertion_lookup_builds=0, assertion_lookup_queries=0,
                                assertion_adapter_computations=0, assertion_index_hits=0)
        self._assertion_lookup = None

    def _variant(self, owner):
        self._assertion_lookup = None
        return super()._variant(owner)

    def _lookup(self, owner, unit, flow):
        if self._assertion_lookup is None:
            self._assertion_lookup = _AssertionLookup(owner, unit, flow, self.work_counts)
        return self._assertion_lookup

    def _observation_span(self, old, changes):
        return map_unchanged_span(old, changes)

    def _observation_source_matches(self, owner, current, old):
        return owner.data[current['start_byte']:current['end_byte']] == self.corpus['sources'][old['path']]['code'].encode()[old['start_byte']:old['end_byte']]

    def evidence(self, candidate):
        # Same v1 evidence body inherited by v2, except the lazy assertion lookup
        # replaces the repeated prefix scan and second actual-node adapter call.
        clean = dict(candidate, edits=_program_edits(candidate)); base = clean['base_test_id']
        record = dict(strong_priority=False, may_priority=False, witnesses=[], may_witnesses=[], unknowns=[], patch_unknowns=self.patch_unknowns,
                      scope='modified_test_and_final_repository_return_may_dependencies')
        try:
            sources, owner, changes, imports, unknowns = _modified_sources(self.corpus, clean)
            if len({(e['span']['path'], e['span']['start_byte'], e['span']['end_byte']) for e in clean['edits']}) != len(clean['edits']):
                raise ValueError('duplicate_edit_coordinates')
            index = self._variant(owner); original = self.corpus['tests'][base]
            definition = original.get('definition_span') or original['span']
            anchor = dict(path=owner.path, start_byte=definition['start_byte'], end_byte=definition['start_byte']+1)
            mapped = map_unchanged_span(anchor, changes)
            matches = [u for u in index.units.values() if u.source.path == owner.path and mapped and u.node.start_byte == mapped['start_byte']]
            if original.get('owner_kind') == 'module_script':
                matches = [Unit(owner, owner.root, owner.root, '<script>', test=True)]
                index.units[matches[0].id] = matches[0]
            if len(matches) != 1: raise ValueError('modified_test_identity_unknown')
            unit = matches[0]
            scope_unknown = _scope_unknown(unit)
            if scope_unknown: record['unknowns'].append(scope_unknown)
            flow = _flow_for_test(index, unit, list(_test_walk(unit.body)))
            record.update(modified_owner_sha256=hashlib.sha256(owner.data).hexdigest(), input_changes=changes, import_bindings=imports)
            record['unknowns'].extend(row['reason'] for row in unknowns)
            for q in self.observations[base]:
                old = q.get('assertion_span') or q['span']; current = self._observation_span(old, changes)
                if current is None:
                    record['unknowns'].append('changed_assertion_unknown'); continue
                if not self._observation_source_matches(owner, current, old):
                    raise ValueError('assertion_source_identity_mismatch')
                found = self._lookup(owner, unit, flow).find(current)
                if found is None:
                    record['unknowns'].append('modified_observation_unavailable'); continue
                assertion, actual = found
                roots = [n['id'] for n in flow.nodes if actual is not None and n['kind'] not in _SYNTHETIC
                         and n['start_byte'] == actual.start_byte and n['end_byte'] == actual.end_byte]
                summary = self._slice(index, unit, flow, roots, (unit.id,)) if not scope_unknown else dict(patches=[], unknowns={scope_unknown})
                record['unknowns'].extend(summary['unknowns'])
                may_witnesses, may_unknowns = self._may_witnesses(index, unit, flow, roots, changes, q, old, current, actual) if actual is not None else ([], {'actual_unavailable'})
                record['may_witnesses'].extend(may_witnesses); record['unknowns'].extend(may_unknowns)
                for item in summary['patches']:
                    for change in changes:
                        if change['role'] == 'semantic_expected' or change['before'] == change['after']: continue
                        extent = change['span']
                        if extent['start_byte'] == extent['end_byte']:
                            record['unknowns'].append('deleted_input_no_modified_seed'); continue
                        seeds = [nid for nid in item['input_node_ids'] if flow.nodes[nid]['kind'] not in _SYNTHETIC
                                 and extent['start_byte'] < flow.nodes[nid]['end_byte'] and flow.nodes[nid]['start_byte'] < extent['end_byte']]
                        if not seeds or not item['call_chain']: continue
                        record['witnesses'].append(dict(item, observation_id=q['id'], original_assertion_span=old,
                            modified_assertion_span=current, actual_span=span(owner, actual),
                            original_edit_span=change['original_span'], modified_edit_span=extent,
                            input_nodes=[dict(span=_extent(owner, flow.nodes[nid]),
                                code=owner.data[flow.nodes[nid]['start_byte']:flow.nodes[nid]['end_byte']].decode()) for nid in sorted(seeds)],
                            status='complete_source_return_may_path_not_execution_or_oracle_proof'))
        except (ValueError, KeyError, TypeError, IndexError, RecursionError, UnicodeError) as error:
            record['unknowns'].append(str(error)); record['witnesses'] = []; record['may_witnesses'] = []
        record['strong_priority'] = bool(record['witnesses'])
        record['may_priority'] = bool(record['witnesses'] or record['may_witnesses'])
        for key in ('witnesses', 'may_witnesses'):
            representatives = {}
            for row in sorted(record[key], key=lambda item: (len(item['call_chain']), item['patch_span']['path'], item['patch_span']['start_byte'], item['patch_span']['end_byte'])):
                call = row['call_chain'][0]['call_span']
                identity = (row['observation_id'], tuple(sorted(row['original_edit_span'].items())), tuple(sorted(call.items())))
                representatives.setdefault(identity, row)
            record[key] = list(representatives.values())
        record['witness_material'] = 'one deterministic shortest representative per observation/edit/outer call; not all-path coverage'
        record['unknowns'] = sorted(set(record['unknowns']))
        return record


def select(corpus, frontend, candidates, patch, budget=16, *, mode='strict',
           disable_receiver_fix=True):
    """Byte-compatible v2 selection output; cache work counts stay external."""
    if not isinstance(patch, str): raise ValueError('patch must be source text')
    if mode not in {'strict', 'may'}: raise ValueError('unknown priority mode')
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
        for rank, row in enumerate(ranking, 1): row.update(rank=rank, selected=rank <= budget)
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
        for method in (Index.module_paths, Index.reach, Index.field_factors): method.cache_clear()
