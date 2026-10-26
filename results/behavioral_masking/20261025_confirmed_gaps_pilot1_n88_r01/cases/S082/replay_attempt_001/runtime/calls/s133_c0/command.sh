cd /app && git checkout tests/server_tests.js && python3 - <<'PY'
p='tests/server_tests.js'
lines=open(p).read().split('\n')
# Insert before the main describe closing at line index 588 (0-based) => line 589 '});'
# Find the last line equal to '});' before 'function middleware'
close_idx = None
for i, line in enumerate(lines):
    if line == '});':
        close_idx = i
insert = [
"",
"  describe('broadcastAbort', function() {",
"    it('is idempotent and can be reset', function() {",
"      let server = new Server(new Config('ci', {}));",
"      let emits = 0;",
"      server.io = {",
"        emit: function(evt) {",
"          if (evt === 'abort-tests') {",
"            emits++;",
"          }",
"        }",
"      };",
"      server.broadcastAbort();",
"      server.broadcastAbort();",
"      expect(emits).to.equal(1);",
"      server.resetAbort();",
"      server.broadcastAbort();",
"      expect(emits).to.equal(2);",
"    });",
"",
"    it('tolerates uninitialized io', function() {",
"      let server = new Server(new Config('ci', {}));",
"      expect(function() {",
"        server.broadcastAbort();",
"      }).to.not.throw();",
"    });",
"  });",
]
lines = lines[:close_idx] + insert + lines[close_idx:]
open(p,'w').write('\n'.join(lines))
PY
node -e "const s=require('fs').readFileSync('tests/server_tests.js','utf8'); let d=0; for (const c of s){ if(c==='{')d++; if(c==='}')d--; } console.log('depth',d);"
npx mocha tests/server_tests.js 2>&1 | tail -12