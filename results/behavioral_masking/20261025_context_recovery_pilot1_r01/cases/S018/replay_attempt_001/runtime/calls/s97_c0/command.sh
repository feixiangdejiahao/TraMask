cd /app && python - <<'EOF'
from bandit.core import nosec, manager
src = b"import subprocess\n\n# nosec-next-line\n@decorator\ndef foo():\n    subprocess.Popen('ls *', shell=True)\n"
lines = src.splitlines()
tree = nosec._find_statement_at_line(__import__('ast').parse(src), 4)
print("tree at 4:", tree)
print("next:", nosec._next_statement_lines(lines, 3, __import__('ast').parse(src)))
EOF