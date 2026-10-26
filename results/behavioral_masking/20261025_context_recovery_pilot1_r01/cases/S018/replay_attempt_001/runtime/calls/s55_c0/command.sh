cd /app && cat > /tmp/bandit_repro/test_misc.py <<'EOF'
import subprocess

# nosec-none
subprocess.Popen('ls *', shell=True)

# nosec-begin B602 &  # unparseable fallback -> union B602
subprocess.Popen('ls *', shell=True)
# nosec-end

# nosec-begin # nosec-end
subprocess.Popen('ls *', shell=True)

# nosec-end unmatched
EOF
python -m bandit -f json /tmp/bandit_repro/test_misc.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"