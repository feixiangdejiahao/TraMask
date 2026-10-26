cd /app && mkdir -p /tmp/badcache && echo '{"format_version": 999, "entries": {}}' > /tmp/badcache/cache.json
python -m bandit --cache-summary --cache-dir /tmp/badcache 2>/dev/null
echo "--- list empty ---"
mkdir -p /tmp/emptycache && python -m bandit --list-cached-files --cache-dir /tmp/emptycache 2>/dev/null; echo "exit=$?"
echo "--- stats missing dir ---"
python -m bandit --cache-stats --cache-dir /tmp/nodir 2>/dev/null