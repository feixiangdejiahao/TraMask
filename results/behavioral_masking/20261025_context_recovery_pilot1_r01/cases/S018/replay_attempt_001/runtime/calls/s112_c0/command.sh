cd /app && python - <<'EOF'
path = 'bandit/core/nosec.py'
src = open(path).read()
old = '''_DIRECTIVE_PATTERN = re.compile(
    r"#\\s*nosec(?P<directive>-(?:begin|end|next-line))?"
    r"(?P<selector>[^#]*)",
    re.IGNORECASE,
)
'''
new = '''_DIRECTIVE_PATTERN = re.compile(
    r"#\\s*nosec(?P<directive>-(?:begin|end|next-line))?"
    r"(?![A-Za-z0-9_-])"
    r"(?P<selector>[^#]*)",
    re.IGNORECASE,
)
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("regex updated")
EOF
python - <<'EOF'
from bandit.core import nosec
EN = {"B602","B607"}
for c in ["# nosec-beginning", "# nosec-endpoint", "# nosec-begin", "# nosec-end", "# nosec-next-line B602"]:
    d = nosec.parse_directives(c, 1, EN)
    print(repr(c), [(x.type, x.suppression) for x in d])
EOF