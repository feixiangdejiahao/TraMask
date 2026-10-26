cd /app && python - <<'EOF'
path = 'bandit/core/nosec.py'
src = open(path).read()
old = '''        line_suppressions = [
            suppression for _, suppression in active_regions
        ]
        for directive in directives:
            if directive.type == "nosec":
                line_suppressions.append(directive.suppression)
        combined = combine_suppressions(line_suppressions)
        if combined is not None:
            nosec_lines[lineno] = combined
'''
new = '''        line_suppressions = [
            suppression for _, suppression in active_regions
        ]
        for directive in directives:
            if directive.type == "nosec":
                line_suppressions.append(directive.suppression)
        combined = combine_suppressions(line_suppressions)
        if combined is not None:
            existing = nosec_lines.get(lineno)
            nosec_lines[lineno] = combine_suppressions(
                [existing, combined]
            )
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("fixed")
EOF
cat > /tmp/bandit_repro/test_next_region_combine.py <<'EOF'
import subprocess
# nosec-begin B607
# nosec-next-line B602
subprocess.Popen('ls *', shell=True)
# nosec-end
EOF
python -m bandit -f json /tmp/bandit_repro/test_next_region_combine.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"