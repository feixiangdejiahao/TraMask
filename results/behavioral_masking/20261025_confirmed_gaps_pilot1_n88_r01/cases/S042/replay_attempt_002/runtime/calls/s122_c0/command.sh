cd /app && python3 - <<'PY'
p='packages/core/src/query/types.ts'
s=open(p).read()
# Replace UnwrapModifierData block with helpers
old="""type UnwrapModifierData<T> = T extends Modifier<infer C> ? C : never;

export type StoresFromParameters<T extends QueryParameter[]> = T extends [infer First, ...infer Rest]
    ? [
          ...(First extends Trait
              ? [ExtractStore<First>]
              : First extends Modifier
                ? StoresFromParameters<UnwrapModifierData<First>>
                : []),
          ...(Rest extends QueryParameter[] ? StoresFromParameters<Rest> : []),
      ]
    : [];"""
new="""type UnwrapModifierData<T> = T extends Modifier<infer C> ? C : never;

type ExtractModifiersFromOrParams<T extends OrParameter[]> = T extends [infer F, ...infer R]
    ? F extends Modifier
        ? [F, ...ExtractModifiersFromOrParams<R>]
        : ExtractModifiersFromOrParams<R>
    : [];

export type StoresFromParameters<T extends QueryParameter[]> = T extends [infer First, ...infer Rest]
    ? [
          ...(First extends Trait
              ? [ExtractStore<First>]
              : First extends Modifier
                ? First extends OrModifier<infer P>
                    ? StoresFromParameters<ExtractModifiersFromOrParams<P>>
                    : StoresFromParameters<UnwrapModifierData<First>>
                : []),
          ...(Rest extends QueryParameter[] ? StoresFromParameters<Rest> : []),
      ]
    : [];"""
assert old in s
s=s.replace(old,new)
old2="""export type InstancesFromParameters<T extends QueryParameter[]> = T extends [
    infer First,
    ...infer Rest,
]
    ? [
          ...(First extends Trait
              ? IsTag<First> extends false
                  ? ExtractSchema<First> extends AoSFactory
                      ? [ReturnType<ExtractSchema<First>>]
                      : [TraitRecord<First>]
                  : []
              : First extends Modifier
                ? IsNotModifier<First> extends true
                    ? []
                    : InstancesFromParameters<UnwrapModifierData<First>>
                : []),
          ...(Rest extends QueryParameter[] ? InstancesFromParameters<Rest> : []),
      ]
    : [];"""
new2="""export type InstancesFromParameters<T extends QueryParameter[]> = T extends [
    infer First,
    ...infer Rest,
]
    ? [
          ...(First extends Trait
              ? IsTag<First> extends false
                  ? ExtractSchema<First> extends AoSFactory
                      ? [ReturnType<ExtractSchema<First>>]
                      : [TraitRecord<First>]
                  : []
              : First extends Modifier
                ? IsNotModifier<First> extends true
                    ? []
                    : First extends OrModifier<infer P>
                      ? InstancesFromParameters<ExtractModifiersFromOrParams<P>>
                      : InstancesFromParameters<UnwrapModifierData<First>>
                : []),
          ...(Rest extends QueryParameter[] ? InstancesFromParameters<Rest> : []),
      ]
    : [];"""
assert old2 in s
s=s.replace(old2,new2)
# Update OrModifier type
old3="""/** Or modifier that can contain both traits and nested modifiers */
export type OrModifier<T extends OrParameter[] = OrParameter[]> = Modifier<
    ExtractTraitsFromOrParams<T>,
    'or'
> & {
    modifiers: Modifier[];
};"""
new3="""/** Or modifier that can contain both traits and nested modifiers */
export type OrModifier<T extends OrParameter[] = OrParameter[]> = Modifier<
    ExtractTraitsFromOrParams<T>,
    'or'
> & {
    modifiers: ExtractModifiersFromOrParams<T>;
};"""
assert old3 in s
s=s.replace(old3,new3)
open(p,'w').write(s)
print('types updated')
PY
cd packages/core && pnpm exec tsc --noEmit -p tsconfig.json 2>&1 | head -60