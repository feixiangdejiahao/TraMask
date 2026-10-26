cd /app && sed -i "s|expect(out.e.stack).toBe('Error: hello\\\\nat a (/app/a.ts:1:1)\\\\nat c (/app/c.ts:3:3)');|expect(out.e.stack).toBe('Error: hello\\\\nat a (/app/a.ts:1:1)');|" src/tmp-error-stack.test.ts
grep -n "expect(out.e.stack)" src/tmp-error-stack.test.ts
npx vitest run src/tmp-error-stack.test.ts 2>&1 | tail -20