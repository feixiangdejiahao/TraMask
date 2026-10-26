cd /app && python - <<'PY'
import re
path = 'bandit/core/manager.py'
src = open(path).read()

# Add ast, time imports after collections
src = src.replace(
    "import collections\nimport fnmatch",
    "import ast\nimport collections\nimport fnmatch\nimport time",
    1
)

# Add cache import
src = src.replace(
    "from bandit.core import constants as b_constants\n",
    "from bandit.core import cache as b_cache\nfrom bandit.core import constants as b_constants\n",
    1
)

open(path, 'w').write(src)
PY
sed -n '1,20p' bandit/core/manager.py