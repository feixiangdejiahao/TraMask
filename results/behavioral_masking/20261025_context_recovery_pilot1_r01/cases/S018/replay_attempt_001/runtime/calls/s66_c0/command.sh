cd /app && cat > /tmp/bandit_repro/test_combine.py <<'EOF'
import subprocess
# nosec-begin B607
subprocess.Popen('ls *', shell=True) # nosec B602
# nosec-end
subprocess.Popen('ls *', shell=True)
EOF
python -m bandit -f json /tmp/bandit_repro/test_combine.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"