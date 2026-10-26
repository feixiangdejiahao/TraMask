cd /app && python3 - <<'PY'
p='packages/core/src/relation/tracking.ts'
s=open(p).read()
s=s.replace("import { $internal } from '../common';\nimport type { Entity } from '../entity/types';\n", "import { $internal } from '../common';\nimport type { Entity } from '../entity/types';\nimport { getEntityId } from '../entity/utils/pack-entity';\n")
s=s.replace("            const packedEntity = ctx.entityIndex.dense[denseIdx];\n            if (packedEntity === undefined || getEntityIdOf(packedEntity) !== eid) continue;\n", "            const packedEntity = ctx.entityIndex.dense[denseIdx];\n            if (packedEntity === undefined || getEntityId(packedEntity) !== eid) continue;\n")
s=s.replace("""function getEntityIdOf(entity: number): number {
    return entity & 0xffffffff;
}
""", "")
open(p,'w').write(s)
print('updated')
PY
tail -20 packages/core/src/relation/tracking.ts