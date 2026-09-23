# Reconstruction is insufficient to identify a new oracle

Consider three existing tests over Boolean-valued inputs:

```python
# A
assert f(0, 0) == 0
# B
assert f(1, 0) == 1
# C
assert f(0, 1) == 1
```

Two deterministic functions satisfy exactly these same tests:

```python
def arithmetic_sum(x, y):
    return x + y

def inclusive_or(x, y):
    return x + y - x * y
```

For the combination input D, `(1, 1)`, the first function requires expected
value `2` and the second requires `1`. The input changes and all three source
tests are identical in both worlds. Their exact reconstruction therefore cannot
decide which assertion to attach to D.

More generally, let S be the finite set of observed inputs and let d be a new
input outside S. If the output domain contains two values, two deterministic
functions can agree on every input in S and differ at d. This claim concerns
finite examples without an additional semantic restriction; an independent
specification or a justified function-class assumption can distinguish them.
It does not claim that all program analysis or oracle generation is impossible.

## Copying the implementation can copy its defect

Now suppose the independent requirement explicitly says that `f` returns the
arithmetic sum, while the implementation under repair is:

```python
def f(x, y):
    return x + y - x * y  # Defect relative to the sum requirement.
```

The three existing tests still pass. Symbolically evaluating this implementation
at `(1, 1)`, or running it once to record a constant expected value, both produce:

```python
assert f(1, 1) == 1
```

This new test accepts the defective implementation and rejects the correct sum
implementation. Writing `expected = f(1, 1)` inside the generated test makes the
same circular oracle explicit. Source availability and deterministic execution
do not provide an independent correctness criterion.

An independently specified expected-value calculation, such as `x + y` under
the stated sum requirement, is different: its authority comes from that
requirement, not from copying the implementation being checked. Thus source
reconstruction certifies provenance; oracle validity still needs additional
contract evidence and remains a separate evaluation question.

All examples above are invented; this note uses no repository or experiment
outcome and proposes no additional generation kernel.
