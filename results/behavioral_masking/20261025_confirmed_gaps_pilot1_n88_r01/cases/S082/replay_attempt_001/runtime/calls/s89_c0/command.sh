cd /app && cat > check_bail_tmp.js <<'EOF'
'use strict';
const Config = require('./lib/config');
const Reporter = require('./lib/utils/reporter');
const PassThrough = require('stream').PassThrough;
const Server = require('./lib/server');
const BrowserTestRunner = require('./lib/runners/browser_test_runner');
const ProcessTestRunner = require('./lib/runners/process_test_runner');
const Testem = require('./public/testem/testem_client');
const Bluebird = require('bluebird');
const FakeReporter = require('./tests/support/fake_reporter');
const App = require('./lib/app');

function makeReporter(config) {
  const app = { config, reporter: null, server: { resetAbort() {} }, on() {}, emit() {} };
  const stream = new PassThrough();
  const reporter = new Reporter(app, stream);
  app.reporter = reporter;
  const sub = new FakeReporter();
  reporter.reporters = [sub];
  return { reporter, stream, app, sub };
}

console.log('--- getExitCode bail ---');
const c = new Config('ci', {});
c.config.bail_on_test_failure = 1;
const x = makeReporter(c);
const app = new App(c, function(){});
app.reporter = x.reporter;
x.app = app;
x.reporter.report('chrome', {name:'f', passed:false});
const e = app.getExitCode();
console.log('exit code err:', e && e.message);

console.log('--- browser runner abort ---');
const fakeReporter = new FakeReporter();
const launcher = { name: 'chrome', id: 1 };
const runner = new BrowserTestRunner(launcher, fakeReporter, 0, true, c);
let emitted = [];
runner.socket = { emit: (evt) => emitted.push(evt) };
Bluebird.all([runner.abort(), runner.abort()]).then(() => {
  console.log('abort emits:', emitted, 'runner.aborted:', runner.aborted);
  runner.onTestResult({name:'late', failed:1});
  runner.onGlobalError('err','url',1);
  console.log('fakeReporter.total after suppressed:', fakeReporter.total);
});

console.log('--- process runner abort ---');
const procRunner = new ProcessTestRunner({name:'proc', id:2}, fakeReporter);
let killed = false;
procRunner.process = { kill: () => { killed = true; return Bluebird.resolve(); } };
let finished = false;
procRunner.onFinish = () => { finished = true; };
procRunner.onStart = () => {};
procRunner.onEnd = () => {};
procRunner.abort().then(() => {
  procRunner.onProcessError(new Error('killed'));
  console.log('killed:', killed, 'finished:', finished, 'reported count:', fakeReporter.results.filter(r=>r.result && r.result.name).length);
});

console.log('--- client handleAbortTests ---');
Testem.aborted = false;
Testem._isIframeReady = true;
let posts = [];
Testem.iframe = { contentWindow: { postMessage: (msg) => posts.push(msg) } };
let abortedEvents = 0;
Testem.on('abort-tests', () => abortedEvents++);
Testem.handleAbortTests();
console.log('Testem.aborted:', Testem.aborted, 'abortedEvents:', abortedEvents, 'posts:', JSON.stringify(posts));
EOF
node check_bail_tmp.js