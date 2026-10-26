cd /app && python3 - <<'PYEOF'
p='CHANGELOG.md'
s=open(p).read()
s=s.replace("# v12.0.5\n", "# Unreleased\n\n- Add support for asynchronous initialization of container registrations with automatic dependency-aware startup ordering (`container.initialize()`, resolver `initializer()`)\n\n# v12.0.5\n")
open(p,'w').write(s)
print('changelog updated')
PYEOF
head -8 CHANGELOG.md