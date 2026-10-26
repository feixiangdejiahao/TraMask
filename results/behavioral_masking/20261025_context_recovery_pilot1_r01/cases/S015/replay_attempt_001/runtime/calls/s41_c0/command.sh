cd /app && rm -rf /tmp/cachetest/.cache && python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache -f json 2>/dev/null > /tmp/out1; python -c "import json; d=json.load(open('/tmp/out1')); print('run1 cache_info:', d['cache_info'])"
python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache -f json 2>/dev/null > /tmp/out2; python -c "import json; d=json.load(open('/tmp/out2')); print('run2 cache_info:', d['cache_info'])"
# Modify file
printf 'import os\nos.system("id")\n' > /tmp/cachetest/foo.py
python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache -f json 2>/dev/null > /tmp/out3; python -c "import json; d=json.load(open('/tmp/out3')); print('run3 (modified) cache_info:', d['cache_info'])"
# Second time unchanged after modification
python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache -f json 2>/dev/null > /tmp/out4; python -c "import json; d=json.load(open('/tmp/out4')); print('run4 cache_info:', d['cache_info'])"