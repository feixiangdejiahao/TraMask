cd /app && python3 - <<'PY'
p='tests/utils/reporter_tests.js'
s=open(p).read()
# remove the very last "});\n"
s=s.rstrip()
assert s.endswith('});')
s=s[:-3].rstrip()+'\n'
open(p,'w').write(s)
PY
node -e "const s=require('fs').readFileSync('tests/utils/reporter_tests.js','utf8'); let d=0; for (const c of s){ if(c==='{')d++; if(c==='}')d--; } console.log('depth',d);"
npx mocha tests/utils/reporter_tests.js 2>&1 | tail -45