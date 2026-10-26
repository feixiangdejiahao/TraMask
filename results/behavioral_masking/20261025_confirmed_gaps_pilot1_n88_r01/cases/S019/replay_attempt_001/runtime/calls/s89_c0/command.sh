cd /app && python3 - <<'PYEOF'
import re

files = {
    'any': 'AnySchema_',
    'anyOf': 'AnyOfSchema_',
    'binary': 'BinarySchema_',
    'boolean': 'BooleanSchema_',
    'list': 'ListSchema_',
    'map': 'MapSchema_',
    'null': 'NullSchema_',
    'number': 'NumberSchema_',
    'record': 'RecordSchema_',
    'set': 'SetSchema_',
    'string': 'StringSchema_',
}

multi_classes = {'AnyOfSchema_', 'ListSchema_', 'MapSchema_', 'SetSchema_', 'RecordSchema_'}

for fname, class_name in files.items():
    path = f'src/schema/{fname}/schema_.ts'
    with open(path) as f:
        content = f.read()

    # 1. Fix type import: ensure last list item has comma then add WithRequiredIf
    # Find the "} from '../types/index.js'" block and add WithRequiredIf + comma
    # We'll replace "\n} from '../types/index.js'" with "\n  WithRequiredIf\n} from '../types/index.js'"
    content, n = re.subn(
        r"(\n\} from '../types/index\.js'\n)",
        r"\n  WithRequiredIf\n} from '../types/index.js'\n",
        content,
        count=1
    )
    assert n == 1, f"{fname}: type import block not found"
    # Now ensure comma before WithRequiredIf if the previous token has no comma
    content = content.replace('Validator\n  WithRequiredIf', 'Validator,\n  WithRequiredIf')
    content = content.replace('SchemaRequiredProp\n  WithRequiredIf', 'SchemaRequiredProp,\n  WithRequiredIf')

    # 2. Add runtime import
    content = content.replace(
        "} from '../types/index.js'\n",
        "} from '../types/index.js'\nimport { mergeRequiredIf } from '../types/index.js'\n",
        1
    )

    # 3. Build method
    if class_name == 'RecordSchema_':
        return_type = 'RecordSchema_<KEYS, ELEMENTS, WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'
    elif class_name in multi_classes:
        second_type = 'ATTRIBUTES' if class_name == 'MapSchema_' else 'ELEMENTS'
        return_type = f'{class_name}<{second_type}, WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'
    else:
        return_type = f'{class_name}<WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'

    if class_name == 'RecordSchema_':
        ctor = ('new RecordSchema_(this.keys, this.elements, overwrite(this.props, {\n'
                '          requiredIf: mergeRequiredIf(this.props.requiredIf, attributeName, triggerValues)\n'
                '        }))')
    elif class_name in multi_classes:
        second = 'this.attributes' if class_name == 'MapSchema_' else 'this.elements'
        ctor = (f'new {class_name}({second}, overwrite(this.props, {{\n'
                '          requiredIf: mergeRequiredIf(this.props.requiredIf, attributeName, triggerValues)\n'
                '        }))')
    else:
        ctor = ('new ' + class_name + '(overwrite(this.props, {\n'
                '        requiredIf: mergeRequiredIf(this.props.requiredIf, attributeName, triggerValues)\n'
                '      }))')

    method = f'''
  /**
   * Declare the attribute as required when a sibling attribute matches one of
   * the provided trigger values.
   *
   * Chainable with OR semantics.
   *
   * @param attributeName Sibling attribute name
   * @param triggerValues Values that trigger the requirement
   */
  requiredIf<ATTRIBUTE_NAME extends string, TRIGGER_VALUES extends unknown[]>(
    attributeName: ATTRIBUTE_NAME,
    ...triggerValues: TRIGGER_VALUES
  ): {return_type} {{
    return {ctor} as unknown as {return_type}
  }}
'''

    lines = content.split('\n')
    opt_idx = None
    for i, line in enumerate(lines):
        if re.search(r'^\s+optional\(\):', line):
            opt_idx = i
            break
    assert opt_idx is not None, f"{fname}: optional() not found"

    close_idx = None
    for i in range(opt_idx, len(lines)):
        if lines[i].strip() == '}':
            close_idx = i
            break
    assert close_idx is not None, f"{fname}: closing brace not found"

    lines[close_idx:close_idx+1] = [lines[close_idx], method]
    content = '\n'.join(lines)

    with open(path, 'w') as f:
        f.write(content)
    print(f"{fname}: done")
PYEOF