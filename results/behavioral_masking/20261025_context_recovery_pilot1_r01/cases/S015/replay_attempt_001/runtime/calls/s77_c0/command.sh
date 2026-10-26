cd /app && mkdir -p /tmp/syntaxtest && cat > /tmp/syntaxtest/bad.py <<'EOF'
def broken(:
    pass
EOF
rm -rf /tmp/syntaxtest/.cache
echo "=== run1 ==="
python -m bandit /tmp/syntaxtest/bad.py --incremental --cache-dir /tmp/syntaxtest/.cache -f txt 2>/dev/null | grep -E "Files skipped|syntax"
echo "=== run2 ==="
python -m bandit /tmp/syntaxtest/bad.py --incremental --cache-dir /tmp/syntaxtest/.cache -f txt 2>/dev/null | grep -E "Files skipped|syntax"
echo "=== json run2 ==="
python -m bandit /tmp/syntaxtest/bad.py --incremental --cache-dir /tmp/syntaxtest/.cache -f json --exit-zero 2>/dev/null >/tmp/synjson; python -c "import json; d=json.load(open('/tmp/synjson')); print(d['cache_info']); print(d['errors'])"