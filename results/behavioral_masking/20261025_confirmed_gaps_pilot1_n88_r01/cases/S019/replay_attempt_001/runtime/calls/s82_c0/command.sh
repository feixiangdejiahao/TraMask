cd /app && git checkout -- src/schema/anyOf/schema_.ts src/schema/list/schema_.ts src/schema/map/schema_.ts src/schema/set/schema_.ts && python3 - <<'PYEOF'
import re

# Restore only the four malformed files, redo for all to be safe
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

# class names that have a second type parameter before PROPS
multi_classes = {'AnyOfSchema_', 'ListSchema_', 'MapSchema_', 'SetSchema_', 'RecordSchema_'}

for fname, class_name in files.items():
    path = f'src/schema/{fname}/schema_.ts'
    with open(path) as f:
        content = f.read()

    # If already correct (has ELEMENTS/ATTRIBUTES/KEYS in return), skip insertion
    if 'WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>' in content:
        # check if it's a valid multi-param or single-param
        if class_name in multi_classes:
            if class_name == 'RecordSchema_' and 'RecordSchema_<KEYS, ELEMENTS, WithRequiredIf' in content:
                print(f"{fname}: already correct")
                continue
            if class_name != 'RecordSchema_' and f'{class_name}<ELEMENTS, WithRequiredIf' in content:
                print(f"{fname}: already correct")
                continue
            if class_name == 'MapSchema_' and 'MapSchema_<ATTRIBUTES, WithRequiredIf' in content:
                print(f"{fname}: already correct")
                continue
        else:
            print(f"{fname}: already correct")
            continue
        # else fall through to fix

    # Remove any existing requiredIf method block to re-insert cleanly
    # (for files that were restored, none exist; for safety handle existing)
    lines = content.split('\n')
    new_lines = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith('requiredIf<'):
            # skip until method closing brace at 2-space indent
            while i < len(lines):
                if lines[i].strip() == '}' and (i == 0 or lines[i].startswith('  }')):
                    break
                i += 1
            i += 1
            continue
        new_lines.append(lines[i])
        i += 1
    content = '\n'.join(new_lines)

    # Add WithRequiredIf to type import block (only if not already present)
    if '  WithRequiredIf\n' not in content:
        content, n_type = re.subn(
            r"(\} from '../types/index\.js'\n)",
            r"  WithRequiredIf\n\1",
            content,
            count=1
        )
        assert n_type == 1, f"{fname}: type import insert failed"

    # Add runtime import after the type import block (only if not already present)
    if "import { mergeRequiredIf } from '../types/index.js'\n" not in content:
        content = content.replace(
            "} from '../types/index.js'\n",
            "} from '../types/index.js'\nimport { mergeRequiredIf } from '../types/index.js'\n",
            1
        )

    if class_name == 'RecordSchema_':
        return_type = 'RecordSchema_<KEYS, ELEMENTS, WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'
    elif class_name in multi_classes:
        second_type = 'ATTRIBUTES' if class_name == 'MapSchema_' else 'ELEMENTS'
        return_type = f'{class_name}<{second_type}, WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'
    else:
        return_type = f'{class_name}<WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>>'

    if class_name == 'RecordSchema_':
        ctor = ('new RecordSchema_(this.keys, this.elements, overwrite(this.props, {\n'
                '        requiredIf: mergeRequiredIf(this.props.requiredIf, attributeName, triggerValues)\n'
                '      }))')
    elif class_name in multi_classes:
        second = 'this.attributes' if class_name == 'MapSchema_' else 'this.elements'
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