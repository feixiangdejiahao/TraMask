cd /app && cat > docs/partial.md <<'MDEOF'
# Partial Structuring

Sometimes you want to structure data that is incomplete.
_cattrs_ provides {meth}`BaseConverter.partial_structure <cattrs.BaseConverter.partial_structure>` and the top-level {func}`cattrs.partial_structure` for this purpose.

These methods work on _attrs_ classes, dataclasses and TypedDicts, and return a {class}`cattrs.PartialResult`.

```{versionadded} 25.4.0

```

## PartialResult

A {class}`cattrs.PartialResult` has the following attributes:

- `value` - the partially structured value, or `None` if a value cannot be created.
- `is_complete` - whether all fields were structured successfully.
- `structured_fields` - a frozenset of the field names successfully structured from the input.
- `failed_fields` - a frozenset of the field names that were not structured.
- `errors` - an exception describing the failures, or `None`.
- `error_map` - a mapping of field names to the exceptions raised while structuring them.

Fields absent from the input are considered failed, not structured.
Failed fields with defaults use those defaults as fallbacks; required fields without defaults prevent a value from being created (the value will be `None`).

Nested _attrs_ classes, dataclasses and TypedDicts are structured recursively.
If a nested object is only partially complete, its partial value is used and the parent field is marked as failed.
Collection fields (`List`, `Dict`, ...) are structured atomically: any element failure fails the whole field.

## Refinement

The {meth}`PartialResult.refine <cattrs.PartialResult.refine>` method returns a new `PartialResult`, fixing failed fields with new data while preserving already-structured fields.

```python
from attrs import define
from cattrs import Converter

@define
class Product:
    name: str
    price: int
    description: str = ""

c = Converter()

result = c.partial_structure({"name": "Apple", "price": 3}, Product)
# result.value == Product("Apple", 3)
# result.is_complete == False
# result.failed_fields == frozenset({"description"})

result = result.refine({"description": "A red apple"})
# result.value == Product("Apple", 3, "A red apple")
# result.is_complete == True
```
MDEOF
python - <<'EOF'
path='docs/index.md'
s=open(path).read()
old='''usage\nmigrations
indepth
```
'''
new='''usage
migrations
partial
indepth
```
'''
assert old in s
open(path,'w').write(s.replace(old,new))
print("docs index updated")
EOF
git status --short