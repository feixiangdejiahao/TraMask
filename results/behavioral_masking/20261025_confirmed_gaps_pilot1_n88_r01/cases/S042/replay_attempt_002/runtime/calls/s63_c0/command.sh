cd /app && python3 - <<'PY'
p='packages/core/src/query/utils/check-query-tracking-with-relations.ts'
s=open(p).read()
s=s.replace("""import type { Entity } from '../../entity/types';
import { hasRelationPair } from '../../relation/relation';
import type { World } from '../../world';
import type { EventType, QueryInstance } from '../types';
import { checkQueryTracking } from './check-query-tracking';

/**
 * Check if an entity matches a tracking query with relation filters.
 * Combines checkQueryTracking (trait bitmasks + tracking state) with relation checks.
 */
export function checkQueryTrackingWithRelations(
    world: World,
    query: QueryInstance,
    entity: Entity,
    eventType: EventType,
    eventGenerationId: number,
    eventBitflag: number
): boolean {
    // First check trait bitmasks and tracking state (fast)
    if (!checkQueryTracking(world, query, entity, eventType, eventGenerationId, eventBitflag)) {
        return false;
    }
""", """import type { Entity } from '../../entity/types';
import { hasRelationPair } from '../../relation/relation';
import type { World } from '../../world';
import type { EventType, QueryInstance } from '../types';
import { checkQueryTracking } from './check-query-tracking';

/**
 * Check if an entity matches a tracking query with relation filters.
 * Combines checkQueryTracking (trait bitmasks + tracking state) with relation checks.
 */
export function checkQueryTrackingWithRelations(
    world: World,
    query: QueryInstance,
    entity: Entity,
    eventType: EventType,
    eventGenerationId: number,
    eventBitflag: number,
    target?: Entity
): boolean {
    // First check trait bitmasks and tracking state (fast)
    if (!checkQueryTracking(world, query, entity, eventType, eventGenerationId, eventBitflag, target)) {
        return false;
    }
""")
open(p,'w').write(s)
print('updated')
PY
cat packages/core/src/query/utils/check-query-tracking-with-relations.ts