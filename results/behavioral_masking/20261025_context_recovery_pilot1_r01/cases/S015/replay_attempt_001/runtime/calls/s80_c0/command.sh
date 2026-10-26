cd /app && python - <<'PY'
path = 'bandit/core/manager.py'
src = open(path).read()
old = '''        files_to_scan = []
        cached_scores = {}
        path_to_fname = {}
        fname_to_path = {}

        for fname in self.files_list:
            path = os.path.abspath(fname)
            path_to_fname[path] = fname
            fname_to_path[fname] = path
'''
new = '''        files_to_scan = []
        cached_scores = {}
        fname_to_path = {}

        for fname in self.files_list:
            fname_to_path[fname] = os.path.abspath(fname)
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/core/manager.py && echo OK