# A structural limit of the lexical edit square

A lossless diff can reconstruct both source edits while missing their ordinary
nested composition. This was checked using only three invented source strings:

```python
A = "assert f(1) == 1"
B = "assert f([1]) == [1]"
C = "assert f((1,)) == (1,)"
```

Both source-reconstruction checks pass. The kernel applies one insertion order
at every shared position, producing these two syntactically invalid strings:

```python
assert f([(1],)) == [(1],)
assert f(([1,)]) == ([1,)]
```

The ordinary nested forms `assert f([(1,)]) == [(1,)]` and
`assert f(([1],)) == ([1],)` are absent. Opening and closing edits belonging to
one wrapper need coordinated nesting; treating them as independent insertions
with the same global order cannot express it. This is a representation limit,
not evidence about a particular library or experimental outcome.

Conversely, a syntactically valid, nonoverlapping merge does not establish
semantic independence. With initial `count = 0`, let A be `assert True`, let B
add `count += 1` before A, and let C add `assert count == 0` after A. All three
source tests can pass separately; their valid textual merge fails. Byte-exact
reconstruction proves edit provenance, not effect independence or oracle validity.
