cd /app && python3 - <<'PY'
p='tests/server_tests.js'
s=open(p).read()
# find the last '});' closing main describe, before helper functions
idx = s.rfind('});')
assert idx != -1
insert = r'''

  describe('broadcastAbort', function() {
    it('is idempotent and can be reset', function() {
      let server = new Server(new Config('ci', {}));
      let emits = 0;
      server.io = {
        emit: function(evt) {
          if (evt === 'abort-tests') {
            emits++;
          }
        }
      };
      server.broadcastAbort();
      server.broadcastAbort();
      expect(emits).to.equal(1);
      server.resetAbort();
      server.broadcastAbort();
      expect(emits).to.equal(2);
    });

    it('tolerates uninitialized io', function() {
      let server = new Server(new Config('ci', {}));
      expect(function() {
        server.broadcastAbort();
      }).to.not.throw();
    });
  });
'''
s = s[:idx] + insert + s[idx:]
open(p,'w').write(s)
PY
node -e "const s=require('fs').readFileSync('tests/server_tests.js','utf8'); let d=0; for (const c of s){ if(c==='{')d++; if(c==='}')d--; } console.log('depth',d);"
npx mocha tests/server_tests.js 2>&1 | tail -12