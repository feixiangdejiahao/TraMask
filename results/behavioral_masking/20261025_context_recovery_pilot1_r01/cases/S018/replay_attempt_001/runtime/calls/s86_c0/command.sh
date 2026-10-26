cd /app && python - <<'EOF'
path = 'bandit/core/nosec.py'
src = open(path).read()
old = '''# A line consisting solely of these characters is skipped when locating the
# target statement of a # nosec-next-line directive.
_NEXT_LINE_SKIP_RE = re.compile(rb"^[\\(\\)\\[\\]\\{\\};.\\s]*$")
'''
new = '''# A line consisting solely of these characters is skipped when locating the
# target statement of a # nosec-next-line directive.
_NEXT_LINE_SKIP_RE = re.compile(r"^[\\(\\)\\[\\]\\{\\};.\\s]*$")
'''
assert old in src
src = src.replace(old, new)

old = '''    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith(b"#"):
        return True
    return bool(_NEXT_LINE_SKIP_RE.fullmatch(stripped))
'''
new = '''    stripped = line.strip()
    if not stripped:
        return True
    if isinstance(stripped, bytes):
        stripped = stripped.decode("latin-1")
    if stripped.startswith("#"):
        return True
    return bool(_NEXT_LINE_SKIP_RE.fullmatch(stripped))
'''
assert old in src
src = src.replace(old, new)

old = '''    except (tokenize.TokenError, IndentationError):
        pass

    try:
        tree = ast.parse(data)
    except SyntaxError:
        tree = None
'''
new = '''    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass

    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError):
        tree = None
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("updated")
EOF
python -m testtools.run tests.unit.core.test_nosec tests.functional.test_functional 2>&1 | tail -6