cd /app && cat > /tmp/bandit_repro/test_name_selector.py <<'EOF'
import subprocess
# nosec-begin subprocess_popen_with_shell_equals_true
subprocess.Popen('ls *', shell=True)
# nosec-end
EOF
python -m bandit -f json /tmp/bandit_repro/test_name_selector.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"