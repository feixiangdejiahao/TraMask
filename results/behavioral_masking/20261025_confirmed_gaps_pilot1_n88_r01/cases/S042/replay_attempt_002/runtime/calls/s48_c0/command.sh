cd /app && python3 - <<'PY'
p='packages/core/src/query/types.ts'
s=open(p).read()
s=s.replace("""export type Modifier<TTrait extends Trait[] = Trait[], TType extends string = string> = {
    [$modifier]: true;
    type: TType;
    id: number;
    traits: TTrait;
    traitIds: number[];
};""", """export type Modifier<TTrait extends Trait[] = Trait[], TType extends string = string> = {
    [$modifier]: true;
    type: TType;
    id: number;
    traits: TTrait;
    traitIds: number[];
    /** Relation pairs tracked by this modifier (for pair-level tracking) */
    pairs?: RelationPair[];
};""")
s=s.replace("""export type TrackingGroup = {
    /** Whether all traits must match (and) or any trait can match (or) */
    logic: 'and' | 'or';
    /** The type of tracking event */
    type: 'add' | 'remove' | 'change';
    /** Tracking modifier ID for snapshot/mask lookups */
    id: number;
    /** Bitmasks indexed by generationId */
    bitmasks: (number | undefined)[];
    /** Per-entity tracker state indexed by [generationId][entityId] */
    trackers: (number[] | undefined)[];
};""", """export type TrackingGroup = {
    /** Whether all traits must match (and) or any trait can match (or) */
    logic: 'and' | 'or';
    /** The type of tracking event */
    type: 'add' | 'remove' | 'change';
    /** Tracking modifier ID for snapshot/mask lookups */
    id: number;
    /** Bitmasks indexed by generationId */
    bitmasks: (number | undefined)[];
    /** Per-entity tracker state indexed by [generationId][entityId] */
    trackers: (number[] | undefined)[];
    /** Relation pair tracked by this group (one pair per group) */
    pairs?: RelationPair[];
};""")
s=s.replace("""    checkTracking: (
        world: World,
        entity: Entity,
        eventType: 'add' | 'remove' | 'change',
        generationId: number,
        bitflag: number
    ) => boolean;""", """    checkTracking: (
        world: World,
        entity: Entity,
        eventType: 'add' | 'remove' | 'change',
        generationId: number,
        bitflag: number,
        target?: Entity
    ) => boolean;""")
open(p,'w').write(s)
print('query types updated')
PY
grep -n "pairs?\|checkTracking" packages/core/src/query/types.ts