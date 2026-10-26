cd /app && grep -n "userInput" packages/core/src/prompts/autocomplete.ts | head && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
s=s.replace("${this.userInput}\u2589`","${this.userInput}\u2588`")
open(p,'w').write(s)
print("fixed")
PY
grep -n "userInput.*▉\|userInput.*█" packages/core/src/prompts/autocomplete.ts