cd /app && python3 - <<'PY'
p='packages/core/src/trait/types.ts'
s=open(p).read()
s=s.replace("export type TraitOrRelation = Trait | Relation<Trait>;", "export type TraitOrRelation = Trait | Relation<Trait> | RelationPair;")
s=s.replace("""/** Extracts the underlying Trait from a TraitOrRelation (Relations contain a Trait) */
export type ExtractTrait<T> = T extends Relation<infer TTrait> ? TTrait : T;

/** Maps a tuple of TraitOrRelation to their underlying Traits */
export type ExtractTraits<T extends TraitOrRelation[]> = {
    [K in keyof T]: ExtractTrait<T[K]>;
};""", """/** Extracts the underlying Trait from a TraitOrRelation (Relations/Pairs contain a Trait) */
export type ExtractTrait<T> = T extends Relation<infer TTrait>
    ? TTrait
    : T extends RelationPair<infer TPairTrait>
      ? TPairTrait extends Relation<infer TTrait>
          ? TTrait
          : T extends Relation<infer T2>
            ? T2
            : never
      : T;

/** Maps a tuple of TraitOrRelation to their underlying Traits */
export type ExtractTraits<T extends TraitOrRelation[]> = {
    [K in keyof T]: ExtractTrait<T[K]>;
};""")
open(p,'w').write(s)
print('trait types updated')
PY
cat packages/core/src/trait/types.ts | tail -40