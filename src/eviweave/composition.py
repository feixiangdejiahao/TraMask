"""Finite local-recipe joins; compatibility is not proof of program semantics.

Each relation is a required choice of one recipe. A row may change several roles.
Shared roles require equal concrete values; ``None`` is unresolved support, never
evidence of a conflict. Unknown conditions travel with the selected recipes.
The schema describes setup constraints, not product obligations or oracle truth.

The indexed search builds a DAG of shared suffix choices, without expanding the
Cartesian product. Its count is a count of recipe assignments, not distinct test
programs: source provenance is metadata, and no semantic equivalence is inferred.
"""

from collections import deque
from dataclasses import dataclass
from itertools import product
import json


@dataclass(frozen=True)
class _State:
    values: tuple = ()
    same: tuple = ()
    different: tuple = ()
    excluded: tuple = ()
    guards: tuple = ()
    order: tuple = ()


def _normalize(values=(), same=(), different=(), excluded=(), guards=(), order=()):
    """Canonicalize equalities, disequalities and a strict event partial order."""
    roles = {role for role, _ in values} | {role for role, _ in excluded}
    roles.update(role for pair in (*same, *different) for role in pair)
    parent = {role: role for role in roles}

    def root(role):
        while parent[role] != role:
            parent[role] = parent[parent[role]]
            role = parent[role]
        return role

    for left, right in same:
        a, b = sorted((root(left), root(right)))
        parent[b] = a
    known = {}
    for role, value in values:
        role = root(role)
        if role in known and known[role] != value:
            return None
        known[role] = value
    forbidden = {}
    for role, value in excluded:
        forbidden.setdefault(root(role), set()).add(value)
    distinct = set()
    for left, right in different:
        a, b = sorted((root(left), root(right)))
        if a == b:
            return None
        if a in known and b in known:
            if known[a] == known[b]:
                return None
        elif a in known:
            forbidden.setdefault(b, set()).add(known[a])
        elif b in known:
            forbidden.setdefault(a, set()).add(known[b])
        else:
            distinct.add((a, b))
    if any(known.get(role) in vals for role, vals in forbidden.items()):
        return None
    guard_values = {}
    for guard, value in guards:
        if guard in guard_values and guard_values[guard] != value:
            return None
        guard_values[guard] = value
    successors = {}
    for before, after in order:
        successors.setdefault(before, set()).add(after)
    closure = set()
    for start in successors:
        pending = list(successors[start])
        reached = set()
        while pending:
            event = pending.pop()
            if event == start:
                return None
            if event not in reached:
                reached.add(event)
                pending.extend(successors.get(event, ()))
        closure.update((start, end) for end in reached)
    return _State(
        tuple(sorted(known.items())),
        tuple(sorted((root(role), role) for role in roles if root(role) != role)),
        tuple(sorted(distinct)),
        tuple(sorted((role, value) for role, vals in forbidden.items() for value in vals)),
        tuple(sorted(guard_values.items())),
        tuple(sorted(closure)),
    )


def _merge(left, right):
    return _normalize(
        left.values + right.values, left.same + right.same,
        left.different + right.different, left.excluded + right.excluded,
        left.guards + right.guards, left.order + right.order,
    )


def _known_roles(state):
    values = dict(state.values)
    for root, role in state.same:
        if root in values:
            values[role] = values[root]
    return values


def _project(state, roles, guards, events):
    """Forget the past, preserving its equality, exclusion and reachability effects."""
    groups = {}
    for root, role in state.same:
        groups.setdefault(root, {root}).add(role)
    values = dict(state.values)
    excluded = {}
    for role, value in state.excluded:
        excluded.setdefault(role, []).append(value)
    all_roles = set(values) | set(excluded)
    all_roles.update(role for pair in state.different for role in pair)
    for role in all_roles:
        groups.setdefault(role, {role})
    renaming = {}
    projected_same = []
    projected_values = []
    projected_excluded = []
    for old_root, members in groups.items():
        visible = sorted(members & roles)
        if not visible:
            continue
        new_root = visible[0]
        renaming[old_root] = new_root
        projected_same.extend((new_root, role) for role in visible[1:])
        if old_root in values:
            projected_values.append((new_root, values[old_root]))
        projected_excluded.extend((new_root, value) for value in excluded.get(old_root, ()))
    # A different-identity constraint with one known side was already converted
    # to an excluded value. An unbound, forgotten side cannot contradict a future
    # concrete choice; its unresolved requirement remains in the selected row.
    projected_different = [
        tuple(sorted((renaming[a], renaming[b]))) for a, b in state.different
        if a in renaming and b in renaming
    ]
    return _State(
        tuple(sorted(projected_values)), tuple(sorted(projected_same)),
        tuple(sorted(projected_different)), tuple(sorted(projected_excluded)),
        tuple((g, v) for g, v in state.guards if g in guards),
        tuple((a, b) for a, b in state.order if a in events and b in events),
    )


@dataclass(frozen=True)
class Recipe:
    id: str
    bindings: tuple
    same: tuple
    different: tuple
    guards: tuple
    order: tuple
    unknown: tuple
    provenance: tuple
    state: _State | None

    @property
    def roles(self):
        return {r for r, _ in self.bindings} | {r for pair in (*self.same, *self.different) for r in pair}


@dataclass(frozen=True)
class Relation:
    id: str
    rows: tuple[Recipe, ...]


def parse_relations(raw):
    """Parse the JSON-shaped relation schema once at its owning input boundary.

    Required: relation ``id/rows`` and recipe ``id/bindings``. Optional recipe
    fields: ``same/different/order`` pairs, boolean ``guards``, string lists
    ``unknown/provenance``. Binding values are JSON scalars; null means unknown.
    Recipe IDs are unique within a relation. Merge alternate provenance into one
    row upstream only when the entire recipe and constraint boundary are equal.
    """
    def name(value):
        if not isinstance(value, str):
            raise TypeError("Relation, recipe, role and event names must be strings")
        return value

    def pairs(items):
        result = []
        for left, right in items:
            result.append((name(left), name(right)))
        return tuple(sorted(set(result)))

    result = []
    for table in raw:
        rows = []
        for item in table['rows']:
            bindings = []
            unknown = [name(reason) for reason in item.get('unknown', ())]
            for role, value in item['bindings'].items():
                name(role)
                if value is not None and type(value) not in (str, int, float, bool):
                    raise TypeError("Recipe bindings must be JSON scalars or null")
                bindings.append((role, json.dumps(value, ensure_ascii=False, allow_nan=False)))
                if value is None:
                    unknown.append('binding:' + role)
            guards = []
            for guard, value in item.get('guards', {}).items():
                name(guard)
                if value is not None and type(value) is not bool:
                    raise TypeError("Guards must be booleans or null")
                guards.append((guard, value))
                if value is None:
                    unknown.append('guard:' + guard)
            same = pairs(item.get('same', ()))
            different = pairs(item.get('different', ()))
            order = pairs(item.get('order', ()))
            state = _normalize(
                tuple((r, v) for r, v in bindings if v != 'null'), same, different, (),
                tuple((g, v) for g, v in guards if v is not None), order,
            )
            rows.append(Recipe(
                name(item['id']), tuple(sorted(bindings)), same, different,
                tuple(sorted(guards)), order, tuple(sorted(set(unknown))),
                tuple(sorted({name(p) for p in item.get('provenance', ())})), state,
            ))
        if len({row.id for row in rows}) != len(rows):
            raise ValueError("Recipe IDs must be unique within a relation")
        result.append(Relation(name(table['id']), tuple(rows)))
    if len({table.id for table in result}) != len(result):
        raise ValueError("Relation IDs must be unique")
    return tuple(result)


@dataclass(frozen=True)
class Plan:
    selections: tuple[tuple[str, Recipe], ...]

    @property
    def choices(self):
        return tuple((table, row.id) for table, row in self.selections)

    def as_dict(self):
        state = _State()
        for _, row in self.selections:
            state = _merge(state, row.state)
            assert state is not None, "Search emitted an inconsistent recipe assignment"
        bindings = {r: None for _, row in self.selections for r, _ in row.bindings}
        bindings.update((r, json.loads(v)) for r, v in _known_roles(state).items())
        return {
            'choices': dict(self.choices), 'bindings': bindings,
            'same': [list(pair) for pair in state.same],
            'different': [list(pair) for _, row in self.selections for pair in row.different],
            'guards': dict(state.guards), 'order': [list(pair) for pair in state.order],
            'unknown': sorted({u for _, row in self.selections for u in row.unknown}),
            'provenance': sorted({p for _, row in self.selections for p in row.provenance}),
        }


def _stats(relations):
    return dict(
        input_rows=sum(len(t.rows) for t in relations), surviving_rows=0,
        support_revisions=0, support_pair_checks=0, support_index_candidates=0,
        search_row_checks=0, search_index_candidates=0, search_nodes=0,
        cache_hits=0, cartesian_tuples=0, source_assignments=0,
    )


@dataclass
class SearchResult:
    plans: list[Plan]
    stats: dict


def naive_search(relations):
    """Enumerate the full finite Cartesian product, then check each assignment."""
    stats = _stats(relations)
    stats['surviving_rows'] = stats['input_rows']
    plans = []
    for chosen in product(*(t.rows for t in relations)):
        stats['cartesian_tuples'] += 1
        state = _State()
        for row in chosen:
            stats['search_row_checks'] += 1
            state = None if row.state is None else _merge(state, row.state)
            if state is None:
                break
        if state is not None:
            plans.append(Plan(tuple((t.id, row) for t, row in zip(relations, chosen))))
    stats['source_assignments'] = len(plans)
    return SearchResult(plans, stats)


class _Index:
    """Equality postings include wildcard rows, so missing evidence cannot prune."""
    def __init__(self, relation):
        self.postings = {}
        present = {}
        self.valid = set()
        for i, row in enumerate(relation.rows):
            if row.state is None:
                continue
            self.valid.add(i)
            assignments = [(('role', r), v) for r, v in _known_roles(row.state).items()]
            assignments += [(('guard', g), v) for g, v in row.state.guards]
            for key, value in assignments:
                self.postings.setdefault(key, {}).setdefault(value, set()).add(i)
                present.setdefault(key, set()).add(i)
        self.unknown = {key: self.valid - indices for key, indices in present.items()}

    def candidates(self, state, active):
        choices = active
        assignments = [(('role', r), v) for r, v in _known_roles(state).items()]
        assignments += [(('guard', g), v) for g, v in state.guards]
        for key, value in assignments:
            if key in self.postings:
                choices = choices & (self.postings[key].get(value, set()) | self.unknown[key])
                if not choices:
                    break
        return sorted(choices)


def _support(relations, indexes, stats):
    active = [index.valid.copy() for index in indexes]
    signatures = []
    for table in relations:
        signatures.append(
            {('role', r) for row in table.rows for r in row.roles}
            | {('guard', g) for row in table.rows for g, _ in row.guards}
            | {('event', e) for row in table.rows for edge in row.order for e in edge}
        )
    neighbors = [
        [j for j in range(len(relations)) if i != j and signatures[i] & signatures[j]]
        for i in range(len(relations))
    ]
    pending = deque((i, j) for i in range(len(relations)) for j in neighbors[i])
    supports = {}
    while pending:
        i, j = pending.popleft()
        stats['support_revisions'] += 1
        remove = []
        for r in sorted(active[i]):
            key = i, j, r
            if key in supports and supports[key] in active[j]:
                continue
            state = relations[i].rows[r].state
            candidates = indexes[j].candidates(state, active[j])
            stats['support_index_candidates'] += len(candidates)
            for s in candidates:
                stats['support_pair_checks'] += 1
                if _merge(state, relations[j].rows[s].state) is not None:
                    supports[key] = s
                    break
            else:
                remove.append(r)
        if remove:
            active[i].difference_update(remove)
            pending.extend((k, i) for k in neighbors[i] if k != j)
    stats['surviving_rows'] = sum(map(len, active))
    return active


@dataclass(frozen=True)
class _Node:
    edges: tuple
    count: int


@dataclass
class SearchSpace:
    relations: tuple[Relation, ...]
    root: _Node
    stats: dict
    surviving: tuple[tuple[str, ...], ...]

    @property
    def plan_count(self):
        """Exact recipe-assignment count; provenance alternatives are not choices."""
        return self.root.count

    def iter_plans(self, limit=None):
        """Expand in input relation/row order. A budget never removes DAG choices."""
        if limit is not None and limit < 0:
            raise ValueError("Plan limit must be nonnegative")
        emitted = 0

        def visit(depth, node, chosen):
            nonlocal emitted
            if limit is not None and emitted >= limit:
                return
            if depth == len(self.relations):
                emitted += 1
                yield Plan(chosen)
                return
            table = self.relations[depth]
            for row_index, child in node.edges:
                yield from visit(depth + 1, child, chosen + ((table.id, table.rows[row_index]),))
                if limit is not None and emitted >= limit:
                    break

        yield from visit(0, self.root, ())


def indexed_search(relations):
    """Propagate pair supports, then hash-join and memoize future boundary states.

    Pairwise support alone is insufficient: every edge checks the accumulated
    binding, guard and order constraints. Projected order is transitive closure,
    preserving paths through events absent from the remaining relations.
    """
    relations = tuple(relations)
    stats = _stats(relations)
    indexes = [_Index(table) for table in relations]
    active = _support(relations, indexes, stats)
    boundaries = [(set(), set(), set()) for _ in range(len(relations) + 1)]
    for i in reversed(range(len(relations))):
        roles, guards, events = (s.copy() for s in boundaries[i + 1])
        for row in relations[i].rows:
            roles.update(row.roles)
            guards.update(g for g, _ in row.guards)
            events.update(e for edge in row.order for e in edge)
        boundaries[i] = roles, guards, events
    memo = {}
    terminal = _Node((), 1)

    def build(depth, state):
        if depth == len(relations):
            return terminal
        state = _project(state, *boundaries[depth])
        key = depth, state
        if key in memo:
            stats['cache_hits'] += 1
            return memo[key]
        stats['search_nodes'] += 1
        edges = []
        candidates = indexes[depth].candidates(state, active[depth])
        stats['search_index_candidates'] += len(candidates)
        for row_index in candidates:
            stats['search_row_checks'] += 1
            joined = _merge(state, relations[depth].rows[row_index].state)
            if joined is not None:
                child = build(depth + 1, joined)
                if child.count:
                    edges.append((row_index, child))
        node = _Node(tuple(edges), sum(child.count for _, child in edges))
        memo[key] = node
        return node

    root = build(0, _State())
    stats['source_assignments'] = root.count
    surviving = tuple(tuple(t.rows[i].id for i in sorted(a)) for t, a in zip(relations, active))
    return SearchSpace(relations, root, stats, surviving)
