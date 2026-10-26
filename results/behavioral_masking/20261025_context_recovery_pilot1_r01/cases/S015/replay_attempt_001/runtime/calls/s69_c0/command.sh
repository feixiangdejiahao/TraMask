cd /app && python - <<'PY'
path='tests/functional/test_incremental.py'
lines=open(path).read().splitlines(keepends=True)
lines[203]='        proc = self._run(\n'
lines.insert(204,'            "--import-cache", export_file,\n')
lines.insert(205,'            "--cache-dir", new_cache,\n')
lines.insert(206,'        )\n')
open(path,'w').writelines(lines)
PY
python - <<'PY'
fn='tests/functional/test_incremental.py'
for i, line in enumerate(open(fn),1):
    if len(line.rstrip('\n'))>79:
        print(i, len(line.rstrip()))
PY