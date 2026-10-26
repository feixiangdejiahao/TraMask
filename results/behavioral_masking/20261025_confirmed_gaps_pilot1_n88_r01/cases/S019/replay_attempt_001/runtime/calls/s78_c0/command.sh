cd /app && for f in any anyOf binary boolean list map null number record set string; do sed -i 's/  Validator\n  WithRequiredIf/  Validator,\n  WithRequiredIf/' "src/schema/$f/schema_.ts"; done
# sed multiline won't work; use python
python3 - <<'PYEOF'
import glob
for path in glob.glob('src/schema/*/schema_.ts'):
    with open(path) as f:
        content = f.read()
    content = content.replace('  Validator\n  WithRequiredIf', '  Validator,\n  WithRequiredIf')
    with open(path, 'w') as f:
        f.write(content)
print("fixed")
PYEOF
sed -n '13,20p' src/schema/any/schema_.ts