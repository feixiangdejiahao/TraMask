cd /app && mkdir -p /tmp/circtest && cat > /tmp/circtest/a.py <<'EOF'
import b
b.something()
EOF
cat > /tmp/circtest/b.py <<'EOF'
import a
def something():
    return 1
EOF
cat > /tmp/circtest/c.py <<'EOF'
import b
b.something()
EOF
rm -rf /tmp/circtest/.cache
echo "=== run1 ==="
python -m bandit /tmp/circtest --incremental --cache-dir /tmp/circtest/.cache -r -f json 2>/dev/null > /tmp/circ1; python -c "import json; d=json.load(open('/tmp/circ1')); print(d['cache_info'])"
echo "=== run2 (all unchanged, all cached) ==="
timeout 30 python -m bandit /tmp/circtest --incremental --cache-dir /tmp/circtest/.cache -r -f json 2>/dev/null > /tmp/circ2; echo "exit=$?"; python -c "import json; d=json.load(open('/tmp/circ2')); print(d['cache_info'])"
echo "=== modify b.py ==="
printf 'import a\n\ndef something():\n    return 2\n' > /tmp/circtest/b.py
timeout 30 python -m bandit /tmp/circtest --incremental --cache-dir /tmp/circtest/.cache -r -f json 2>/dev/null > /tmp/circ3; echo "exit=$?"; python -c "import json; d=json.load(open('/tmp/circ3')); print(d['cache_info'])"