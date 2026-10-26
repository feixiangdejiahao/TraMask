cd /app && cp packages/core/src/query/utils/check-query-tracking-with-relations.ts /tmp/cq.bak && cat > packages/core/src/query/utils/check-query-tracking-with-relations.ts <<'EOF'
import type { Entity } from '../../entity/types';
import { hasRelationPair } from '../../relation/relation';
import type { World } from '../../world';
import type { EventType, QueryInstance } from '../types';
import { checkQueryTracking } from './check-query-tracking';

export function checkQueryTrackingWithRelations(
    world: World,
    query: QueryInstance,
    entity: Entity,
    eventType: EventType,
    eventGenerationId: number,
    eventBitflag: number
): boolean {
    const first = checkQueryTracking(world, query, entity, eventType, eventGenerationId, eventBitflag);
    if (!first) return false;
    if (query.relationFilters && query.relationFilters.length > 0) {
        for (const pair of query.relationFilters) {
            if (!hasRelationPair(world, entity, pair)) {
                console.log('REJECTED by relation filter', query.hash, 'event', eventType, 'has', hasRelationPair(world, entity, pair));
                return false;
            }
        }
    }
    return true;
}
EOF
cd packages/core && pnpm exec vitest run tests/query-modifiers.test.ts -t "Removed on a relation" 2>&1 | tail -50; cd /app && cp /tmp/cq.bak packages/core/src/query/utils/check-query-tracking-with-relations.ts