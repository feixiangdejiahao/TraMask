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

# return type params
multi = {'anyOf', 'list', 'map', 'set', 'record'}

for fname, class_name in files.items():
    path = f'src/schema/{fname}/schema_.ts'
    with open(path) as f:
        content = f.read()

    # Add WithRequiredIf to type import block
    content, n_type = re.subn(
        r"(\} from '../types/index\.js'\n)",
        r"  WithRequiredIf\n\1",
        content,
        count=1
    )
    assert n_type == 1, f"{fname}: type import insert failed"

    # Add runtime import after the type import block
    content = content.replace(
        "} from '../types/index.js'\n",
        "} from '../types/index.js'\nimport { mergeRequiredIf } from '../types/index.js'\n",
        1
    )

    # Build return type
    if class_name == 'RecordSchema_':
        return_type = 'RecordSchema_<KEYS, ELEMENTS, WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'
    elif class_name in multi:
        second = 'ELEMENTS' if class_name != 'MapSchema_' else 'ATTRIBUTES'
        return_type = f'{class_name}<{second}, WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'
    else:
        return_type = f'{class_name}<WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'

    # Build constructor
    if class_name == 'RecordSchema_':
        ctor = ('new RecordSchema_(this.keys, this.elements, overwrite(this.props, {\n'
                '        requiredIf: mergeRequiredIf(this.props.requiredIf, attributeName, triggerValues)\n'
                '      }))')
    elif class_name in multi:
        second = 'this.elements' if class_name != 'MapSchema_' else 'this.attributes'
        ctor = (f'new {class_name}({second}, overwrite(this.props, {{\n'
                '        requiredIf: mergeRequiredIf(this.props.requiredIf, attributeName, triggerValues)\n'
                '      }))')
    else:
        ctor = ('new ' + class_name + '(overwrite(this.props, {\n'
                '      requiredIf: mergeRequiredIf(this.props.requiredIf, attributeName, triggerValues)\n'
                '    }))')

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
    return {ctor}
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