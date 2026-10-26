cd /app && python3 - <<'PYEOF'
import glob, re

for path in glob.glob('src/schema/*/schema_.ts'):
    with open(path) as f:
        content = f.read()

    lines = content.split('\n')
    new_lines = []
    i = 0
    in_method = False
    return_type = None
    while i < len(lines):
        line = lines[i]
        if re.match(r'^\s+requiredIf<', line):
            in_method = True
            new_lines.append(line)
            i += 1
            continue

        if in_method:
            # look for return type on the signature line "  ): TYPE {"
            m = re.match(r'^  \): (.+?) \{', line)
            if m:
                return_type = m.group(1)
            if line.startswith('    return new '):
                # add cast
                line = line.rstrip() + f' as unknown as {return_type}'
            if line.strip() == '}':
                in_method = False
        new_lines.append(line)
        i += 1

    with open(path, 'w') as f:
        f.write('\n'.join(new_lines))
    print(f"{path}: patched")
PYEOF
grep -n "return new AnySchema_(" -A3 src/schema/any/schema_.ts | head -8