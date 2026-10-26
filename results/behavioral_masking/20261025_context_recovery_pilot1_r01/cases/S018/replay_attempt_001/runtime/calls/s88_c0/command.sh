cd /app && python - <<'EOF'
from bandit.core import nosec
source = "x = 1 + \\\n# nosec-next-line\n    2\nfoo()\n"
print(repr(source))
nl = nosec.build_nosec_lines(source.encode(), {"B602","B607"})
print(nl)
import ast
print(ast.dump(ast.parse(source), indent=2))
EOF