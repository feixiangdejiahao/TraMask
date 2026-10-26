cd /app && cat > /tmp/bandit_repro/test_nested_blanket.py <<'EOF'
import subprocess
# nosec-begin
# nosec-begin B602
subprocess.Popen('ls *', shell=True)
# nosec-end
# nosec-end
EOF
python -m bandit -f json /tmp/bandit_repro/test_nested_blanket.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"