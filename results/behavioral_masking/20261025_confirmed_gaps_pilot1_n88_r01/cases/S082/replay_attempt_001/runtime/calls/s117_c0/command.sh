cd /app && python3 - <<'PY'
p='tests/ci/reporter_tests.js'
s=open(p).read()
insert = r'''

  describe('bail output', function() {
    function makeApp(config) {
      const app = {
        config: config,
        reporter: null,
        on: function() {},
        emit: function() {},
        server: { resetAbort: function() {} }
      };
      return app;
    }

    function bailedReporter(ReporterClass, config) {
      const stream = new PassThrough();
      const app = makeApp(config);
      const Reporter = require('../../lib/utils/reporter');
      const reporter = new Reporter(app, stream);
      app.reporter = reporter;
      reporter.reporters = [new ReporterClass(false, stream, config, app)];
      reporter.report('chrome', { name: 'pass one', passed: true });
      reporter.report('chrome', { name: 'fail one', passed: false, error: { message: 'boom' } });
      reporter.report('chrome', { name: 'late pass', passed: true });
      reporter.finish();
      return stream.read().toString();
    }

    it('tap writes a bail out and summary', function() {
      const config = new Config('ci', { bail_on_test_failure: 1 });
      let output = bailedReporter(TapReporter, config);
      assert.match(output, /Bail out! fail one/);
      assert.match(output, /# bailed/);
      assert.match(output, /# ran before bail 2/);
      assert.match(output, /# suppressed 1/);
    });

    it('dot writes a bail out and summary', function() {
      const config = new Config('ci', { bail_on_test_failure: 1 });
      let output = bailedReporter(DotReporter, config);
      assert.match(output, /Bail out! fail one/);
      assert.match(output, /# bailed/);
      assert.match(output, /# ran before bail 2/);
      assert.match(output, /# suppressed 1/);
    });

    it('teamcity writes bail messages and statistics', function() {
      const config = new Config('ci', { bail_on_test_failure: 1 });
      let output = bailedReporter(TeamcityReporter, config);
      assert.match(output, /##teamcity\[message text='Bail out! fail one' status='ERROR'\]/);
      assert.match(output, /##teamcity\[buildStatisticValue key='bailedTests' value='1'\]/);
      assert.match(output, /##teamcity\[buildStatisticValue key='testsBeforeBail' value='2'\]/);
      assert.match(output, /##teamcity\[buildStatisticValue key='suppressedAfterBail' value='1'\]/);
      assert.match(output, /##teamcity\[buildProblem description='Bail out! fail one'\]/);
    });

    it('xunit adds bail error, errors attribute, properties, and system-out', function() {
      const config = new Config('ci', { bail_on_test_failure: 1 });
      let output = bailedReporter(XUnitReporter, config);
      assert.match(output, /errors="1"/);
      assert.match(output, /<error message="Bail out! fail one"\/>/);
      assert.match(output, /<property name="bailReason" value="fail one"\/>/);
      assert.match(output, /<property name="testsBeforeBail" value="2"\/>/);
      assert.match(output, /<property name="suppressedAfterBail" value="1"\/>/);
      assert.match(output, /<system-out><!\[CDATA\[Bail out! fail one/);
    });
  });
'''
s = s.rstrip()
assert s.endswith('});')
s = s[:-3] + insert + '\n});\n'
open(p,'w').write(s)
PY
node -e "const s=require('fs').readFileSync('tests/ci/reporter_tests.js','utf8'); let d=0; for (const c of s){ if(c==='{')d++; if(c==='}')d--; } console.log('depth',d);"
npx mocha tests/ci/reporter_tests.js 2>&1 | tail -30