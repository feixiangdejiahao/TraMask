cd /app && python3 - <<'PYEOF'
path = 'src/schema/actions/dto/types.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import type { AtLeastOnce, SchemaRequiredProp } from '~/schema/index.js'",
    "import type { AtLeastOnce, RequiredIfValue, SchemaRequiredProp } from '~/schema/index.js'"
)
content = content.replace(
    "interface SchemaPropsDTO extends SchemaDefaultsDTO, SchemaLinksDTO {\n  required?: SchemaRequiredProp\n  hidden?: boolean\n  key?: boolean\n  savedAs?: string\n}",
    "interface SchemaPropsDTO extends SchemaDefaultsDTO, SchemaLinksDTO {\n  required?: SchemaRequiredProp\n  requiredIf?: RequiredIfValue\n  hidden?: boolean\n  key?: boolean\n  savedAs?: string\n}"
)
with open(path, 'w') as f:
    f.write(content)
print("done")
PYEOF
grep -n "requiredIf" src/schema/actions/dto/types.ts