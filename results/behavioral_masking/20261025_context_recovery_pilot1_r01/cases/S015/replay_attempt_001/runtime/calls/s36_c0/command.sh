cd /app && python - <<'PY'
path = 'bandit/cli/main.py'
src = open(path).read()
old = "from bandit.core import config as b_config\n"
new = "from bandit.core import cache as b_cache\nfrom bandit.core import config as b_config\n"
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
grep -n "import cache" bandit/cli/main.py