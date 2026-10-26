cd /app && cat > /tmp/bandit_repro/test_specific_statement_wide.py <<'EOF'
import subprocess
subprocess.Popen(
    'ls *',
    # nosec-begin B607
    shell=True,
    # nosec-end
)
EOF
python -m bandit -f json /tmp/bandit_repro/test_specific_statement_wide.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"