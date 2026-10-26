cd /app && git checkout tests/runners/process_test_runner_tests.js tests/runners/tap_process_test_runner_tests.js && python3 - <<'PY'
# process_test_runner_tests.js
p='tests/runners/process_test_runner_tests.js'
s=open(p).read()
insert = r'''

  describe('abort', function() {
    let runner, reporter;

    beforeEach(function() {
      reporter = new FakeReporter();
      let settings = { protocol: 'process' };
      let config = new Config('ci', { reporter: reporter });
      let launcher = new Launcher('proc', settings, config);
      runner = new ProcessTestRunner(launcher, reporter);
      runner.process = {
        kill: function() { return Promise.resolve(); }
      };
      runner.onStart = function() {};
      runner.onEnd = function() {};
      runner.onFinish = function() {};
    });

    it('is idempotent and finishes without reporting results', function(done) {
      let killCount = 0;
      runner.process.kill = function() {
        killCount++;
        return Promise.resolve();
      };
      runner.abort().then(function() {
        return runner.abort();
      }).then(function() {
        expect(killCount).to.equal(1);
        expect(runner.finished).to.be.true();
        expect(reporter.total).to.equal(0);
        done();
      }).catch(done);
    });

    it('suppresses process errors after abort', function() {
      runner.abort();
      runner.onProcessError(new Error('killed'));
      expect(reporter.total).to.equal(0);
    });
  });
'''
s = s.rstrip()
assert s.endswith('});')
s = s[:-3] + insert + '\n});\n'
open(p,'w').write(s)

# tap_process_test_runner_tests.js
p='tests/runners/tap_process_test_runner_tests.js'
s=open(p).read()
insert = r'''

  describe('abort', function() {
    let runner, reporter;

    beforeEach(function() {
      reporter = new FakeReporter();
      let settings = { protocol: 'tap' };
      let config = new Config('ci', { reporter: reporter });
      let launcher = new Launcher('tap-proc', settings, config);
      runner = new TapProcessTestRunner(launcher, reporter);
      runner.process = {
        kill: function() { return Promise.resolve(); }
      };
      runner.onStart = function() {};
      runner.onEnd = function() {};
      runner.onFinish = function() {};
    });

    it('is idempotent and wraps up without reporting results', function(done) {
      let killCount = 0;
      runner.process.kill = function() {
        killCount++;
        return Promise.resolve();
      };
      runner.abort().then(function() {
        return runner.abort();
      }).then(function() {
        expect(killCount).to.equal(1);
        expect(runner.finished).to.be.true();
        expect(reporter.total).to.equal(0);
        done();
      }).catch(done);
    });

    it('suppresses test results and process errors after abort', function() {
      runner.abort();
      runner.onTestResult({ name: 'late', failed: 1 });
      runner.onProcessError(new Error('killed'));
      expect(reporter.total).to.equal(0);
    });
  });
'''
s = s.rstrip()
assert s.endswith('});')
s = s[:-3] + insert + '\n});\n'
open(p,'w').write(s)
PY
npx mocha tests/runners/process_test_runner_tests.js tests/runners/tap_process_test_runner_tests.js 2>&1 | tail -20