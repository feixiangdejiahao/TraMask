cd /app && python3 - <<'PYEOF'
path = 'src/tmp-error-stack.test.ts'
with open(path) as f:
    src = f.read()
src = src.replace("expect(out.e.stack).toBe('Error: hello\\n    at a (/app/a.ts:1:1)\\n    at c (/app/c.ts:3:3)');",
                  "expect(out.e.stack).toBe('Error: hello\\nat a (/app/a.ts:1:1)\\nat c (/app/c.ts:3:3)');")
src = src.replace("expect(out.e.stackFrames).toEqual([\n      { raw: 'Error: hello' },\n      { raw: 'at a (/app/a.ts:1:1)' },\n      { raw: 'at c (/app/c.ts:3:3)' },\n    ]);",
                  "expect(out.e.stackFrames).toEqual([\n      { raw: 'Error: hello' },\n      { raw: 'at a (/app/a.ts:1:1)' },\n      { raw: 'at c (/app/c.ts:3:3)' },\n    ]);")
src = src.replace("expect(processStackString(stack, opts)).toBe('Error: x\\n    at a (/app/a.ts:1:1)');",
                  "expect(processStackString(stack, opts)).toBe('Error: x\\nat a (/app/a.ts:1:1)');")
src = src.replace("expect(processStackFrames(stack, opts)).toEqual([\n      { raw: 'Error: x' },\n      { raw: 'at a (/app/a.ts:1:1)' },\n    ]);",
                  "expect(processStackFrames(stack, opts)).toEqual([\n      { raw: 'Error: x' },\n      { raw: 'at a (/app/a.ts:1:1)' },\n    ]);")
with open(path, 'w') as f:
    f.write(src)
print('updated')
PYEOF
npx vitest run src/tmp-error-stack.test.ts 2>&1 | tail -30