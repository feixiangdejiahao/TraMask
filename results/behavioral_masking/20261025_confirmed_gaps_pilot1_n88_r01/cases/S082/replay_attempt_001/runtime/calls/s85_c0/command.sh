cd /app && cat > /tmp/check_bail.js <<'EOF'
'use strict';
const Config = require('./lib/config');
const Reporter = require('./lib/utils/reporter');
const PassThrough = require('stream').PassThrough;
const Server = require('./lib/server');
const BrowserTestRunner = require('./lib/runners/browser_test_runner');
const ProcessTestRunner = require('./lib/runners/process_test_runner');
const Testem = require('./public/testem/testem_client');

function mockApp(config) {
  return {
    config,
    reporter: null,
    server: { resetAbort() {} },
    on() {},
    emit() {}
  };
}

function makeReporter(config, reporterName) {
  const app = mockApp(config);
  const stream = new PassThrough();
  const reporter = new Reporter(app, stream);
  app.reporter = reporter;
  reporter.app = app;
  return { reporter, stream, app };
}

console.log('--- validation ---');
let c = new Config('ci', {});
c.config.bail_on_test_failure = true;
let r = makeReporter(c).reporter;
console.log('true =>', r.bailOnTestFailure);

c = new Config('ci', {});
c.config.bail_on_test_failure = 3;
r = makeReporter(c).reporter;
console.log('3 =>', r.bailOnTestFailure);

c = new Config('ci', {});
c.config.bail_on_test_failure = '2';
r = makeReporter(c).reporter;
console.log("'2' =>", r.bailOnTestFailure);

c = new Config('ci', {});
c.config.bail_on_test_failure = 0;
r = makeReporter(c).reporter;
console.log('0 =>', r.bailOnTestFailure);

c = new Config('ci', {});
c.config.bail_on_test_failure = 1.5;
r = makeReporter(c).reporter;
console.log('1.5 =>', r.bailOnTestFailure);

console.log('--- bail reporting ---');
c = new Config('ci', {});
c.config.bail_on_test_failure = 2;
const { reporter, stream } = makeReporter(c);
const FakeReporter = require('./tests/support/fake_reporter');
const sub = new FakeReporter();
reporter.reporters = [sub];
let events = [];
reporter.on('test-failure', (name, result) => events.push([name, result.name]));
reporter.report('chrome', { name: 'pass1', passed: true });
reporter.report('chrome', { name: 'skip1', skipped: true });
reporter.report('chrome', { name: 'todo1', passed: false, todo: true });
reporter.report('chrome', { name: 'fail1', passed: false });
reporter.report('chrome', { name: 'fail2', passed: false });
reporter.report('chrome', { name: 'late1', passed: true });
reporter.report('chrome', { name: 'lateFail', passed: false });
console.log('hasBailed', reporter.hasBailed());
console.log('bailReason', reporter.bailReason);
console.log('bailLauncher', reporter.bailLauncher);
console.log('report', reporter.getBailReport());
console.log('suppressed', reporter.suppressedAfterBail);
console.log('events', events);
console.log('sub.total (should be 5, no late)', sub.total);
console.log('sub.results names', sub.results.map(x => x.result.name));

console.log('--- reset ---');
reporter.resetBailState();
console.log('hasBailed after reset', reporter.hasBailed());
console.log('bailReason after reset', reporter.bailReason);
console.log('bailLauncher after reset', reporter.getBailReport().bailLauncher);
reporter.report('chrome', { name: 'afterResetPass', passed: true });
console.log('sub.total after reset+report', sub.total, 'last', sub.results[sub.results.length-1].result.name);

console.log('--- server broadcastAbort ---');
const server = new Server(c);
let emits = 0;
server.io = { emit: (evt) => { if (evt === 'abort-tests') emits++; } };
server.broadcastAbort();
server.broadcastAbort();
console.log('emits after 2 broadcasts', emits);
server.resetAbort();
server.broadcastAbort();
console.log('emits after reset+broadcast', emits);
const server2 = new Server(c);
server2.broadcastAbort();
console.log('no io no throw');

console.log('--- app getExitCode ---');
const App = require('./lib/app');
const app = new App(c, function(){});
app.reporter = reporter;
reporter._bailed = false; reporter.bailReason = null; reporter.testsRanBeforeBail = 0;
reporter.report('chrome', {name:'f', passed:false});
const e = app.getExitCode();
console.log('exit code err', e && e.message);
EOF
node /tmp/check_bail.js