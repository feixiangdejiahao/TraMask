cd /app && cat > /tmp/bandit_repro/test_selectors2.py <<'EOF'
import subprocess

# nosec-next-line (B602 | B607) & !B607
subprocess.Popen('ls *', shell=True)

# nosec-next-line all - B607
subprocess.Popen('ls *', shell=True)

# nosec-begin (B607 - B607)
subprocess.Popen('ls *', shell=True)
# nosec-end
subprocess.Popen('ls *', shell=True)
EOF
python -m bandit -f json /tmp/bandit_repro/test_selectors2.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"