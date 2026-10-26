cd /app && git checkout tests/utils/reporter_tests.js && python3 - <<'PY'
p='tests/utils/reporter_tests.js'
s=open(p).read()
# Insert new describe before the final "});" of the outer describe
assert s.rstrip().endswith('});')
insert = r'''

  describe('bail_on_test_failure', function() {
    function bailApp(value) {
      return {
        config: {
          get: function(key) {
            switch (key) {
              case 'reporter':
                return new FakeReporter();
              case 'bail_on_test_failure':
                return value;
            }
          }
        }
      };
    }

    it('defaults to disabled when no value is provided', function() {
      let reporter = new Reporter(mockApp(), stream);
      expect(reporter.bailOnTestFailure).to.equal(0);
      expect(reporter.hasBailed()).to.be.false();
    });

    it('treats true as a threshold of one', function() {
      let reporter = new Reporter(bailApp(true), stream);
      expect(reporter.bailOnTestFailure).to.equal(1);
    });

    it('treats a positive integer as the threshold', function() {
      let reporter = new Reporter(bailApp(3), stream);
      expect(reporter.bailOnTestFailure).to.equal(3);
    });

    [0, -1, 1.5, '2'].forEach(function(value) {
      it('logs a warning and defaults to false for ' + JSON.stringify(value), function() {
        sandbox.spy(log, 'warn');
        let reporter = new Reporter(bailApp(value), stream);
        expect(reporter.bailOnTestFailure).to.equal(0);
        expect(log.warn).to.have.been.calledWith('bail_on_test_failure', sinon.match.any);
      });
    });

    it('bails on the Nth non-skipped non-todo failure', function() {
      let reporter = new Reporter(bailApp(2), stream);
      let events = [];
      reporter.on('test-failure', function(name, result) {
        events.push({ name: name, result: result });
      });

      reporter.report('chrome', { name: 'pass', passed: true });
      reporter.report('chrome', { name: 'skip', skipped: true });
      reporter.report('chrome', { name: 'todo', passed: false, todo: true });
      reporter.report('chrome', { name: 'fail one', passed: false });
      expect(reporter.hasBailed()).to.be.false();

      reporter.report('chrome', { name: 'fail two', passed: false });
      expect(reporter.hasBailed()).to.be.true();
      expect(reporter.bailReason).to.equal('fail two');
      expect(events).to.have.length(1);
      expect(events[0].name).to.equal('chrome');
      expect(events[0].result.name).to.equal('fail two');
    });

    it('gates subsequent results from sub-reporters', function() {
      let reporter = new Reporter(bailApp(1), stream);
      let subReporter = reporter.reporters[0];
      reporter.report('chrome', { name: 'fail', passed: false });
      reporter.report('chrome', { name: 'late', passed: true });

      expect(subReporter.results.map(function(r) { return r.result.name; }))
        .to.deep.equal(['fail']);
      expect(reporter.suppressedAfterBail).to.equal(1);
    });

    it('exposes bail state through getBailReport', function() {
      let reporter = new Reporter(bailApp(1), stream);
      reporter.report('chrome', { name: 'first fail', passed: false });
      reporter.report('chrome', { name: 'second fail', passed: false });

      let report = reporter.getBailReport();
      expect(report.testsRanBeforeBail).to.equal(1);
      expect(report.bailLauncher).to.equal('chrome');
      expect(report.failuresByLauncher).to.deep.equal({ chrome: 1 });
      expect(report.failedTests).to.deep.equal(['first fail']);
    });

    it('resetBailState clears all bail state', function() {
      let reporter = new Reporter(bailApp(1), stream);
      reporter.report('chrome', { name: 'fail', passed: false });
      expect(reporter.hasBailed()).to.be.true();

      reporter.resetBailState();
      expect(reporter.hasBailed()).to.be.false();
      expect(reporter.bailReason).to.be.null();
      expect(reporter.getBailReport().bailLauncher).to.be.null();
      expect(reporter.getBailReport().failuresByLauncher).to.deep.equal({});
      expect(reporter.getBailReport().failedTests).to.deep.equal([]);
    });
  });
'''
s = s.rstrip()[:-3] + insert + '\n});\n'
open(p,'w').write(s)
PY
node -e "const s=require('fs').readFileSync('tests/utils/reporter_tests.js','utf8'); let d=0; for (const c of s){ if(c==='{')d++; if(c==='}')d--; } console.log('depth',d);"
npx mocha tests/utils/reporter_tests.js 2>&1 | tail -45