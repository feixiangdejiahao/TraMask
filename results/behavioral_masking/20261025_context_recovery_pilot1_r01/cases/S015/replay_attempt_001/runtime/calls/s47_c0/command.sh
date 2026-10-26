cd /app && rm -rf /tmp/cachetest/.cache && printf 'import os\nos.system("ls")\n' > /tmp/cachetest/foo.py
python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache -f txt 2>/dev/null | grep -E "Issue:|Files" 
echo "--- modify ---"
printf 'import subprocess\nsubprocess.call("ls", shell=True)\n' > /tmp/cachetest/foo.py
python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache --verbose -f txt 2>/dev/null | grep -E "Files cached|Files scanned|Invalidation|Issue:"
echo "--- cached run ---"
python -m bandit /tmp/cachetest/foo.py --incremental --cache-dir /tmp/cachetest/.cache --verbose -f txt 2>/dev/null | grep -E "Files cached|Files scanned|Invalidation|Issue:"