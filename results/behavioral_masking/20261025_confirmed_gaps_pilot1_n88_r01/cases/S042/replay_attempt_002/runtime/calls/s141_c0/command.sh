cd /app && python3 - <<'PY'
# queries.md: add pair mention
p='skills/koota/references/queries.md'
s=open(p).read()
s=s.replace("""// Track relation additions
const newChildren = world.query(Added(ChildOf))
```""", """// Track relation additions
const newChildren = world.query(Added(ChildOf))

// Track a specific relation pair (wildcard '*' matches any pair)
const childrenOfParent = world.query(Added(ChildOf(parent)))
```""")
s=s.replace("""// Track orphaned entities
const orphaned = world.query(Removed(ChildOf))
```""", """// Track orphaned entities
const orphaned = world.query(Removed(ChildOf))

// Track removal of a specific pair
const removedFromParent = world.query(Removed(ChildOf(parent)))
```""")
s=s.replace("""// Track relation data changes
const updatedChildren = world.query(Changed(ChildOf))
```""", """// Track relation data changes
const updatedChildren = world.query(Changed(ChildOf))

// Track changes to a specific pair
const updatedFromParent = world.query(Changed(ChildOf(parent)))
```""")
open(p,'w').write(s)

# relations.md: add subsection under Querying Relations
p='skills/koota/references/relations.md'
s=open(p).read()
marker="""### Combined queries

```typescript
// Enemies targeting the player
const threats = world.query(IsEnemy, Targeting(player))
"""
insert="""### Tracking relation pairs

Tracking modifiers accept relation pairs directly for per-target reactivity:

```typescript
const Added = createAdded()
const Removed = createRemoved()
const Changed = createChanged()

// Specific pair
world.query(Added(ChildOf(parent)))

// Any pair
world.query(Removed(ChildOf('*')))

// Per-target data changes
world.query(Changed(Contains(gold)))
```

### Combined queries

```typescript
// Enemies targeting the player
const threats = world.query(IsEnemy, Targeting(player))
"""
assert marker in s
s=s.replace(marker, insert)
open(p,'w').write(s)
print('skills updated')
PY
grep -n "Tracking relation pairs\|childrenOfParent" skills/koota/references/queries.md skills/koota/references/relations.md