cd /app && cat > check_bail_tmp2.js <<'EOF'
'use strict';
const Config = require('./lib/config');
const Reporter = require('./lib/utils/reporter');
const PassThrough = require('stream').PassThrough;
const TapReporter = require('./lib/reporters/tap_reporter');
const DotReporter = require('./lib/reporters/dot_reporter');
const TeamcityReporter = require('./lib/reporters/teamcity_reporter');
const XUnitReporter = require('./lib/reporters/xunit_reporter');
const FakeReporter = require('./tests/support/fake_reporter');

function run(reporterName, ReporterClass, config) {
  const app = { config, reporter: null, on(){}, emit(){}, server:{resetAbort(){}} };
  const stream = new PassThrough();
  const reporter = new Reporter(app, stream);
  app.reporter = reporter;
  reporter.reporters = [new ReporterClass(false, stream, config, app)];
  reporter.report('chrome', {name:'pass1', passed:true});
  reporter.report('chrome', {name:'fail1', passed:false, error:{message:'boom'}});
  reporter.report('chrome', {name:'late', passed:true});
  reporter.finish();
  return stream.read().toString();
}

let c = new Config('ci', {});
c.config.bail_on_test_failure = 1;
console.log('=== TAP ===');
console.log(run('tap', TapReporter, c));
console.log('=== DOT ===');
console.log(run('dot', DotReporter, c));
console.log('=== TEAMCITY ===');
console.log(run('teamcity', TeamcityReporter, c));
console.log('=== XUNIT ===');
console.log(run('xunit', XUnitReporter, c));
EOF
node check_bail_tmp2.js