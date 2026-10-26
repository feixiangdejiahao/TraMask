cd /app && cat > /tmp/cachetest/bandit.yaml <<'EOF'
incremental_analysis:
    enabled: true
    cache_directory: /tmp/cachetest/conf_cache
    cache_expiry_days: 0
EOF
rm -rf /tmp/cachetest/conf_cache
echo "=== config enabled, expiry 0 -> run1 miss, run2 expired -> miss ==="
python -m bandit /tmp/cachetest/foo.py -c /tmp/cachetest/bandit.yaml -f json 2>/dev/null >/tmp/c1; python -c "import json; d=json.load(open('/tmp/c1')); print('run1', d['cache_info'])"
python -m bandit /tmp/cachetest/foo.py -c /tmp/cachetest/bandit.yaml -f json 2>/dev/null >/tmp/c2; python -c "import json; d=json.load(open('/tmp/c2')); print('run2', d['cache_info'])"
echo "=== verbose output ==="
python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache --verbose -f txt 2>/dev/null | grep -E "Files cached|Files scanned|Invalidation"
echo "=== force-rescan with incremental ==="
python -m bandit /tmp/cachetest/foo.py --incremental --force-rescan --cache-dir /tmp/cachetest/.cache -f json 2>/dev/null >/tmp/fr; python -c "import json; d=json.load(open('/tmp/fr')); print('force-rescan', d['cache_info'])"
python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache -f json 2>/dev/null >/tmp/fr2; python -c "import json; d=json.load(open('/tmp/fr2')); print('after force', d['cache_info'])"