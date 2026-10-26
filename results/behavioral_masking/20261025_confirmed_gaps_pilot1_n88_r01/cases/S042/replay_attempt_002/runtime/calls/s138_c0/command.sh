cd /app && python3 - <<'PY'
# README
p='README.md'
s=open(p).read()
s=s.replace("""\u003e Tracking modifiers do not accept pairs directly such as `Changed(ChildOf(parent))`. Instead, pass the base relation to the modifier and add the pair as a separate query parameter to filter by target.
""", """\u003e Tracking modifiers accept pairs directly. Pass `ChildOf(parent)` (or `ChildOf('*')` for any target) to track a specific relation pair. The base relation form tracks trait-level changes, while the pair form tracks per-target changes.
""")
s=s.replace("""// Filter changed entities by a specific target
const changedChildren = world.query(Changed(ChildOf), ChildOf(parent))""", """// Track changes to a specific relation pair
const changedChildren = world.query(Changed(ChildOf(parent)))

// Wildcard tracks changes to any pair
const anyChangedChildren = world.query(Changed(ChildOf('*')))""")
open(p,'w').write(s)

# docs/api/relations.md
p='docs/api/relations.md'
s=open(p).read()
s=s.replace("""\u003e Tracking modifiers do not accept pairs directly such as `Changed(ChildOf(parent))`. Instead, pass the base relation to the modifier and add the pair as a separate query parameter to filter by target.
""", """\u003e Tracking modifiers accept pairs directly. Pass `ChildOf(parent)` (or `ChildOf('*')` for any target) to track a specific relation pair. The base relation form tracks trait-level changes, while the pair form tracks per-target changes.
""")
s=s.replace("""// Filter changed entities by a specific target
const changedChildren = world.query(Changed(ChildOf), ChildOf(parent))""", """// Track changes to a specific relation pair
const changedChildren = world.query(Changed(ChildOf(parent)))

// Wildcard tracks changes to any pair
const anyChangedChildren = world.query(Changed(ChildOf('*')))""")
open(p,'w').write(s)
print('done')
PY
grep -n "Tracking modifiers accept pairs\|anyChangedChildren" README.md docs/api/relations.md