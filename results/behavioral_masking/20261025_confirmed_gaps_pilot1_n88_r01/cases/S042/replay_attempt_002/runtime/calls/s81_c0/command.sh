cd /app && python3 - <<'PY'
p='packages/core/src/trait/types.ts'
s=open(p).read()
old="""/** Extracts the underlying Trait from a TraitOrRelation (Relations/Pairs contain a Trait) */
export type ExtractTrait<T> = T extends Relation<infer TTrait>
    ? TTrait
    : T extends RelationPair<infer TPairTrait>
      ? TPairTrait extends Relation<infer TTrait>
          ? TTrait
          : T extends Relation<infer T2>
            ? T2
            : never
      : T;"""
new="""/** Extracts the underlying Trait from a TraitOrRelation (Relations/Pairs contain a Trait) */
export type ExtractTrait<T> = T extends Relation<infer TTrait>
    ? TTrait
    : T extends RelationPair<infer TPairTrait>
      ? TPairTrait
      : T;"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('fixed ExtractTrait')
PY
# fix query-result spread
python3 - <<'PY'
p='packages/core/src/query/query-result.ts'
s=open(p).read()
old="""            const value = getRelationData(world, entity, relation, target);
            state[j] = value;
            atomicSnapshots[j] = trait[$internal].type === 'aos' ? { ...value } : null;"""
new="""            const value = getRelationData(world, entity, relation, target);
            state[j] = value;
            atomicSnapshots[j] =
                trait[$internal].type === 'aos' && value && typeof value === 'object'
                    ? { ...(value as Record<string, unknown>) }
                    : null;"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('fixed spread')
PY
cd packages/core && pnpm exec tsc --noEmit -p tsconfig.json 2>&1 | head -100