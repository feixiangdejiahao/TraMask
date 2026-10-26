cd /app && python3 - <<'PY'
import re
p='lib/app.js'
s=open(p).read()

# add abortRunnersCalled in constructor
s=s.replace("""    this.testSuiteTimedOut = null;
    this.testSuiteTimedOut = false;
""", """    this.testSuiteTimedOut = null;
    this.testSuiteTimedOut = false;
    this.abortRunnersCalled = false;
""",1)

# add listener in start
s=s.replace("""      return Bluebird.using(Reporter.with(this, this.stdoutStream, this.reportFileName), reporter => {
        this.reporter = reporter;
""", """      return Bluebird.using(Reporter.with(this, this.stdoutStream, this.reportFileName), reporter => {
        this.reporter = reporter;
        this.reporter.on('test-failure', () => {
          this.abortRunners();
        });
""",1)

# add resetBailState call in runTests after paused check
s=s.replace("""    if (this.paused) {
      return Bluebird.resolve();
    }

    log.info('Running tests...');
""", """    if (this.paused) {
      return Bluebird.resolve();
    }

    this.resetBailState();

    log.info('Running tests...');
""",1)

# update getExitCode
s=s.replace("""  getExitCode() {
    if (!this.reporter) {
      return new Error('Failed to initialize.');
    }
    if (!this.reporter.hasPassed()) {
      let e = new Error('Not all tests passed.');
      e.hideFromReporter = true;
      return e;
    }
""", """  getExitCode() {
    if (!this.reporter) {
      return new Error('Failed to initialize.');
    }
    if (this.reporter.hasBailed()) {
      let bailReport = this.reporter.getBailReport();
      let e = new Error(`Bailed out due to "${this.reporter.bailReason}" after ${bailReport.testsRanBeforeBail} tests.`);
      e.hideFromReporter = true;
      return e;
    }
    if (!this.reporter.hasPassed()) {
      let e = new Error('Not all tests passed.');
      e.hideFromReporter = true;
      return e;
    }
""",1)

# add methods before stopRunners
s=s.replace("""  stopRunners() {
    return Bluebird.each(this.runners, runner => {
""", """  abortRunners() {
    if (this.abortRunnersCalled) {
      return Bluebird.resolve();
    }
    this.abortRunnersCalled = true;

    this.server.broadcastAbort();

    return Bluebird.all(this.runners.map(runner => {
      if (typeof runner.abort === 'function') {
        return runner.abort();
      }
      return Bluebird.resolve();
    }));
  }

  resetBailState() {
    this.abortRunnersCalled = false;

    if (this.reporter) {
      this.reporter.resetBailState();
    }

    if (this.server) {
      this.server.resetAbort();
    }
  }

  stopRunners() {
    return Bluebird.each(this.runners, runner => {
""",1)

open(p,'w').write(s)
PY
node -c lib/app.js && echo OK