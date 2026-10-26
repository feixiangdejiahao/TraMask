cd /app && python - <<'EOF'
import ast
src = "import subprocess\n\n# nosec-next-line\n@decorator\ndef foo():\n    subprocess.Popen('ls *', shell=True)\n"
tree = ast.parse(src)
for n in ast.walk(tree):
    if isinstance(n, ast.stmt):
        print(type(n).__name__, n.lineno, n.end_lineno)
EOF