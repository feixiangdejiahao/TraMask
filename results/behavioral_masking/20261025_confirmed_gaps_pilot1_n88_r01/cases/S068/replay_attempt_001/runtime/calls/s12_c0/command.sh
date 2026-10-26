python3 - <<'EOF'
import ast
src = open('sqlite_utils/db.py').read()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef) and not n.name.startswith('__')]
        print(node.name, ':', ', '.join(methods))
        print()
EOF