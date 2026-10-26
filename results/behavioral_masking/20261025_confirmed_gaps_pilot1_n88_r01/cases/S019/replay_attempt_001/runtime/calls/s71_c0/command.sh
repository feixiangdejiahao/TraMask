cd /app && python3 - <<'PYEOF'
import re

for path in ['src/schema/item/schema.ts', 'src/schema/map/schema.ts']:
    with open(path) as f:
        content = f.read()
    content = content.replace(
        "import { checkSchemaProps } from '../utils/checkSchemaProps.js'",
        "import { checkSchemaProps } from '../utils/checkSchemaProps.js'\nimport { checkRequiredIf } from '../utils/checkRequiredIf.js'"
    )
    # Insert checkRequiredIf call after the attribute check loop and before freeze block.
    # The loop ends with:
    #   for (const [attributeName, attribute] of Object.entries(this.attributes)) {
    #     attribute.check(...)
    #   }
    # Then "Object.freeze(this.props)"
    content = content.replace(
        "    Object.freeze(this.props)",
        "    checkRequiredIf(this, path)\n\n    Object.freeze(this.props)"
    )
    with open(path, 'w') as f:
        f.write(content)
    print(f"{path}: updated")
PYEOF
grep -n "checkRequiredIf" src/schema/item/schema.ts src/schema/map/schema.ts