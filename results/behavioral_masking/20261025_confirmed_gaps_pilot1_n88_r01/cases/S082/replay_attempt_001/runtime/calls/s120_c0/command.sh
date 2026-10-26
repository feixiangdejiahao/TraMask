cd /app && python3 - <<'PY'
p='tests/app_tests.js'
s=open(p).read()
insert = r'''

  describe('bail', function() {
    beforeEach(function() {
      config = new Config('ci', {});
    });

    it('getExitCode returns a bail-specific error', function() {
      config.config.bail_on_test_failure = 1;
      app = new App(config, function() {});
      let stream = new (require('stream').PassThrough)();
      let Reporter = require('../lib/utils/reporter');
      app.reporter = new Reporter(app, stream);
      app.reporter.reporters = [new FakeReporter()];
      app.reporter.report('chrome', { name: 'it fails', passed: false });

      let err = app.getExitCode();
      expect(err).to.be.an.instanceof(Error);
      expect(err.message).to.include('it fails');
      expect(err.message).to.include('1');
      expect(err.hideFromReporter).to.be.true();
    });

    it('abortRunners broadcasts and aborts all runners once', function() {
      app = new App(config, function() {});
      let broadcast = sandbox.spy();
      app.server = { broadcastAbort: broadcast };
      let runner1 = { abort: sandbox.spy(function() { return Bluebird.resolve(); }) };
      let runner2 = { abort: sandbox.spy(function() { return Bluebird.resolve(); }) };
      app.runners = [runner1, runner2];

      return app.abortRunners().then(function() {
        return app.abortRunners();
      }).then(function() {
        expect(broadcast).to.have.been.calledOnce();
        expect(runner1.abort).to.have.been.calledOnce();
        expect(runner2.abort).to.have.been.calledOnce();
      });
    });

    it('resetBailState resets abort tracking and server broadcast state', function() {
      app = new App(config, function() {});
      let resetAbort = sandbox.spy();
      app.server = { resetAbort: resetAbort };
      app.abortRunnersCalled = true;
      app.reporter = { resetBailState: sandbox.spy() };

      app.resetBailState();

      expect(app.abortRunnersCalled).to.be.false();
      expect(resetAbort).to.have.been.calledOnce();
      expect(app.reporter.resetBailState).to.have.been.calledOnce();
    });
  });
'''
s = s.rstrip()
assert s.endswith('});')
s = s[:-3] + insert + '\n});\n'
open(p,'w').write(s)
PY
node -e "const s=require('fs').readFileSync('tests/app_tests.js','utf8'); let d=0; for (const c of s){ if(c==='{')d++; if(c==='}')d--; } console.log('depth',d);"
npx mocha tests/app_tests.js 2>&1 | tail -30