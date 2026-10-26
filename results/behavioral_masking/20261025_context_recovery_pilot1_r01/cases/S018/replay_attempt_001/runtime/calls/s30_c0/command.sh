cd /app && mkdir -p /tmp/bandit_repro && cat > /tmp/bandit_repro/test_nosec_directives.py <<'EOF'
# nosec-begin
import subprocess
subprocess.Popen('/bin/ls *', shell=True)
# nosec-end
subprocess.Popen('/bin/ls *', shell=True)

# nosec-next-line
subprocess.Popen('/bin/ls *', shell=True)

# nosec-next-line B602
subprocess.Popen('/bin/ls *', shell=True)

# nosec-begin B607
subprocess.Popen('/bin/ls *', shell=True)
# nosec-end
subprocess.Popen('/bin/ls *', shell=True)
EOF
cd /app && python -m bandit -f json /tmp/bandit_repro/test_nosec_directives.py 2>&1 | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"