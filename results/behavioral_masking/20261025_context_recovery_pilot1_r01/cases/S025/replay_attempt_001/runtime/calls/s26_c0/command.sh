cd /app && python3 - <<'PY'
import re
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
s=s.replace("\tfilteredOptions: T[];\n", "\tfilteredOptions: T[] = [];\n")
# add trimCache after applyAsyncResult block
marker = "\t#initializeSelection(options: T[]): void {"
insert = "\t#trimCache(): void {\n\t\tif (this.#cache && this.#cache.size > this.#maxCacheSize) {\n\t\t\tconst oldestKey = this.#cache.keys().next().value;\n\t\t\tif (oldestKey !== undefined) {\n\t\t\t\tthis.#cache.delete(oldestKey);\n\t\t\t}\n\t\t}\n\t}\n\n"
s=s.replace(marker, insert + marker)
open(p,'w').write(s)
PY
cd /app/packages/core && npx tsc --noEmit --project ../../tsconfig.json 2>&1 | head -40