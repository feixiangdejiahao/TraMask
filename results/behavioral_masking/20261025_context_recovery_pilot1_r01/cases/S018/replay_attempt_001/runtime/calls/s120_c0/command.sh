cd /app && cat > /tmp/bandit_repro/test_multi_same_line.py <<'EOF'
import subprocess
# nosec-begin B602 # nosec-begin B607
subprocess.Popen('ls *', shell=True)
# nosec-end # nosec-end
subprocess.Popen('ls *', shell=True)
EOF
python -m bandit -f json /tmp/bandit_repro/test_multi_same_line.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"