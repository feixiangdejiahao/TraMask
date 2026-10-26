cd /app && cat > /tmp/bandit_repro/test_case_insensitive.py <<'EOF'
import subprocess
# NOSEC-BEGIN
subprocess.Popen('ls *', shell=True)
# NOSEC-END this text is ignored
subprocess.Popen('ls *', shell=True)
# nosec-NEXT-LINE
subprocess.Popen('ls *', shell=True)
EOF
python -m bandit -f json /tmp/bandit_repro/test_case_insensitive.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"