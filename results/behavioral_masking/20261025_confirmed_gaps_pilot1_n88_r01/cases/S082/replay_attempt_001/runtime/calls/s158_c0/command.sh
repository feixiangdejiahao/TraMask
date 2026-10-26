cd /app && python3 - <<'PY'
p='tests/config_tests.js'
s=open(p).read()
insert = r'''

describe('bail_on_test_failure', function() {
  it('defaults to false', function() {
    let config = new Config('ci', {});
    expect(config.get('bail_on_test_failure')).to.be.false();
  });

  it('allows true and positive integers', function() {
    let config = new Config('ci', { bail_on_test_failure: true });
    expect(config.get('bail_on_test_failure')).to.be.true();

    config = new Config('ci', { bail_on_test_failure: 3 });
    expect(config.get('bail_on_test_failure')).to.equal(3);
  });
});
'''
s = s.rstrip() + '\n' + insert + '\n'
open(p,'w').write(s)
PY
node -e "const s=require('fs').readFileSync('tests/config_tests.js','utf8'); let d=0; for (const c of s){ if(c==='{')d++; if(c==='}')d--; } console.log('depth',d);"
npx mocha tests/config_tests.js 2>&1 | tail -10