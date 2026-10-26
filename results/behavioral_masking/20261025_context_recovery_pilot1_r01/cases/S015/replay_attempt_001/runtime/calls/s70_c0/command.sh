cd /app && python - <<'PY'
path = 'bandit/core/cache.py'
src = open(path).read()
old = '''        while self.entries and os.path.getsize(self.cache_path) > self.size_limit:
'''
new = '''        while (
            self.entries
            and os.path.getsize(self.cache_path) > self.size_limit
        ):
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)

path = 'bandit/core/manager.py'
src = open(path).read()
old = '''                score["CONFIDENCE"][conf_idx] += b_constants.RANKING_VALUES[conf]
'''
new = '''                score["CONFIDENCE"][conf_idx] += (
                    b_constants.RANKING_VALUES[conf]
                )
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python - <<'PY'
for fn in ['bandit/core/cache.py','bandit/core/manager.py']:
    bad=[]
    for i,line in enumerate(open(fn),1):
        if len(line.rstrip('\n'))>79:
            bad.append((i,len(line.rstrip())))
    print(fn,bad)
PY