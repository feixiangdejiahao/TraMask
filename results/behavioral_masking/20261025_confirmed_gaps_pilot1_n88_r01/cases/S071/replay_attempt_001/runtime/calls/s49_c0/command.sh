cd /app && python3 - <<'PYEOF'
path = 'src/index.ts'
with open(path) as f:
    src = f.read()
old = "export { SuperJSON, SuperJSONResult, SuperJSONValue };"
new = "export { SuperJSON, SuperJSONResult, SuperJSONValue, ErrorStackOptions };"
assert old in src
src = src.replace(old, new)
with open(path, 'w') as f:
    f.write(src)
print('updated')
PYEOF
npm run build 2>&1 | tail -20