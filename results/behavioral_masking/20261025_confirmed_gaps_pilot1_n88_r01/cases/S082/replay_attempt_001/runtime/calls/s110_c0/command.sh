cd /app && node -e "
const s=require('fs').readFileSync('tests/utils/reporter_tests.js','utf8');
let depth=0;
for (let i=0;i<s.length;i++){ if(s[i]==='{')depth++; if(s[i]==='}')depth--; }
console.log('brace depth at end', depth);
console.log('line 470-485:'); 
const lines=s.split('\n');
for(let i=469;i<Math.min(485,lines.length);i++) console.log((i+1)+': '+lines[i]);
"