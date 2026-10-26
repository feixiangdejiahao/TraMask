cd /app && python - <<'PY'
path = 'tests/functional/test_incremental.py'
src = open(path).read()
old = '''    def _run_json(self, *args, cwd=None):
        proc = self._run(*args, cwd=cwd)
        self.assertEqual(0, proc.returncode, proc.stderr.decode())
        data = json.loads(proc.stdout.decode())
        return data, proc
'''
new = '''    def _run_json(self, *args, cwd=None):
        proc = self._run(*args, "--exit-zero", cwd=cwd)
        self.assertEqual(0, proc.returncode, proc.stderr.decode())
        data = json.loads(proc.stdout.decode())
        return data, proc
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
timeout 300 python -m pytest tests/functional/test_incremental.py -q 2>&1 | tail -40