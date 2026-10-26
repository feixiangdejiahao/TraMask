cd /app && python3 - <<'PYEOF'
import glob
for path in glob.glob('src/schema/*/schema_.ts'):
    with open(path) as f:
        content = f.read()
    content = content.replace('  Validator\n  WithRequiredIf', '  Validator,\n  WithRequiredIf')
    with open(path, 'w') as f:
        f.write(content)
print("fixed")
PYEOF
npx tsc --noEmit 2>&1 | head -80