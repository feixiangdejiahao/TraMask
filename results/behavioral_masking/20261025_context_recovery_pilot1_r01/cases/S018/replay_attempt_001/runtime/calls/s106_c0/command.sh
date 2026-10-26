cd /app && python - <<'EOF'
path = 'bandit/core/manager.py'
src = open(path).read()
src = src.replace('import os\nimport re\nimport sys\nimport tokenize\nimport traceback\n', 'import os\nimport sys\nimport traceback\n')
# trim trailing blank lines to single newline
src = src.rstrip() + '\n'
open(path, 'w').write(src)
print('manager cleaned')
EOF
python -m flake8 bandit/core/manager.py bandit/core/nosec.py bandit/core/tester.py bandit/core/utils.py 2>&1 | head