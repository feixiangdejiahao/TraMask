cd /app && cat > .tmp-dto.ts <<'EOF'
import { item, map, list, set, record, anyOf, string, number, any, nul, binary, boolean } from './src/index.js'
import { SchemaDTO } from './src/schema/actions/dto/index.js'
import { fromSchemaDTO } from './src/schema/actions/fromDTO/index.js'

const sch = item({
  pk: string().key(),
  str: string().optional().requiredIf('type', 'a', 'b'),
  num: number().optional().requiredIf('type', 'a'),
  anyAttr: any().optional().requiredIf('type', 'b'),
  bool: boolean().optional().requiredIf('type', 'a'),
  nulAttr: nul().optional().requiredIf('type', 'b'),
  bin: binary().optional().requiredIf('type', 'a'),
  setAttr: set(string()).optional().requiredIf('type', 'b'),
  listAttr: list(string()).optional().requiredIf('type', 'a'),
  mapAttr: map({ x: string() }).optional().requiredIf('type', 'b'),
  recAttr: record(string(), string()).optional().requiredIf('type', 'a'),
  anyOfAttr: anyOf(string(), number()).optional().requiredIf('type', 'b'),
  type: string().enum('a', 'b')
})
sch.check()

const dto = new SchemaDTO(sch).toJSON()
console.log('DTO attrs requiredIf:', Object.fromEntries(Object.entries(dto.attributes).map(([k,v]: any)=>[k, v.requiredIf])))
const restored = fromSchemaDTO(dto)
restored.check()
console.log('restored attrs requiredIf:', Object.fromEntries(Object.entries(restored.attributes).map(([k,v]: any)=>[k, v.props.requiredIf])))
const dto2 = new SchemaDTO(restored).toJSON()
console.log('roundtrip equal:', JSON.stringify(dto) === JSON.stringify(dto2))
EOF
cd /app && npx tsx .tmp-dto.ts