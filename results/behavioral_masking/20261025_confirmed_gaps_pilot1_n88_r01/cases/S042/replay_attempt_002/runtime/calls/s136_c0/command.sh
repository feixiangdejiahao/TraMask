cd /app && python3 - <<'PY'
# README
p='README.md'
s=open(p).read()
old="""\u003e \ud83d\udc49 **Note**\u003cbr\u003e
\u003e Tracking modifiers do not accept pairs directly such as `Changed(ChildOf(parent))`. Instead, pass the base relation to the modifier and add the pair as a separate query parameter to filter by target.

```js
const parent = world.spawn()

// Filter changed entities by a specific target
const changedChildren = world.query(Changed(ChildOf), ChildOf(parent))
```"""
new="""\u003e \ud83d\udc49 **Note**\u003cbr\u003e
\u003e Tracking modifiers accept pairs directly. Pass `ChildOf(parent)` (or `ChildOf('*')` for any target) to track a specific relation pair. The base relation form tracks trait-level changes, while the pair form tracks per-target changes.

```js
const parent = world.spawn()

// Track changes to a specific relation pair
const changedChildren = world.query(Changed(ChildOf(parent)))

// Wildcard tracks changes to any pair
const anyChangedChildren = world.query(Changed(ChildOf('*')))
```"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)

# docs/api/relations.md
p='docs/api/relations.md'
s=open(p).read()
old="""\u003e [!IMPORTANT]  \n\u003e Tracking modifiers do not accept pairs directly such as `Changed(ChildOf(parent))`. Instead, pass the base relation to the modifier and add the pair as a separate query parameter to filter by target.


```js
const parent = world.spawn()

// Filter changed entities by a specific target
const changedChildren = world.query(Changed(ChildOf), ChildOf(parent))
```"""
new="""\u003e [!IMPORTANT]  \n\u003e Tracking modifiers accept pairs directly. Pass `ChildOf(parent)` (or `ChildOf('*')` for any target) to track a specific relation pair. The base relation form tracks trait-level changes, while the pair form tracks per-target changes.


```js
const parent = world.spawn()

// Track changes to a specific relation pair
const changedChildren = world.query(Changed(ChildOf(parent)))

// Wildcard tracks changes to any pair
const anyChangedChildren = world.query(Changed(ChildOf('*')))
```"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('docs updated')
PY
grep -n "Tracking modifiers accept pairs\|ChildOf('*')" README.md docs/api/relations.md