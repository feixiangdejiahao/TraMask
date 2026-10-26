cd /app && cat > /tmp/bandit_repro/test_next_multiline.py <<'EOF'
import subprocess
# nosec-next-line
subprocess.Popen(
    'ls *',
    shell=True,
)
EOF
python -m bandit -f json /tmp/bandit_repro/test_next_multiline.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"