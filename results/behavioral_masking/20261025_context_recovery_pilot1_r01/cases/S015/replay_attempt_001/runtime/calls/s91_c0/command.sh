cd /app && rm -rf /tmp/final && mkdir -p /tmp/final && printf 'import os\nos.system("ls")\n' > /tmp/final/a.py
bandit /tmp/final/a.py --incremental --cache-dir /tmp/final/cache -f json --exit-zero 2>/dev/null >/tmp/final1.json
bandit /tmp/final/a.py --incremental --cache-dir /tmp/final/cache -f json --exit-zero 2>/dev/null >/tmp/final2.json
python -c "import json; d1=json.load(open('/tmp/final1.json')); d2=json.load(open('/tmp/final2.json')); print('run1:', d1['cache_info']['cache_hits'], d1['cache_info']['cache_misses']); print('run2:', d2['cache_info']['cache_hits'], d2['cache_info']['cache_misses'])"
bandit --cache-summary --cache-dir /tmp/final/cache 2>/dev/null
bandit --list-cached-files --cache-dir /tmp/final/cache 2>/dev/null
bandit --cache-stats --cache-dir /tmp/final/cache 2>/dev/null
bandit --export-cache /tmp/final/export.json --cache-dir /tmp/final/cache 2>/dev/null && python -c "import json; print('export format_version:', json.load(open('/tmp/final/export.json'))['format_version'])"
bandit --clear-cache --cache-dir /tmp/final/cache 2>/dev/null; echo "clear exit=$?"
bandit --cache-summary --cache-dir /tmp/final/cache 2>/dev/null