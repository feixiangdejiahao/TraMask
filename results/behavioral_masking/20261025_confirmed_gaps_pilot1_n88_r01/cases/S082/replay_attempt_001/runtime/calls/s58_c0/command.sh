cd /app && cat > lib/utils/reporter.js <<'EOF'
'use strict';

const Bluebird = require('bluebird');
const EventEmitter = require('events').EventEmitter;
const log = require('npmlog');

const reporters = require('../reporters');
const isa = require('./isa');
const ReportFile = require('./report-file');

function setupReporter(name, out, config, app) {
  let reporter;

  if (isa(name, String)) {
    let TestReporter = reporters[name];
    if (TestReporter) {
      reporter = new TestReporter(false, out, config, app);
    }
  } else if (isa(name, Function)) {
    // name is a constructor function, ignore new-cap and instantiate
    // eslint-disable-next-line new-cap
    reporter = new name(false, out, config, app);
  } else {
    reporter = name;
  }

  if (!reporter) {
    throw new Error('Test reporter `' + name + '` not found.');
  }

  return reporter;
}


class Reporter extends EventEmitter {
  constructor(app, stdout, path) {
    super();
    this.total = 0;
    this.passed = 0;
    this.skipped = 0;
    this.todo = 0;

    this._bailed = false;
    this.bailReason = null;
    this.bailLauncher = null;
    this.failures = 0;
    this.failuresByLauncher = {};
    this.failedTests = [];
    this.testsRanBeforeBail = 0;
    this.suppressedAfterBail = 0;

    if (path) {
      this.reportFile = new ReportFile(path);
    }

    let config = app.config;

    this.bailOnTestFailure = this.parseBailOnTestFailure(config);

    if (path && config.get('xunit_intermediate_output') && config.get('reporter') === 'xunit') {
      this.reporters = [
        setupReporter('tap', stdout, config, app),
        setupReporter(config.get('reporter'), this.reportFile.outputStream, config, app)
      ];
    } else {
      this.reporters = [setupReporter(config.get('reporter'), stdout, config, app)];

      if (path) {
        if (config.appMode === 'dev') {
          let devModeFileReporter = config.get('dev_mode_file_reporter');
          if (!devModeFileReporter) {
            log.warn('You configured a `report_file`, you may want to configure the `dev_mode_file_reporter` as well. Using the `tap` logger now.');
            devModeFileReporter = 'tap';
          }
          this.reporters.push(setupReporter(devModeFileReporter, this.reportFile.outputStream, config, app));
        } else {
          this.reporters.push(setupReporter(config.get('reporter'), this.reportFile.outputStream, config, app));
        }
      }
    }
  }

  parseBailOnTestFailure(config) {
    let value = config.get('bail_on_test_failure');

    if (value === false || value === undefined || value === null) {
      return 0;
    }

    if (value === true) {
      return 1;
    }

    if (typeof value === 'number' && Number.isInteger(value) && value >= 1) {
      return value;
    }

    log.warn('bail_on_test_failure', `Invalid value ${JSON.stringify(value)}. Defaulting to false.`);
    return 0;
  }

  testStarted(name, data) {
    this.reporters.forEach(reporter => {
      if (reporter.testStarted) {
        reporter.testStarted(name, data);
      }
    });
  }

  close() {
    this.finish();

    if (this.reportFile) {
      return this.reportFile.close();
    }
  }

  hasTests() {
    return this.total > 0;
  }

  hasPassed() {
    return this.total <= ((this.passed || 0) + (this.skipped || 0) + (this.todo || 0));
  }

  hasBailed() {
    return this._bailed;
  }

  isBailFailure(result) {
    return !result.passed && !result.skipped && !result.todo;
  }

  getBailReport() {
    return {
      testsRanBeforeBail: this.testsRanBeforeBail,
      bailLauncher: this.bailLauncher,
      failuresByLauncher: this.failuresByLauncher,
      failedTests: this.failedTests
    };
  }

  resetBailState() {
    this._bailed = false;
    this.bailReason = null;
    this.bailLauncher = null;
    this.failures = 0;
    this.failuresByLauncher = {};
    this.failedTests = [];
    this.testsRanBeforeBail = 0;
    this.suppressedAfterBail = 0;

    this.reporters.forEach(reporter => {
      if (typeof reporter.reset === 'function') {
        reporter.reset();
      }
    });
  }

  report(name, result) {
    this.total++;
    if (result.skipped) {
      this.skipped++;
    } else if (result.passed && !result.todo) {
      this.passed++;
    } else if (!result.passed && result.todo) {
      this.todo++;
    }

    if (this._bailed) {
      this.suppressedAfterBail++;
      return;
    }

    let failure = this.isBailFailure(result);
    if (failure) {
      this.failures++;
      this.failuresByLauncher[name] = (this.failuresByLauncher[name] || 0) + 1;
      if (result.name) {
        this.failedTests.push(result.name);
      }
    }

    this.reporters.forEach(reporter => {
      reporter.report(name, result);
    });

    if (failure && this.bailOnTestFailure > 0 && this.failures >= this.bailOnTestFailure) {
      this.bailReason = result.name;
      this.bailLauncher = name;
      this.testsRanBeforeBail = this.total;
      this._bailed = true;
      this.emit('test-failure', name, result);
    }
  }
}

Reporter.with = (app, stdout, path) => Bluebird.try(() => new Reporter(app, stdout, path)).disposer((reporter, promise) => {
  if (promise.isRejected()) {
    let err = promise.reason();

    if (!err.hideFromReporter) {
      reporter.report(null, {
        passed: false,
        name: err.name || 'unknown error',
        error: {
          message: err.message
        }
      });
    }
  }

  return reporter.close();
});

function forwardToReporters(fn) {
  return function() {
    let args = new Array(arguments.length);
    for (let i = 0; i < args.length; ++i) {
      args[i] = arguments[i];
    }

    this.reporters.forEach(reporter => {
      if (reporter[fn]) {
        reporter[fn].apply(reporter, args);
      }
    });
  };
}

['finish', 'onStart', 'onEnd', 'reportMetadata'].forEach(fn => {
  Reporter.prototype[fn] = forwardToReporters(fn);
});

module.exports = Reporter;
EOF
node -c lib/utils/reporter.js && echo OK