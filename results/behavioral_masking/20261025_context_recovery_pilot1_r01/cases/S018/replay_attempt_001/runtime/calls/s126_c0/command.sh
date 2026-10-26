cd /app && cat > /tmp/bandit_repro/test_profile_enabled.py <<'EOF'
import subprocess
# nosec-next-line !B602
subprocess.Popen('ls *', shell=True)
EOF
cat > /tmp/bandit_repro/profile.yaml <<'EOF'
profile:
    include:
        - B602
        - B607
EOF
cd /app && python -m bandit -c /tmp/bandit_repro/profile.yaml -f json /tmp/bandit_repro/test_profile_enabled.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"