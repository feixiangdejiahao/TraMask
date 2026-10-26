cd /app && python - <<'PY'
path = 'bandit/core/manager.py'
src = open(path).read()

old = '''                if entry.get("skipped"):
                    # Restore the skipped status but keep the file out of the
                    # active file list, matching non-incremental behavior.
                    self.skipped.append(
                        (fname, entry.get("skip_reason") or "cached skipped")
                    )
                    self.files_cached.append(fname)
                    self.cache_hits += 1
                    paths_to_remove.append(fname)
'''
new = '''                if entry.get("skipped"):
                    # Restore the skipped status but keep the file out of the
                    # active file list, matching non-incremental behavior.
                    self.skipped.append(
                        (fname, entry.get("skip_reason") or "cached skipped")
                    )
                    metrics_data = entry.get("metrics")
                    if isinstance(metrics_data, dict):
                        self.metrics.data[fname] = metrics_data
                    self.files_cached.append(fname)
                    self.cache_hits += 1
                    paths_to_remove.append(fname)
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/core/manager.py && echo OK