cd /app && python3 - <<'PYEOF'
import re

files = {
    'any': ('AnySchema_', 'PROPS', 'new AnySchema_({props})'),
    'anyOf': ('AnyOfSchema_', 'PROPS', 'new AnyOfSchema_(this.elements, {props})'),
    'binary': ('BinarySchema_', 'PROPS', 'new BinarySchema_({props})'),
    'boolean': ('BooleanSchema_', 'PROPS', 'new BooleanSchema_({props})'),
    'list': ('ListSchema_', 'PROPS', 'new ListSchema_(this.elements, {props})'),
    'map': ('MapSchema_', 'PROPS', 'new MapSchema_(this.attributes, {props})'),
    'null': ('NullSchema_', 'PROPS', 'new NullSchema_({props})'),
    'number': ('NumberSchema_', 'PROPS', 'new NumberSchema_({props})'),
    'record': ('RecordSchema_', 'PROPS', 'new RecordSchema_(this.keys, this.elements, {props})'),
    'set': ('SetSchema_', 'PROPS', 'new SetSchema_(this.elements, {props})'),
    'string': ('StringSchema_', 'PROPS', 'new StringSchema_({props})'),
}

method_template = '''
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
  ): {CLASS}<{TYPEPARAMS}WithRequiredIf<PROPS, ATTRIBUTE_NAME, TRIGGER_VALUES>{TYPEARGS}> {
    return {CTOR}
  }
'''

for fname, (class_name, props_type, ctor_tpl) in files.items():
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

    # Determine return type params
    if class_name in ('ListSchema_', 'SetSchema_', 'AnyOfSchema_'):
        typ = f'ELEMENTS, '
    elif class_name == 'MapSchema_':
        typ = 'ATTRIBUTES, '
    elif class_name == 'RecordSchema_':
        typ = 'KEYS, ELEMENTS, '
    else:
        typ = ''
    type_args = '' if typ == '' else ', '

    # Find optional() method and its closing brace
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

    ctor = ctor_tpl.format(props="overwrite(this.props, {\n        requiredIf: mergeRequiredIf(this.props.requiredIf, attributeName, triggerValues)\n      })")
    method = method_template.format(
        CLASS=class_name,
        TYPEPARAMS=typ,
        TYPEARGS=type_args,
        CTOR=ctor
    )

    # Insert after close_idx
    lines[close_idx:close_idx+1] = [lines[close_idx], method]
    content = '\n'.join(lines)

    with open(path, 'w') as f:
        f.write(content)
    print(f"{fname}: done")
PYEOF