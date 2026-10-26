cd /app && cat > .tmp-zod.ts <<'EOF'
import { item, map, string, number } from './src/index.js'
import { ZodSchemer } from './src/schema/actions/zodSchemer/index.js'

const sch = item({
  pk: string().key(),
  type: string().enum('a', 'b'),
  details: string().optional().requiredIf('type', 'a')
})
sch.check()

const zod = new ZodSchemer(sch)

function check(label: string, fn: () => unknown) {
  try {
    const v = fn()
    console.log(label, 'OK', JSON.stringify(v))
  } catch (e) {
    console.log(label, 'ERR', (e as any).issues?.[0]?.message ?? (e as any).message)
  }
}

check('parser put type a missing', () => zod.parser({ mode: 'put' }).parse({ pk: 'x', type: 'a' }))
check('parser put type a present', () => zod.parser({ mode: 'put' }).parse({ pk: 'x', type: 'a', details: 'd' }))
check('parser put type b missing', () => zod.parser({ mode: 'put' }).parse({ pk: 'x', type: 'b' }))
check('parser update type a missing (should OK)', () => zod.parser({ mode: 'update' }).parse({ pk: 'x', type: 'a' }))

check('formatter type a missing', () => zod.formatter().parse({ pk: 'x', type: 'a' }))
check('formatter type a present', () => zod.formatter().parse({ pk: 'x', type: 'a', details: 'd' }))
check('formatter type b missing', () => zod.formatter().parse({ pk: 'x', type: 'b' }))
EOF
cd /app && npx tsx .tmp-zod.ts