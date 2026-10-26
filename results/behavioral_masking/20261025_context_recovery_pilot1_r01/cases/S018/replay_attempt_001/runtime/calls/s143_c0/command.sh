cd /app && cat > /tmp/bandit_repro/test_colon_empty.py <<'EOF'
import subprocess
subprocess.Popen('ls *', shell=True)  # nosec:
EOF
python -m bandit -f json /tmp/bandit_repro/test_colon_empty.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"