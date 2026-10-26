cd /app && python - <<'EOF'
path = 'bandit/core/nosec.py'
src = open(path).read()
old = '''        if tree is not None:
            statement = _find_statement_at_line(tree, line_no)
            if statement is not None:
                # If the line is a continuation of a statement that began
                # before the directive, it is not the next statement.
                if statement.lineno < directive_line + 1:
                    continue
                return list(
                    range(statement.lineno, statement.end_lineno + 1)
                )
        return [line_no]
'''
new = '''        if tree is not None:
            statement = _find_statement_at_line(tree, line_no)
            if statement is None:
                # Decorator lines are not part of any AST statement node;
                # keep looking for the statement they decorate.
                continue
            # If the line is a continuation of a statement that began
            # before the directive, it is not the next statement.
            if statement.lineno < directive_line + 1:
                continue
            return list(
                range(statement.lineno, statement.end_lineno + 1)
            )
        return [line_no]
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("fixed")
EOF
python -m bandit -f json /tmp/bandit_repro/test_next_decorator.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"