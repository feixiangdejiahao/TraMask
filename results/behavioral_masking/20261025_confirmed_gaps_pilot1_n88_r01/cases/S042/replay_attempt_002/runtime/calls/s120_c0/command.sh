cd /app && python3 - <<'PY'
p='packages/core/tests/pair-tracking-modifiers.test.ts'
s=open(p).read()
old="""        const seen = new Map<number, number>();
        world
            .query(Or(Added(Contains(targetA)), Added(Contains(targetB))))
            .readEach(([contains], entity) => {
                seen.set(entity.id(), (contains as { amount: number }).amount);
            });

        expect(seen.get(entityA.id())).toBe(1);
        expect(seen.get(entityB.id())).toBe(2);"""
new="""        const seen = new Map<number, number>();
        world
            .query(Or(Added(Contains(targetA)), Added(Contains(targetB))))
            .readEach(([containsA, containsB], entity) => {
                const amount =
                    (containsA as { amount?: number } | undefined)?.amount ??
                    (containsB as { amount?: number } | undefined)?.amount;
                seen.set(entity.id(), amount);
            });

        expect(seen.get(entityA.id())).toBe(1);
        expect(seen.get(entityB.id())).toBe(2);"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('test updated')
PY
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -35