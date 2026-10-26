cd /app && python - <<'PY'
for fn in ['tests/functional/test_functional.py','tests/functional/test_runtime.py','tests/unit/cli/test_main.py']:
    n=0
    for i,line in enumerate(open(fn),1):
        if len(line.rstrip('\n'))>79:
            n+=1
    print(fn, n)
PY