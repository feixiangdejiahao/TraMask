cd /app && python - <<'EOF'
path = 'bandit/core/nosec.py'
src = open(path).read()
old = '''    for match in _DIRECTIVE_PATTERN.finditer(comment):
        directive = match.group("directive")
        selector_text = match.group("selector").strip()
        if selector_text.startswith(":"):
            selector_text = selector_text[1:].strip()

        if directive == "-end":
            # Extra text after nosec-end is ignored.
            directives.append(Directive("end", line, Suppression.none()))
            continue

        if directive == "-begin":
            type_ = "begin"
        elif directive == "-next-line":
            type_ = "next_line"
        else:
            type_ = "nosec"
'''
new = '''    for match in _DIRECTIVE_PATTERN.finditer(comment):
        directive = match.group("directive")
        if directive is not None:
            directive = directive.lower()
        selector_text = match.group("selector").strip()
        if selector_text.startswith(":"):
            selector_text = selector_text[1:].strip()

        if directive == "-end":
            # Extra text after nosec-end is ignored.
            directives.append(Directive("end", line, Suppression.none()))
            continue

        if directive == "-begin":
            type_ = "begin"
        elif directive == "-next-line":
            type_ = "next_line"
        else:
            type_ = "nosec"
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("fixed")
EOF
python -m bandit -f json /tmp/bandit_repro/test_case_insensitive.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"