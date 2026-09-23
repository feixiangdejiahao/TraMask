"""Immutable syntax terms and first-order anti-unification.

This module knows no API, library, test name, or semantic relation. Tree-sitter
conversion preserves punctuation and whitespace. Binding resolution belongs to
the caller: normalization is an explicit token callback or source-span mapping,
never an identifier-spelling heuristic. Matching establishes syntax, not oracle
validity, type correctness, purity, or equivalence of mutable objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Hashable, Iterator, Mapping, TypeAlias


DEFAULT_MAX_NODES = 20_000
DEFAULT_MAX_DEPTH = 256
DEFAULT_MAX_HOLES = 128
TRIVIA = "#trivia"
Path: TypeAlias = tuple[int, ...]


@dataclass(frozen=True, slots=True, eq=False)
class Term:
    kind: str
    atom: Hashable | None = None
    children: tuple["Node", ...] = ()

    def __post_init__(self):
        if not isinstance(self.kind, str):
            raise TypeError("Term kind must be a string")
        hash(self.atom)  # Reject mutable atoms instead of silently sharing them.
        object.__setattr__(self, "children", tuple(self.children))
        if any(not isinstance(child, (Term, Hole)) for child in self.children):
            raise TypeError("Term children must be Term or Hole instances")

    def __eq__(self, other):
        # Python considers True == 1 == 1.0. Syntax atoms keep their types.
        return (isinstance(other, Term) and self.kind == other.kind
                and type(self.atom) is type(other.atom) and self.atom == other.atom
                and self.children == other.children)

    def __hash__(self):
        return hash((self.kind, type(self.atom), self.atom, self.children))


@dataclass(frozen=True, slots=True)
class Hole:
    sort: str
    id: int | str

    def __post_init__(self):
        if not isinstance(self.sort, str) or type(self.id) not in (int, str):
            raise TypeError("A hole needs a string sort and an integer/string id")


Node: TypeAlias = Term | Hole
SortOf: TypeAlias = Callable[[Term], str]
Substitution: TypeAlias = Mapping[Hole, Node]


class BudgetExceeded(ValueError):
    """The deterministic size/depth/hole budget was exceeded."""


@dataclass(frozen=True, slots=True)
class Span:
    start_byte: int
    end_byte: int


@dataclass(frozen=True, slots=True)
class SourceTerm:
    term: Term
    spans: Mapping[Path, Span] = field(compare=False, hash=False, repr=False)
    source_path: str = field(default="", compare=False, hash=False)
    original_text: str = field(default="", compare=False, hash=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "spans", MappingProxyType(dict(self.spans)))


@dataclass(frozen=True, slots=True)
class AntiUnification:
    pattern: Node
    left_subst: Substitution
    right_subst: Substitution

    def __post_init__(self):
        object.__setattr__(self, "left_subst", MappingProxyType(dict(self.left_subst)))
        object.__setattr__(self, "right_subst", MappingProxyType(dict(self.right_subst)))

    def __iter__(self):
        yield self.pattern
        yield self.left_subst
        yield self.right_subst


def _limits(max_nodes: int, max_depth: int):
    if type(max_nodes) is not int or max_nodes < 1:
        raise ValueError("max_nodes must be a positive integer")
    if type(max_depth) is not int or max_depth < 0:
        raise ValueError("max_depth must be a nonnegative integer")


def subterms(term: Node, *, max_nodes: int = DEFAULT_MAX_NODES,
             max_depth: int = DEFAULT_MAX_DEPTH) -> Iterator[tuple[Path, Node]]:
    """Yield every occurrence in deterministic preorder, including the root.

    Node limits count occurrences, not unique objects in a shared DAG. Exhaust
    this iterator to validate a complete term; its prefixes are not validation.
    """
    _limits(max_nodes, max_depth)
    pending = [((), term)]
    count = 0
    while pending:
        path, node = pending.pop()
        if not isinstance(node, (Term, Hole)):
            raise TypeError("Expected a Term or Hole")
        count += 1
        if count > max_nodes or len(path) > max_depth:
            raise BudgetExceeded("Term size/depth budget exceeded")
        yield path, node
        if isinstance(node, Term):
            pending.extend((path + (i,), child) for i, child in reversed(list(enumerate(node.children))))


def _check(term: Node, max_nodes: int, max_depth: int):
    for _ in subterms(term, max_nodes=max_nodes, max_depth=max_depth):
        pass


def from_source(source, node=None, *, normalize=None,
                normalization_map: Mapping[tuple[int, int], str] | None = None,
                max_nodes: int = DEFAULT_MAX_NODES,
                max_depth: int = DEFAULT_MAX_DEPTH) -> SourceTerm:
    """Convert a Source/tree-sitter node without discarding any source tokens.

    ``source`` provides ``data`` (UTF-8 bytes), ``root`` and optionally ``path``.
    ``normalize(node, raw_text)`` can return a replacement string, or None to
    retain the token. Alternatively supply a mapping of exact byte spans to
    replacement strings. Only leaves are normalized; maps targeting non-leaves
    or nonexistent spans fail explicitly. No identifiers are selected for the
    caller, so attribute names and strings change only if explicitly requested.
    Render returns normalized code; ``original_text`` always retains the input.
    """
    _limits(max_nodes, max_depth)
    if normalize is not None and normalization_map is not None:
        raise ValueError("Choose normalization callback or span map, not both")
    root = source.root if node is None else node
    data = source.data
    if not isinstance(data, bytes):
        raise TypeError("Source data must be UTF-8 bytes")
    positions: dict[Path, Span] = {}
    supplied = dict(normalization_map or {})
    consumed = set()
    count = 0

    def record(path, start, end):
        nonlocal count
        count += 1
        if count > max_nodes or len(path) > max_depth:
            raise BudgetExceeded("Source conversion size/depth budget exceeded")
        positions[path] = Span(start, end)

    def convert(current, path):
        start, end = current.start_byte, current.end_byte
        record(path, start, end)
        children = list(current.children)  # Includes punctuation/anonymous nodes.
        if not children:
            raw = data[start:end].decode("utf-8")
            key = (start, end)
            atom = supplied.get(key, raw)
            if key in supplied:
                consumed.add(key)
            elif normalize is not None:
                replacement = normalize(current, raw)
                atom = raw if replacement is None else replacement
            if not isinstance(atom, str):
                raise TypeError("Source token normalization must return str or None")
            return Term(current.type, atom)
        result = []
        cursor = start
        for child in children:
            if child.start_byte < cursor or child.end_byte > end:
                raise ValueError("Overlapping or out-of-range source children")
            if child.start_byte > cursor:
                child_path = path + (len(result),)
                record(child_path, cursor, child.start_byte)
                result.append(Term(TRIVIA, data[cursor:child.start_byte].decode("utf-8")))
            result.append(convert(child, path + (len(result),)))
            cursor = child.end_byte
        if cursor < end:
            child_path = path + (len(result),)
            record(child_path, cursor, end)
            result.append(Term(TRIVIA, data[cursor:end].decode("utf-8")))
        return Term(current.type, None, tuple(result))

    term = convert(root, ())
    if supplied.keys() - consumed:
        raise ValueError("Normalization map contains spans that are not leaf tokens")
    return SourceTerm(term, positions, getattr(source, "path", ""),
                      data[root.start_byte:root.end_byte].decode("utf-8"))


def render(term: Node, *, max_nodes: int = DEFAULT_MAX_NODES,
           max_depth: int = DEFAULT_MAX_DEPTH) -> str:
    """Concatenate leaves. An unbound hole cannot be rendered as source code."""
    output = []
    for _, node in subterms(term, max_nodes=max_nodes, max_depth=max_depth):
        if isinstance(node, Hole):
            raise ValueError(f"Cannot render unbound hole {node.id!r}")
        if node.children:
            if node.atom is not None:
                raise ValueError("A renderable internal term must have atom=None")
        elif node.atom is not None:
            output.append(str(node.atom))
    return "".join(output)


def _sort(term: Node, sort_of: SortOf | None) -> str:
    return term.sort if isinstance(term, Hole) else sort_of(term) if sort_of else term.kind


def anti_unify(left: Term, right: Term, *, sort_of: SortOf | None = None,
               max_nodes: int = DEFAULT_MAX_NODES,
               max_depth: int = DEFAULT_MAX_DEPTH,
               max_holes: int = DEFAULT_MAX_HOLES) -> AntiUnification:
    """Least general first-order skeleton of two ground syntax terms.

    Equal mismatch pairs share a hole everywhere. Different syntax kinds use
    sort 'any' unless the external sort function gives them a common sort.
    Size/depth limits apply to each input and output, not to the corpus size.
    """
    if type(max_holes) is not int or max_holes < 0:
        raise ValueError("max_holes must be a nonnegative integer")
    for term in (left, right):
        for _, node in subterms(term, max_nodes=max_nodes, max_depth=max_depth):
            if isinstance(node, Hole):
                raise ValueError("anti_unify expects ground terms")
    mismatches: dict[tuple[Term, Term], Hole] = {}
    left_subst, right_subst = {}, {}

    def generalize(a, b):
        if a == b:
            return a
        if a.kind == b.kind and type(a.atom) is type(b.atom) and a.atom == b.atom and len(a.children) == len(b.children):
            return Term(a.kind, a.atom, tuple(generalize(x, y) for x, y in zip(a.children, b.children)))
        pair = (a, b)
        if pair not in mismatches:
            if len(mismatches) >= max_holes:
                raise BudgetExceeded("Anti-unification hole budget exceeded")
            sa, sb = _sort(a, sort_of), _sort(b, sort_of)
            hole = Hole(sa if sa == sb else "any", len(mismatches))
            mismatches[pair] = hole
            left_subst[hole], right_subst[hole] = a, b
        return mismatches[pair]

    pattern = generalize(left, right)
    _check(pattern, max_nodes, max_depth)
    return AntiUnification(pattern, left_subst, right_subst)


def match(pattern: Node, term: Term, *, sort_of: SortOf | None = None,
          max_nodes: int = DEFAULT_MAX_NODES,
          max_depth: int = DEFAULT_MAX_DEPTH) -> dict[Hole, Node] | None:
    """Match syntax and repeated-hole equality; no binder/type inference."""
    _check(pattern, max_nodes, max_depth)
    for _, node in subterms(term, max_nodes=max_nodes, max_depth=max_depth):
        if isinstance(node, Hole):
            raise ValueError("match expects a ground subject term")
    result = {}
    pending = [(pattern, term)]
    while pending:
        p, t = pending.pop()
        if isinstance(p, Hole):
            if p.sort != "any" and p.sort != _sort(t, sort_of):
                return None
            if p in result and result[p] != t:
                return None
            result[p] = t
        else:
            if p.kind != t.kind or type(p.atom) is not type(t.atom) or p.atom != t.atom or len(p.children) != len(t.children):
                return None
            pending.extend(reversed(list(zip(p.children, t.children))))
    return result


def substitute(pattern: Node, substitutions: Substitution, *, strict: bool = True,
               max_nodes: int = DEFAULT_MAX_NODES,
               max_depth: int = DEFAULT_MAX_DEPTH) -> Node:
    """Simultaneous substitution. Inserted terms are not substituted again.

    This is deliberately a syntactic operation. The caller must resolve and
    alpha-rename bindings before grafting code, and validate its scope interface.
    """
    _check(pattern, max_nodes, max_depth)
    for hole, replacement in substitutions.items():
        if not isinstance(hole, Hole):
            raise TypeError("Substitution keys must be Hole instances")
        _check(replacement, max_nodes, max_depth)

    def apply(node):
        if isinstance(node, Hole):
            if node in substitutions:
                return substitutions[node]
            if strict:
                raise KeyError(node)
            return node
        return Term(node.kind, node.atom, tuple(apply(child) for child in node.children))

    result = apply(pattern)
    _check(result, max_nodes, max_depth)
    return result


def at(term: Node, path: Path) -> Node:
    node = term
    for index in path:
        if type(index) is not int or index < 0 or not isinstance(node, Term) or index >= len(node.children):
            raise IndexError(path)
        node = node.children[index]
    return node


def replace_at(term: Node, path: Path, replacement: Node, *,
               max_nodes: int = DEFAULT_MAX_NODES,
               max_depth: int = DEFAULT_MAX_DEPTH) -> Node:
    """Replace one occurrence, preserving all other children and token atoms."""
    _check(term, max_nodes, max_depth)
    _check(replacement, max_nodes, max_depth)
    at(term, path)  # Validate even empty/invalid replacement paths.
    ancestors = []
    current = term
    for index in path:
        ancestors.append((current, index))
        current = current.children[index]
    result = replacement
    for parent, index in reversed(ancestors):
        children = list(parent.children)
        children[index] = result
        result = Term(parent.kind, parent.atom, tuple(children))
    _check(result, max_nodes, max_depth)
    return result


def context_at(term: Node, path: Path, hole: Hole | None = None, **limits) -> Node:
    """Return the context with one occurrence replaced by the specified hole."""
    carrier = at(term, path)
    if hole is None:
        hole = Hole(_sort(carrier, None), 0)
        if any(node == hole for _, node in subterms(term, **limits)):
            raise ValueError("Default context hole already occurs; supply a fresh hole")
    return replace_at(term, path, hole, **limits)


@dataclass(frozen=True, slots=True)
class BindingInterface:
    """Lexical symbols identified externally, after intended interface renaming."""
    free: frozenset[str] = frozenset()
    bound: frozenset[str] = frozenset()

    def __post_init__(self):
        object.__setattr__(self, "free", frozenset(self.free))
        object.__setattr__(self, "bound", frozenset(self.bound))


class CaptureError(ValueError):
    pass


def check_capture(interface: BindingInterface, *, available=(),
                  surrounding_bound=(), context_free=()) -> None:
    """Check caller-supplied scope facts; this does not discover/rename binders.

    ``surrounding_bound`` are binders crossed when entering the hole, excluding
    intended interface bindings; ``context_free`` are context references that
    newly inserted declarations could capture. The caller handles language
    scope rules and supplies facts for the actual insertion site.
    """
    missing = interface.free - frozenset(available)
    captured_donor = interface.free & frozenset(surrounding_bound)
    captured_context = interface.bound & frozenset(context_free)
    if missing or captured_donor or captured_context:
        raise CaptureError(f"missing={sorted(missing)}, donor_capture={sorted(captured_donor)}, "
                           f"context_capture={sorted(captured_context)}")
