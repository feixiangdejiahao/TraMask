ls -la /app/*.py 2>/dev/null; find / -maxdepth 3 -name 'tube.py' 2>/dev/null | head; echo ---; python - <<'PY'
import sys
# Simulate: how does python -m doctest import?
print(sys.path[:3])
PY