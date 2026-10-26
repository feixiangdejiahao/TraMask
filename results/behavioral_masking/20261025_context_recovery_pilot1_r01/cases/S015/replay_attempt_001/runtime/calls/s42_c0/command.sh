cd /app && rm -rf /tmp/cachetest/.cache
echo "=== force-rescan (no incremental) ==="
python -m bandit /tmp/cachetest/foo.py --force-rescan --cache-dir /tmp/cachetest/.cache -f json 2>/tmp/force_err >/tmp/force_out; echo "exit=$?"; grep -i "force-rescan" /tmp/force_err; echo "cache dir exists: $(test -d /tmp/cachetest/.cache && echo yes || echo no)"
echo "=== warm-cache ==="
rm -rf /tmp/cachetest/.cache
python -m bandit /tmp/cachetest/foo.py --warm-cache --cache-dir /tmp/cachetest/.cache -f json >/tmp/warm_out 2>/tmp/warm_err; echo "exit=$?"; echo "stdout bytes: $(wc -c < /tmp/warm_out)"; echo "stderr:"; cat /tmp/warm_err; echo "cached files: $(python -m bandit --cache-summary --cache-dir /tmp/cachetest/.cache 2>/dev/null)"
echo "=== cache summary no-op clear ==="
python -m bandit --clear-cache --cache-dir /tmp/nonexistent-cache 2>&1; echo "exit=$?"
echo "=== export/import ==="
python -m bandit --export-cache /tmp/exported.json --cache-dir /tmp/cachetest/.cache 2>/dev/null; echo "export exit=$?"; head -20 /tmp/exported.json
rm -rf /tmp/cachetest/.cache2
python -m bandit --import-cache /tmp/exported.json --cache-dir /tmp/cachetest/.cache2 2>&1; echo "import exit=$?"; python -m bandit --cache-summary --cache-dir /tmp/cachetest/.cache2 2>/dev/null