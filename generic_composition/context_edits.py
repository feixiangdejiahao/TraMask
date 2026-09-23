"""Learn and replay syntactic context changes; no semantic equivalence claims.

Two expressions supply an observed edit C0[E] -> C1[E]. Shared expression
subtrees become correlated holes; matching C0 against another expression carries
its own subtrees into C1. This is syntax evidence only. In particular, occurrence
counts are not effect counts, and lexical name reporting is not scope resolution.
The caller must establish type, binding, effect and oracle admissibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Mapping

from .terms import (BudgetExceeded, Hole, Node, Path, SourceTerm, Span, Term,
                    TRIVIA, from_source, match, render, substitute, subterms)


# Grammar categories, not library/API identities. Structural argument lists,
# declaration names, property names and type syntax cannot become carriers.
_EXPRESSIONS = frozenset({
    'identifier', 'integer', 'float', 'number', 'string', 'true', 'false', 'none',
    'nil', 'null', 'undefined', 'call', 'attribute', 'subscript', 'binary_operator',
    'boolean_operator', 'comparison_operator', 'unary_operator', 'not_operator',
    'lambda', 'list', 'dictionary', 'tuple', 'set', 'list_comprehension',
    'dictionary_comprehension', 'set_comprehension', 'generator_expression',
    'object', 'array', 'arrow_function', 'function_expression', 'template_string',
})
_NO_CARRIER_FIELDS = frozenset({
    'attribute', 'property', 'field', 'key', 'name',
    'type', 'parameters', 'parameter', 'label', 'operator',
})
_NO_READ_FIELDS = _NO_CARRIER_FIELDS - {'function', 'constructor', 'key'}
_CALLS = {'call', 'call_expression', 'new_expression'}
_ATTRS = {'attribute', 'member_expression', 'selector_expression'}


def _expression(term):
    return (isinstance(term, Term) and
            (term.kind in _EXPRESSIONS or term.kind.endswith(('_expression', '_literal'))))


def _pack(node):
    if isinstance(node, Hole):
        return {'hole': node.id, 'sort': node.sort}
    return {'kind': node.kind, 'atom': node.atom, 'children': [_pack(c) for c in node.children]}


def _unpack(value):
    if 'hole' in value:
        return Hole(value['sort'], value['hole'])
    return Term(value['kind'], value['atom'], tuple(_unpack(c) for c in value['children']))


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass
class _Input:
    term: Term
    spans: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)
    named: dict = field(default_factory=dict)
    path: str = ''
    declared_free: set | None = None

    def blocked(self, path, fields):
        return any(self.fields.get(path[:i]) in fields for i in range(1, len(path) + 1))

    def eligible(self, path, term):
        # A method receiver is a value carrier, while a bare/parenthesized
        # callee is not. This distinction uses grammar fields only.
        for depth in range(1, len(path) + 1):
            if self.fields.get(path[:depth]) in {'function', 'constructor'}:
                if not any(self.fields.get(path[:i]) in {'object', 'operand'}
                           for i in range(depth + 1, len(path) + 1)):
                    return False
        return (_expression(term) and self.named.get(path, True)
                and not self.blocked(path, _NO_CARRIER_FIELDS))

    def names(self, pattern=None):
        result = set()
        for path, node in subterms(self.term if pattern is None else pattern):
            if (isinstance(node, Term) and node.kind == 'identifier' and isinstance(node.atom, str)
                    and not self.blocked(path, _NO_READ_FIELDS)):
                result.add(node.atom)
        return result if self.declared_free is None else result & self.declared_free

    def provenance(self):
        span = self.spans.get(())
        return {'path': self.path, 'start_byte': span.start_byte if span else None,
                'end_byte': span.end_byte if span else None,
                'text': render(self.term), 'sha256': _digest(render(self.term))}


def _infer_fields(inp):
    """Recover only unambiguous grammar roles when SourceTerm lost field labels."""
    for path, node in subterms(inp.term):
        if not isinstance(node, Term):
            continue
        meaningful = [(i, c) for i, c in enumerate(node.children)
                      if isinstance(c, Term) and c.kind != TRIVIA]
        if node.kind in _CALLS and meaningful:
            inp.fields.setdefault(path + (meaningful[0][0],), 'function')
        if node.kind in _ATTRS and meaningful:
            inp.fields.setdefault(path + (meaningful[0][0],), 'object')
            inp.fields.setdefault(path + (meaningful[-1][0],), 'property')
        if node.kind in {'pair', 'keyed_element'} and meaningful:
            inp.fields.setdefault(path + (meaningful[0][0],), 'key')


def _coerce(value, max_nodes=512):
    if isinstance(value, Term):
        inp = _Input(value)
    elif isinstance(value, SourceTerm):
        inp = _Input(value.term, dict(value.spans), path=value.source_path)
    elif isinstance(value, tuple) and len(value) == 2:
        source, node = value
        converted = from_source(source, node, max_nodes=max_nodes)
        inp = _Input(converted.term, dict(converted.spans), path=converted.source_path)

        def metadata(current, path):
            inp.named[path] = current.is_named
            cursor = current.start_byte
            index = 0
            for i, child in enumerate(current.children):
                if child.start_byte > cursor:
                    index += 1
                child_path = path + (index,)
                inp.fields[child_path] = current.field_name_for_child(i)
                metadata(child, child_path)
                cursor = child.end_byte
                index += 1
        metadata(node, ())
    elif isinstance(value, Mapping) and 'ast' in value:
        ast, text = value['ast'], value['text']
        base = ast['start_byte']
        data = text.encode('utf-8')
        spans, fields, named = {}, {}, {}
        count = 0

        def convert(node, path):
            nonlocal count
            count += 1
            if count > max_nodes or len(path) > 256:
                raise BudgetExceeded('Context source conversion budget exceeded')
            start, end = node['start_byte'], node['end_byte']
            if not base <= start <= end <= base + len(data):
                raise ValueError('AST span falls outside expression text')
            spans[path] = Span(start, end)
            fields[path] = node.get('field')
            named[path] = node.get('is_named', True)
            children = node.get('children', [])
            if not children:
                return Term(node['kind'], data[start-base:end-base].decode('utf-8'))
            result, cursor = [], start
            for child in children:
                if child['start_byte'] < cursor or child['end_byte'] > end:
                    raise ValueError('Overlapping AST children')
                if cursor < child['start_byte']:
                    gap_path = path + (len(result),)
                    spans[gap_path] = Span(cursor, child['start_byte'])
                    named[gap_path] = False
                    result.append(Term(TRIVIA, data[cursor-base:child['start_byte']-base].decode('utf-8')))
                result.append(convert(child, path + (len(result),)))
                cursor = child['end_byte']
            if cursor < end:
                gap_path = path + (len(result),)
                spans[gap_path] = Span(cursor, end)
                named[gap_path] = False
                result.append(Term(TRIVIA, data[cursor-base:end-base].decode('utf-8')))
            return Term(node['kind'], None, tuple(result))

        inp = _Input(convert(ast, ()), spans, fields, named,
                     value.get('span', {}).get('path', ''),
                     set(value['free_identifiers']) if 'free_identifiers' in value else None)
        inp.fields.pop((), None)
    else:
        raise TypeError('Expected Term, SourceTerm, corpus expression, or (Source, node)')
    for _, node in subterms(inp.term, max_nodes=max_nodes):
        if isinstance(node, Hole):
            raise ValueError('Context learning/application expects ground terms')
    _infer_fields(inp)
    return inp


def _hole_paths(pattern):
    result = {}
    for path, node in subterms(pattern):
        if isinstance(node, Hole):
            result.setdefault(node, []).append(path)
    return result


@dataclass(frozen=True)
class AppliedContext:
    term: Term
    text: str
    bindings: Mapping[Hole, Term]
    provenance: dict
    unbound_free_names: tuple[str, ...]
    introduced_names: tuple[str, ...]

    def as_dict(self):
        return {'text': self.text, 'term': _pack(self.term), 'provenance': self.provenance,
                'unbound_free_names': list(self.unbound_free_names),
                'introduced_names': list(self.introduced_names),
                'bindings': [{'hole': h.id, 'text': render(t)} for h, t in self.bindings.items()]}


@dataclass(frozen=True)
class ContextEdit:
    before: Node
    after: Node
    source_bindings: tuple[tuple[Hole, Term], ...]
    source_before: dict
    source_after: dict
    required_names: tuple[str, ...]
    introduced_names: tuple[str, ...]
    max_nodes: int = 512

    @property
    def fingerprint(self):
        canonical = json.dumps([_pack(self.before), _pack(self.after)], sort_keys=True)
        return _digest(canonical)[:20]

    @property
    def edit_size(self):
        return sum(1 for pattern in (self.before, self.after)
                   for _, n in subterms(pattern) if isinstance(n, Term) and n.kind != TRIVIA)

    def as_dict(self):
        before_paths, after_paths = _hole_paths(self.before), _hole_paths(self.after)
        return {'kind': 'ast_context', 'before': _pack(self.before), 'after': _pack(self.after),
                'source_bindings': [{'hole': _pack(h), 'term': _pack(t)} for h, t in self.source_bindings],
                'source_before': self.source_before, 'source_after': self.source_after,
                'required_names': list(self.required_names), 'introduced_names': list(self.introduced_names),
                'max_nodes': self.max_nodes, 'fingerprint': self.fingerprint,
                'carrier_occurrences': [{'hole': h.id, 'before': [list(p) for p in before_paths[h]],
                                         'after': [list(p) for p in after_paths[h]],
                                         'count_changed': len(before_paths[h]) != len(after_paths[h])}
                                        for h, _ in self.source_bindings],
                'claim': 'syntactic_reconstruction_only',
                'binding_precision': 'lexical_reads; capture_and_scope_unresolved'}

    @classmethod
    def from_dict(cls, value):
        result = cls(_unpack(value['before']), _unpack(value['after']),
                     tuple((_unpack(b['hole']), _unpack(b['term'])) for b in value['source_bindings']),
                     value['source_before'], value['source_after'], tuple(value['required_names']),
                     tuple(value['introduced_names']), value['max_nodes'])
        result.check_reconstruction()
        if value.get('fingerprint', result.fingerprint) != result.fingerprint:
            raise ValueError('Context edit fingerprint mismatch')
        return result

    def check_reconstruction(self):
        subst = dict(self.source_bindings)
        for pattern, provenance in ((self.before, self.source_before), (self.after, self.source_after)):
            text = render(substitute(pattern, subst, max_nodes=self.max_nodes))
            if text != provenance['text'] or _digest(text) != provenance['sha256']:
                raise ValueError('Context edit does not reconstruct its source')
        if set(_hole_paths(self.before)) != set(subst) or set(_hole_paths(self.after)) != set(subst):
            raise ValueError('Each carrier must occur on both sides')

    def apply(self, target, *, available_names=(), max_nodes=None):
        limit = self.max_nodes if max_nodes is None else max_nodes
        inp = _coerce(target, limit)
        bindings = match(self.before, inp.term, max_nodes=limit)
        if bindings is None:
            return None
        paths = _hole_paths(self.before)
        if any(not inp.eligible(p, bindings[h]) for h in paths for p in paths[h]):
            return None
        result = substitute(self.after, bindings, max_nodes=limit)
        if result == inp.term:
            return None
        carriers = []
        for hole, term in bindings.items():
            occurrences = []
            for path in paths[hole]:
                span = inp.spans.get(path)
                occurrences.append({'path': list(path),
                                    'start_byte': span.start_byte if span else None,
                                    'end_byte': span.end_byte if span else None})
            carriers.append({'hole': hole.id, 'text': render(term), 'occurrences': occurrences})
        provenance = {'edit': self.fingerprint, 'source_before': self.source_before,
                      'source_after': self.source_after, 'target': inp.provenance(),
                      'carriers': carriers, 'claim': 'syntactic_reconstruction_only',
                      'binding_precision': 'lexical_reads; capture_and_scope_unresolved',
                      'carrier_occurrence_changes': [item for item in self.as_dict()['carrier_occurrences']
                                                     if item['count_changed']]}
        unbound = tuple(sorted(set(self.required_names) - inp.names() - set(available_names)))
        return AppliedContext(result, render(result), bindings, provenance, unbound, self.introduced_names)


def learn_context_edits(before, after, *, max_nodes=512, max_holes=8, max_candidates=16):
    """Mine bounded, deterministic shared-subtree context substitutions.

    The first candidate abstracts a maximal nonoverlapping set of common
    expression subtrees; subsequent candidates abstract one subtree each.
    Repeated equal subtrees share one hole. Results are not exhaustive when the
    candidate budget is reached. No execution or oracle inference occurs here.
    """
    if any(type(v) is not int or v < 1 for v in (max_nodes, max_holes, max_candidates)):
        raise ValueError('Context budgets must be positive integers')
    left, right = _coerce(before, max_nodes), _coerce(after, max_nodes)
    if left.term == right.term:
        return []

    def candidates(inp):
        values = {}
        for path, node in subterms(inp.term, max_nodes=max_nodes):
            if inp.eligible(path, node):
                values.setdefault(node, []).append(path)
        return values

    a, b = candidates(left), candidates(right)
    common = sorted(a.keys() & b.keys(), key=lambda t: (-sum(1 for _ in subterms(t)), a[t][0]))
    maximal = []
    for term in common:
        # Never pick overlapping carriers on either source side. This also
        # prevents a smaller common subtree from disappearing behind a hole.
        if any(any(term == n for _, n in subterms(outer))
               or any(outer == n for _, n in subterms(term)) for outer in maximal):
            continue
        maximal.append(term)
        if len(maximal) >= max_holes:
            break
    groups = ([maximal] if maximal else []) + [[term] for term in common]
    results, seen = [], set()
    for group in groups:
        group = sorted(group, key=lambda t: a[t][0])
        holes = {term: Hole('any', i) for i, term in enumerate(group)}
        # Abstract only eligible occurrences. Equal strings in callee/property
        # positions remain literal syntax, even when an argument has that name.
        def contextual(inp):
            def visit(term, path):
                if term in holes and inp.eligible(path, term):
                    return holes[term]
                return Term(term.kind, term.atom, tuple(visit(c, path + (i,))
                                                       for i, c in enumerate(term.children)))
            return visit(inp.term, ())
        p, q = contextual(left), contextual(right)
        if p == q or (p, q) in seen:
            continue
        seen.add((p, q))
        required = right.names(q)
        edit = ContextEdit(p, q, tuple((holes[t], t) for t in group),
                           left.provenance(), right.provenance(), tuple(sorted(required)),
                           tuple(sorted(required - left.names(p))), max_nodes)
        edit.check_reconstruction()
        results.append(edit)
        if len(results) >= max_candidates:
            break
    return results
