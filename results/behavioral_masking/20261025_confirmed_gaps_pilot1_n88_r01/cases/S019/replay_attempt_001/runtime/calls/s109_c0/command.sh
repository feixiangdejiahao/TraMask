cd /app && python3 - <<'PYEOF'
import re

files = [
    'src/schema/actions/dto/getSchemaDTO/any.ts',
    'src/schema/actions/dto/getSchemaDTO/anyOf.ts',
    'src/schema/actions/dto/getSchemaDTO/list.ts',
    'src/schema/actions/dto/getSchemaDTO/map.ts',
    'src/schema/actions/dto/getSchemaDTO/primitive.ts',
    'src/schema/actions/dto/getSchemaDTO/record.ts',
    'src/schema/actions/dto/getSchemaDTO/set.ts',
]

for path in files:
    with open(path) as f:
        content = f.read()

    # add requiredIf to destructure
    # pattern: const { required, hidden, key, savedAs
    content = re.sub(
        r"const \{ required, hidden, key, savedAs",
        "const { required, requiredIf, hidden, key, savedAs",
        content,
        count=1
    )
    # primitive uses "const { required, hidden, key, savedAs, transform } = props"
    content = re.sub(
        r"const \{ required, hidden, key, savedAs, transform \} = props",
        "const { required, requiredIf, hidden, key, savedAs, transform } = props",
        content,
        count=1
    )

    # add requiredIf spread after required spread
    content = content.replace(
        "    ...(required !== undefined && required !== 'atLeastOnce' ? { required } : {}),\n",
        "    ...(required !== undefined && required !== 'atLeastOnce' ? { required } : {}),\n    ...(requiredIf !== undefined ? { requiredIf } : {}),\n",
        1
    )

    with open(path, 'w') as f:
        f.write(content)
    print(f"{path}: updated")
PYEOF
grep -n "requiredIf" src/schema/actions/dto/getSchemaDTO/*.ts | grep -v unit