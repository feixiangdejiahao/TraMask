cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
# Remove all debug lines by reconstructing the file cleanly. We'll rewrite from scratch.
print("will rewrite")
PY