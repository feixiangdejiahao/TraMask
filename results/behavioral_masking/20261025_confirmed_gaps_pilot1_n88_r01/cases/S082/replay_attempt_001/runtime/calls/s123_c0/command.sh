cd /app && python3 - <<'PY'
p='tests/runners/browser_test_runner_tests.js'
s=open(p).read()
insert = r'''

  describe('abort', function() {
    let runner, reporter, socket, config;

    beforeEach(function() {
      reporter = new FakeReporter();
      config = new Config('ci', { reporter: reporter });
      let launcher = new Launcher('ci', { protocol: 'browser' }, config);
      runner = new BrowserTestRunner(launcher, reporter, 1, true, config);
      socket = new FakeSocket();
      runner.socket = socket;
    });

    it('is idempotent and emits abort-tests via the socket', function() {
      let emit = sinon.spy(socket, 'emit');
      return Bluebird.all([runner.abort(), runner.abort()]).then(function() {
        expect(emit).to.have.been.calledWith('abort-tests');
        expect(emit).to.have.been.calledOnce();
        expect(runner.aborted).to.be.true();
      });
    });

    it('suppresses subsequent results and errors', function() {
      runner.abort();
      runner.onTestResult({ name: 'late', failed: 1 });
      runner.onGlobalError('boom', 'url', 1);
      runner.onProcessError(new Error('boom'));

      expect(reporter.total).to.equal(0);
    });
  });
'''
s = s.rstrip()
assert s.endswith('});')
s = s[:-3] + insert + '\n});\n'
open(p,'w').write(s)
PY
node -e "const s=require('fs').readFileSync('tests/runners/browser_test_runner_tests.js','utf8'); let d=0; for (const c of s){ if(c==='{')d++; if(c==='}')d--; } console.log('depth',d);"
npx mocha tests/runners/browser_test_runner_tests.js 2>&1 | tail -20