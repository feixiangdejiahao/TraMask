cd /app && head -20 pwnlib/tubes/mux.py && python - <<'EOF'
import ast
t=ast.parse(open('pwnlib/tubes/mux.py').read())
imports=[n.names[0].name for n in ast.walk(t) if isinstance(n, ast.Import)]
froms=[]
for n in ast.walk(t):
    if isinstance(n, ast.ImportFrom):
        for a in n.names: froms.append(a.name)
print("imports", imports, "froms", froms)
EOF