"""Independent source repairs for edited-observation path queries.

The scored campaign and frozen priority study are unchanged. Correspondence
and argument binding organize source facts; neither proves a correct oracle.
"""
from __future__ import annotations

from anchor_retrieval.syntax import call_parts, child
from prototypes.observation_correspondence import correspond
from prototypes.patch_observation_priority_cached import Analyzer as CachedAnalyzer
from prototypes.source_argument_binding import bind_python_arguments
from prototypes.source_receiver_binding import dispatch_unknown
from relational_gap.frontend import _assertion_nodes, _parameters, span


VERSION = 'repaired-observation-source-analysis-v1'


def _key(extent):
    return extent['path'], extent['start_byte'], extent['end_byte']


def _same_source_span(left, right):
    """Compare UTF-8 source identity, excluding derived display metadata.

    Transported spans contain byte coordinates, while frontend AST spans also
    carry line numbers.  Those extra fields neither change source identity nor
    justify accepting an actual/expected operand at a different location.
    """
    if left is None or right is None:
        return left is right
    return _key(left) == _key(right)


class _RoleCheckedLookup:
    def __init__(self, original, analyzer, owner, unit):
        self.original, self.analyzer, self.owner, self.unit = original, analyzer, owner, unit

    def find(self, extent):
        found = self.original.find(extent)
        if found is None:
            return None
        assertion, actual = found
        mappings = [row for row in self.analyzer._correspondences.values()
                    if row.get('status') == 'corresponding'
                    and _same_source_span(row.get('span'), extent)]
        for mapping in mappings:
            if not _same_source_span(mapping.get('actual_span'),
                                     span(self.owner, actual) if actual is not None else None):
                self.analyzer._role_unknowns.add('modified_actual_role_differs_from_source_observation')
                return None
            if 'expected_span' in mapping:
                _, _, expected, _ = _assertion_nodes(self.owner, assertion, self.unit)
                if not _same_source_span(mapping['expected_span'],
                                         span(self.owner, expected) if expected is not None else None):
                    self.analyzer._role_unknowns.add('modified_expected_role_differs_from_source_observation')
                    return None
        return found


class Analyzer(CachedAnalyzer):
    def __init__(self, corpus, frontend, patch, *, repair_correspondence=True,
                 repair_arguments=True, disable_receiver_fix=False):
        super().__init__(corpus, frontend, patch, disable_receiver_fix=disable_receiver_fix)
        self.repair_correspondence = repair_correspondence
        self.repair_arguments = repair_arguments
        self._owner = None
        self._current_base = None
        self._correspondences = {}
        self._source_observations = {}
        self._role_unknowns = set()

    def _variant(self, owner):
        self._owner = owner
        self._correspondences = {}
        self._source_observations = {}
        for observation in self.observations[self._current_base]:
            old = observation.get('assertion_span') or observation['span']
            self._source_observations.setdefault(_key(old), []).append(observation)
        return super()._variant(owner)

    def _correspondence(self, old, changes):
        key = _key(old)
        if key not in self._correspondences:
            original = self.index.sources[old['path']]
            rows = [correspond(original, self._owner, observation, changes)
                    for observation in self._source_observations.get(key, [])]
            if not rows or any(row != rows[0] for row in rows):
                result = dict(status='unknown', reason='observation_roles_ambiguous_at_span')
            else:
                result = rows[0]
            self._correspondences[key] = result
        return self._correspondences[key]

    def _observation_span(self, old, changes):
        if not self.repair_correspondence:
            return super()._observation_span(old, changes)
        result = self._correspondence(old, changes)
        return result.get('span') if result['status'] == 'corresponding' else None

    def _observation_source_matches(self, owner, current, old):
        if not self.repair_correspondence:
            return super()._observation_source_matches(owner, current, old)
        result = self._correspondences.get(_key(old), {})
        return result.get('status') == 'corresponding' and result.get('span') == current

    def _lookup(self, owner, unit, flow):
        original = super()._lookup(owner, unit, flow)
        return _RoleCheckedLookup(original, self, owner, unit) if self.repair_correspondence else original

    def _bind_target(self, index, unit, flow, call, *, exact_arguments):
        if unit.source.language != 'python' or not self.repair_arguments:
            return super()._bind_target(index, unit, flow, call, exact_arguments=exact_arguments)
        calls, _ = self._unit_facts(unit)
        extent = flow.nodes[call.node]
        node = calls.get((extent['start_byte'], extent['end_byte']))
        if node is None:
            return None, 'call_source_node_unavailable'
        _, arguments = call_parts(node)
        keywords = []
        keyword_seen = False
        for argument in arguments:
            if argument.type == 'keyword_argument':
                keyword_seen = True
                name = unit.source.text(child(argument, 'name'))
                if name not in call.keywords:
                    return None, 'keyword_value_graph_unavailable'
                keywords.append((name, call.keywords[name].id))
            elif keyword_seen and not ('splat' in argument.type or 'spread' in argument.type):
                # Tree-sitter accepts this ordering, while Python rejects it.
                # Check before resolution: a failed Python import parse must
                # not hide the same invalid syntax behind a missing callee.
                return None, 'positional_argument_after_keyword'
        # Reuse source resolution without inheriting its all-positional arity
        # shortcut. The ordered AST keywords retain duplicate names.
        resolved, reason = super()._bind_target(index, unit, flow, call, exact_arguments=False)
        if resolved is None:
            return None, reason
        target, _, resolution = resolved
        if target.source.language != 'python':
            return None, 'cross_language_python_binding_unknown'
        reason = dispatch_unknown(index, unit, flow, call, target)
        if reason is not None:
            return None, reason
        if not exact_arguments:
            return resolved, None
        parameters = _parameters(target)
        implicit = self._implicit_receiver(target, call, resolution, parameters)
        if implicit is None:
            return None, 'decorator_binding_unknown'
        result = bind_python_arguments(parameters, [value.id for value in call.args], keywords,
            implicit_receiver=call.receiver.id if implicit else None,
            has_spread=any('splat' in argument.type or 'spread' in argument.type for argument in arguments))
        if result['status'] != 'bound':
            return None, result['reason']
        target.params = [parameter['name'] for parameter in parameters]
        return (target, result['bindings'], resolution), None

    def evidence(self, candidate):
        self._current_base = candidate['base_test_id']
        self._correspondences = {}
        self._role_unknowns = set()
        result = super().evidence(candidate)
        result['unknowns'] = sorted(set(result['unknowns']) | self._role_unknowns)
        result['source_repairs'] = dict(version=VERSION,
            correspondence_enabled=self.repair_correspondence,
            argument_binding_enabled=self.repair_arguments,
            observations=[dict(original_span=dict(path=key[0], start_byte=key[1], end_byte=key[2]), **row)
                          for key, row in sorted(self._correspondences.items())],
            limits=['source correspondence is not oracle correctness',
                    'bounded receiver dispatch, not whole-program alias proof',
                    'no heap, exception, callback or default-expression summaries'])
        return result
