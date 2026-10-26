'use strict';

const expect = require('chai').expect;
const sinon = require('sinon');
const PassThrough = require('stream').PassThrough;

const Config = require('../lib/config');
const Reporter = require('../lib/utils/reporter');
const FakeReporter = require('./support/fake_reporter');
const App = require('../lib/app');
const Server = require('../lib/server');
const BrowserTestRunner = require('../lib/runners/browser_test_runner');
const ProcessTestRunner = require('../lib/runners/process_test_runner');
const TapProcessTestRunner = require('../lib/runners/tap_process_test_runner');
const FakeSocket = require('./support/fake_socket');
const Launcher = require('../lib/launcher');
const Testem = require('../public/testem/testem_client');
const Bluebird = require('bluebird');

describe('bail_on_test_failure', function() {
  let sandbox;

  beforeEach(function() {
    sandbox = sinon.createSandbox();
  });

  afterEach(function() {
    sandbox.restore();
  });

  function makeApp(configOptions) {
    configOptions = configOptions || {};
    return {
      config: {
        appMode: 'ci',
        get(key) {
          if (key === 'reporter' && !configOptions.reporter) {
            return FakeReporter;
          }
          return configOptions[key];
        }
      }
    };
  }

  describe('config default', function() {
    it('defaults to false', function() {
      let config = new Config('ci');
      expect(config.get('bail_on_test_failure')).to.equal(false);
    });
  });

  describe('Reporter constructor validation', function() {
    it('accepts true as threshold one', function() {
      let reporter = new Reporter(makeApp({bail_on_test_failure: true}), new PassThrough());
      expect(reporter.bailThreshold).to.equal(1);
    });

    it('accepts a positive integer as threshold', function() {
      let reporter = new Reporter(makeApp({bail_on_test_failure: 3}), new PassThrough());
      expect(reporter.bailThreshold).to.equal(3);
    });

    it('accepts false as disabled', function() {
      let reporter = new Reporter(makeApp({bail_on_test_failure: false}), new PassThrough());
      expect(reporter.bailThreshold).to.equal(false);
    });

    ['zero', 'negative', 'float', 'string'].forEach(function(kind) {
      let value = {zero: 0, negative: -1, float: 1.5, string: '1'}[kind];
      it(`warns and defaults to false for ${kind}`, function() {
        let warn = sandbox.stub(require('npmlog'), 'warn');
        let reporter = new Reporter(makeApp({bail_on_test_failure: value}), new PassThrough());
        expect(warn).to.have.been.calledWith('bail_on_test_failure');
        expect(reporter.bailThreshold).to.equal(false);
      });
    });
  });

  describe('bail behavior', function() {
    let reporter, emitted;

    beforeEach(function() {
      reporter = new Reporter(makeApp({bail_on_test_failure: 2}), new PassThrough());
      emitted = [];
      reporter.on('test-failure', function(name, result) {
        emitted.push({name: name, result: result});
      });
    });

    function result(name, passed) {
      return {name: name, passed: passed};
    }

    it('does not bail on the first failure when threshold is 2', function() {
      reporter.report('launcher1', result('first failure', false));
      expect(reporter.hasBailed()).to.equal(false);
      expect(emitted).to.have.length(0);
      expect(reporter.getBailReport().bailLauncher).to.equal(null);
    });

    it('bails on the Nth failure and emits test-failure', function() {
      reporter.report('launcher1', result('first failure', false));
      reporter.report('launcher2', result('second failure', false));

      expect(reporter.hasBailed()).to.equal(true);
      expect(reporter.bailReason).to.equal('second failure');
      expect(reporter.getBailReport().bailLauncher).to.equal('launcher2');
      expect(reporter.getBailReport().testsRanBeforeBail).to.equal(2);
      expect(reporter.getBailReport().failuresByLauncher).to.deep.equal({launcher1: 1, launcher2: 1});
      expect(reporter.getBailReport().failedTests).to.deep.equal(['first failure', 'second failure']);
      expect(emitted).to.have.length(1);
      expect(emitted[0].name).to.equal('launcher2');
      expect(emitted[0].result.name).to.equal('second failure');
    });

    it('ignores skipped and todo failures', function() {
      reporter.report('launcher1', {name: 'skipped', passed: false, skipped: true});
      reporter.report('launcher1', {name: 'todo', passed: false, todo: true});
      reporter.report('launcher1', result('real failure', false));
      reporter.report('launcher1', result('second real failure', false));

      expect(reporter.hasBailed()).to.equal(true);
      expect(reporter.getBailReport().failedTests).to.deep.equal(['real failure', 'second real failure']);
    });

    it('gates subsequent results from sub-reporters', function() {
      let fake = new FakeReporter();
      let app = makeApp({bail_on_test_failure: 1});
      app.config.get = function(key) {
        if (key === 'reporter') {
          return fake;
        }
        return key === 'bail_on_test_failure' ? 1 : undefined;
      };
      reporter = new Reporter(app, new PassThrough());

      reporter.report('launcher1', result('fails', false));
      reporter.report('launcher1', result('after bail', true));

      expect(fake.results).to.have.length(1);
      expect(fake.results[0].result.name).to.equal('fails');
      expect(reporter.suppressed).to.equal(1);
      expect(reporter.total).to.equal(2);
    });

    it('resetBailState clears bail state and allows reporting again', function() {
      reporter = new Reporter(makeApp({bail_on_test_failure: 1}), new PassThrough());
      reporter.report('launcher1', result('fails', false));
      expect(reporter.hasBailed()).to.equal(true);

      reporter.resetBailState();
      expect(reporter.hasBailed()).to.equal(false);
      expect(reporter.bailReason).to.equal(null);
      expect(reporter.bailLauncher).to.equal(null);
      expect(reporter.getBailReport().failuresByLauncher).to.deep.equal({});
      expect(reporter.getBailReport().failedTests).to.deep.equal([]);

      reporter.report('launcher1', result('fails again', false));
      expect(reporter.hasBailed()).to.equal(true);
      expect(reporter.bailReason).to.equal('fails again');
    });
  });

  describe('reporter output', function() {
    it('tap reporter outputs bail summary', function() {
      let stream = new PassThrough();
      let reporter = new Reporter(makeApp({
        reporter: 'tap',
        bail_on_test_failure: 1,
        tap_quiet_logs: false,
        tap_failed_tests_only: false
      }), stream);
      reporter.report('launcher', {name: 'fails', passed: false});
      reporter.finish();
      let output = stream.read().toString();
      expect(output).to.match(/Bail out! fails \(1\)/);
      expect(output).to.match(/# bailed/);
      expect(output).to.match(/# ran before bail 1/);
      expect(output).to.match(/# suppressed 0/);
    });

    it('dot reporter outputs bail summary', function() {
      let stream = new PassThrough();
      let reporter = new Reporter(makeApp({
        reporter: 'dot',
        bail_on_test_failure: 1
      }), stream);
      reporter.report('launcher', {name: 'fails', passed: false});
      reporter.finish();
      let output = stream.read().toString();
      expect(output).to.match(/Bail out! fails \(1\)/);
      expect(output).to.match(/# bailed/);
      expect(output).to.match(/# ran before bail 1/);
      expect(output).to.match(/# suppressed 0/);
    });

    it('teamcity reporter outputs bail information', function() {
      let stream = new PassThrough();
      let reporter = new Reporter(makeApp({
        reporter: 'teamcity',
        bail_on_test_failure: 1
      }), stream);
      reporter.report('launcher', {name: 'fails', passed: false});
      reporter.finish();
      let output = stream.read().toString();
      expect(output).to.match(/Bail out! ERROR/);
      expect(output).to.match(/buildStatisticValue key='bailedTests' value='1'/);
      expect(output).to.match(/buildStatisticValue key='testsBeforeBail' value='1'/);
      expect(output).to.match(/buildStatisticValue key='suppressedAfterBail' value='0'/);
      expect(output).to.match(/buildProblem/);
    });

    it('xunit reporter outputs bail information', function() {
      let stream = new PassThrough();
      let reporter = new Reporter(makeApp({
        reporter: 'xunit',
        bail_on_test_failure: 1,
        xunit_exclude_stack: false
      }), stream);
      reporter.report('launcher', {name: 'fails', passed: false, runDuration: 1});
      reporter.finish();
      let output = stream.read().toString();
      expect(output).to.match(/errors="1"/);
      expect(output).to.match(/<error message="Bail out! fails \(1\)"/);
      expect(output).to.match(/name="bailReason" value="fails"/);
      expect(output).to.match(/name="testsBeforeBail" value="1"/);
      expect(output).to.match(/name="suppressedAfterBail" value="0"/);
      expect(output).to.match(/<system-out>/);
    });
  });

  describe('App', function() {
    it('getExitCode returns a bail-specific error', function() {
      let app = new App(new Config('ci'));
      app.reporter = {
        hasBailed: function() { return true; },
        getBailReport: function() {
          return {testsRanBeforeBail: 5, bailLauncher: 'launcher'};
        },
        bailReason: 'my failing test',
        hasPassed: function() { return false; },
        hasTests: function() { return true; }
      };
      let err = app.getExitCode();
      expect(err).to.be.an.instanceof(Error);
      expect(err.message).to.match(/my failing test/);
      expect(err.message).to.match(/5/);
      expect(err.message).not.to.match(/Not all tests passed/);
    });

    it('resetBailState resets abort tracking and server broadcast state', function() {
      let app = new App(new Config('ci'));
      app.reporter = new Reporter(makeApp({bail_on_test_failure: 1}), new PassThrough());
      app.reporter.report('launcher', {name: 'fails', passed: false});
      app.abortRunners();

      expect(app.aborted).to.equal(true);
      expect(app.server.abortBroadcasted).to.equal(true);

      app.resetBailState();
      expect(app.aborted).to.equal(false);
      expect(app.server.abortBroadcasted).to.equal(false);
      expect(app.reporter.hasBailed()).to.equal(false);
    });
  });

  describe('Server', function() {
    it('broadcastAbort is idempotent and tolerates uninitialized io', function() {
      let server = new Server(new Config('ci'));
      server.broadcastAbort();
      expect(server.abortBroadcasted).to.equal(true);

      server.resetAbort();
      let emit = sandbox.spy();
      server.io = {emit: emit};
      server.broadcastAbort();
      server.broadcastAbort();
      expect(emit).to.have.been.calledOnce();
      expect(emit).to.have.been.calledWith('abort-tests');

      server.resetAbort();
      server.broadcastAbort();
      expect(emit).to.have.been.calledTwice();
    });
  });

  describe('runners', function() {
    function makeBrowserRunner() {
      let config = new Config('ci');
      let launcher = new Launcher('ci', {id: 1, protocol: 'browser'}, config);
      return new BrowserTestRunner(launcher, new FakeReporter(), null, null, config);
    }

    it('browser runner abort is idempotent and emits abort-tests via socket', function() {
      let runner = makeBrowserRunner();
      let socket = new FakeSocket();
      let emit = sandbox.spy(socket, 'emit');
      runner.tryAttach('browser', 1, socket);

      return runner.abort().then(function() {
        expect(runner.aborted).to.equal(true);
        expect(emit).to.have.been.calledWith('abort-tests');
        return runner.abort();
      }).then(function() {
        expect(emit).to.have.been.calledOnce();
      });
    });

    it('browser runner abort suppresses subsequent results', function() {
      let runner = makeBrowserRunner();
      let socket = new FakeSocket();
      runner.tryAttach('browser', 1, socket);
      runner.abort();
      runner.onTestResult({failed: 1, name: 'late failure'});
      expect(runner.reporter.results).to.have.length(0);
    });

    it('tap process runner abort is idempotent and does not throw', function() {
      let config = new Config('ci');
      let launcher = new Launcher('ci', {id: 1, protocol: 'tap'}, config);
      let runner = new TapProcessTestRunner(launcher, new FakeReporter());
      sandbox.stub(runner, 'exit').callsFake(function() { return Bluebird.resolve(); });

      return runner.abort().then(function() {
        return runner.abort();
      }).then(function() {
        expect(runner.aborted).to.equal(true);
        expect(runner.finished).to.equal(true);
      });
    });

    it('process runner abort is idempotent and suppresses results', function() {
      let config = new Config('ci');
      let launcher = new Launcher('ci', {id: 1, protocol: 'process'}, config);
      let fakeReporter = new FakeReporter();
      let runner = new ProcessTestRunner(launcher, fakeReporter);
      runner.onFinish = function() {};
      sandbox.stub(runner, 'exit').callsFake(function() { return Bluebird.resolve(); });

      return runner.abort().then(function() {
        return runner.abort();
      }).then(function() {
        expect(runner.aborted).to.equal(true);
        runner.finish(new Error('should be suppressed'));
        expect(fakeReporter.results).to.have.length(0);
      });
    });
  });

  describe('client', function() {
    afterEach(function() {
      Testem.aborted = false;
      Testem._allowAbortMessages = false;
      Testem._isIframeReady = false;
      Testem.iframe = undefined;
    });

    it('handleAbortTests sets aborted, emits events, and blocks emitMessage', function() {
      Testem.aborted = false;
      Testem._allowAbortMessages = false;
      Testem._isIframeReady = true;
      Testem.iframe = { contentWindow: { postMessage: sandbox.spy() } };
      let emit = sandbox.spy(Testem, 'emit');

      Testem.handleAbortTests();

      expect(Testem.aborted).to.equal(true);
      expect(emit).to.have.been.calledWith('abort-tests');
      expect(emit).to.have.been.calledWith('after-tests-complete');
      expect(Testem.iframe.contentWindow.postMessage).to.have.callCount(2);

      Testem.emitMessage('test-result', {name: 'x'});
      expect(Testem.iframe.contentWindow.postMessage).to.have.callCount(2);
    });
  });
});

describe('adapter abort handling', function() {
  let sandbox, originalTestem;

  beforeEach(function() {
    sandbox = sinon.createSandbox();
    originalTestem = global.Testem;
    global.Testem = {aborted: false};
  });

  afterEach(function() {
    global.Testem = originalTestem;
    sandbox.restore();
  });

  describe('mocha adapter', function() {
    let mochaAdapter, _mocha, _Mocha, Runner, emit, setTimeoutStub, originalSetTimeout;

    beforeEach(function() {
      mochaAdapter = require('../public/testem/mocha_adapter');
      Runner = function() {};
      Runner.prototype.emit = function() {};
      _mocha = {Runner: Runner};
      _Mocha = {Runner: Runner};
      emit = sandbox.spy();
      setTimeoutStub = sandbox.stub();
      sandbox.stub(Runner.prototype, 'emit').callsFake(function() {});
      originalSetTimeout = global.setTimeout;
      global.mocha = _mocha;
      global.Mocha = _Mocha;
      global.emit = emit;
      global.setTimeout = setTimeoutStub;
      mochaAdapter();
    });

    afterEach(function() {
      delete global.mocha;
      delete global.Mocha;
      delete global.emit;
      global.setTimeout = originalSetTimeout;
    });

    it('suppresses events once aborted and signals all-test-results once', function() {
      let runner = new Runner();
      global.Testem.aborted = true;

      runner.emit('test end', {title: 'foo', state: 'passed'});
      expect(setTimeoutStub).not.to.have.been.called();

      runner.emit('fail', {title: 'foo'}, {message: 'x'});
      expect(emit).not.to.have.been.calledWith('test-result');

      runner.emit('end');
      runner.emit('end');
      expect(emit).to.have.been.calledOnce();
      expect(emit).to.have.been.calledWith('all-test-results');
    });

    it('suppresses inside deferred callbacks after abort', function() {
      let runner = new Runner();
      runner.emit('test end', {title: 'foo', state: 'passed'});
      let deferred = setTimeoutStub.lastCall.args[0];

      global.Testem.aborted = true;
      runner.emit('end');
      deferred();

      expect(emit).not.to.have.been.calledWith('test-result');
      expect(emit).to.have.been.calledOnce();
      expect(emit).to.have.been.calledWith('all-test-results');
    });
  });

  describe('jasmine2 adapter', function() {
    let jasmine2Adapter, addReporter, reporter;

    beforeEach(function() {
      jasmine2Adapter = require('../public/testem/jasmine2_adapter');
      addReporter = sandbox.spy();
      global.jasmine = {
        getEnv: function() {
          return {addReporter: addReporter};
        }
      };
      global.emit = sandbox.spy();
      jasmine2Adapter();
      reporter = addReporter.lastCall.args[0];
    });

    afterEach(function() {
      delete global.jasmine;
      delete global.emit;
    });

    it('suppresses events once aborted and signals all-test-results once', function() {
      global.Testem.aborted = true;
      reporter.jasmineStarted();
      reporter.specStarted({fullName: 'foo'});
      reporter.specDone({id: 0, fullName: 'foo', status: 'failed', failedExpectations: []});
      reporter.jasmineDone();
      reporter.jasmineDone();

      expect(global.emit).to.have.been.calledOnce();
      expect(global.emit).to.have.been.calledWith('all-test-results');
    });
  });

  describe('qunit adapter', function() {
    let qunitAdapter, hooks;

    beforeEach(function() {
      qunitAdapter = require('../public/testem/qunit_adapter');
      hooks = {};
      global.QUnit = {
        config: {queue: ['one', 'two']},
        log: function(fn) { hooks.log = fn; },
        testStart: function(fn) { hooks.testStart = fn; },
        testDone: function(fn) { hooks.testDone = fn; },
        done: function(fn) { hooks.done = fn; }
      };
      global.emit = sandbox.spy();
      qunitAdapter();
    });

    afterEach(function() {
      delete global.QUnit;
      delete global.emit;
    });

    it('suppresses events once aborted, clears the queue, and signals all-test-results once', function() {
      global.Testem.aborted = true;
      hooks.testStart({module: 'm', name: 't'});
      hooks.testDone({failed: 1, passed: 0, skipped: 0, todo: 0, total: 1, runtime: 1});
      hooks.done({runtime: 1});
      hooks.done({runtime: 1});

      expect(global.QUnit.config.queue).to.have.length(0);
      expect(global.emit).to.have.been.calledOnce();
      expect(global.emit).to.have.been.calledWith('all-test-results');
    });
  });
});
