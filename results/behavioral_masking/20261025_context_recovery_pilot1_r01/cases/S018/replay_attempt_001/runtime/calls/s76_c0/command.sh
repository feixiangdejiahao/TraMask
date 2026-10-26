cd /app && cat > examples/nosec-directives.py <<'EOF'
import subprocess

# nosec-begin
subprocess.Popen('ls *', shell=True)
subprocess.Popen('ls *', shell=True)
# nosec-end

subprocess.Popen('ls *', shell=True)

# nosec-next-line B602
subprocess.Popen('ls *', shell=True)

# nosec-begin B607
subprocess.Popen('ls *', shell=True)
# nosec-end

# nosec-next-line
subprocess.Popen('ls *', shell=True)
EOF
cd /app && python -m bandit -f json examples/nosec-directives.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"