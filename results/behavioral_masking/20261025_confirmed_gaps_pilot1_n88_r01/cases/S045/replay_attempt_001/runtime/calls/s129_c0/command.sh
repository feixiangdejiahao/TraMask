cd /app/libs/core && python - <<'PY'
# Check for unused imports in coalesce.py (rough)
import ast, sys
tree = ast.parse(open('langchain_core/runnables/coalesce.py').read())
imports = []
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom):
        for a in node.names:
            imports.append((a.asname or a.name, node.lineno))
    elif isinstance(node, ast.Import):
        for a in node.names:
            imports.append((a.asname or a.name.split('.')[0], node.lineno))
names = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Name):
        names.add(node.id)
    if isinstance(node, ast.Attribute):
        pass
for name, lineno in imports:
    if name not in names and name != 'annotations':
        print("possibly unused:", name, lineno)
PY