cd /app && mkdir -p /tmp/cachetest && cat > /tmp/cachetest/foo.py <<'EOF'
import os
os.system("ls")
EOF
echo "=== First run ===" && python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache -f json 2>&1 | python -c "import sys,json; d=json.load(sys.stdin); print('cache_info:', d['cache_info']); print('metrics:', d['metrics']['_totals']['cache_hits'], d['metrics']['_totals']['cache_misses'])"
echo "=== Second run ===" && python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache -f json 2>&1 | python -c "import sys,json; d=json.load(sys.stdin); print('cache_info:', d['cache_info']); print('metrics:', d['metrics']['_totals']['cache_hits'], d['metrics']['_totals']['cache_misses'])"
echo "=== cache summary ===" && python -m bandit --cache-summary --cache-dir /tmp/cachetest/.cache 2>&1
echo "=== list ===" && python -m bandit --list-cached-files --cache-dir /tmp/cachetest/.cache 2>&1
echo "=== stats ===" && python -m bandit --cache-stats --cache-dir /tmp/cachetest/.cache 2>&1