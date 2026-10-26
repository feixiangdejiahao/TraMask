cd /app && python3 - <<'PY'
p='lib/runners/browser_test_runner.js'
s=open(p).read()

# add aborted in constructor
s=s.replace("""    this.pendingTimer = undefined;
    this.onProcessExitTimer = undefined;
    this.exitRequested = false;
""", """    this.pendingTimer = undefined;
    this.onProcessExitTimer = undefined;
    this.exitRequested = false;
    this.aborted = false;
""",1)

# add abort method before stop
s=s.replace("""  stop(cb) {
    if (this.socket) {
      this.socket.emit('stop-run');
    }
    return Bluebird.resolve().asCallback(cb);
  }
""", """  abort() {
    if (this.aborted) {
      return Bluebird.resolve();
    }
    this.aborted = true;

    if (this.socket) {
      this.socket.emit('abort-tests');
    }

    return Bluebird.resolve();
  }

  stop(cb) {
    if (this.socket) {
      this.socket.emit('stop-run');
    }
    return Bluebird.resolve().asCallback(cb);
  }
""",1)

# guard reportResults
s=s.replace("""  reportResults(err, code, browserProcess) {
    browserProcess = browserProcess || this.process;
""", """  reportResults(err, code, browserProcess) {
    if (this.aborted) {
      return;
    }
    browserProcess = browserProcess || this.process;
""",1)

# guard onTestsStart
s=s.replace("""  onTestsStart(testData) {
    if (testData) {
""", """  onTestsStart(testData) {
    if (this.aborted) {
      return;
    }
    if (testData) {
""",1)

# guard onTestResult
s=s.replace("""  onTestResult(result) {
    let errItems = (result.items || [])
""", """  onTestResult(result) {
    if (this.aborted) {
      return;
    }
    let errItems = (result.items || [])
""",1)

# guard onTestMetadata
s=s.replace("""  onTestMetadata(tag, metadata) {
    this.reporter.reportMetadata(tag, metadata);
  }
""", """  onTestMetadata(tag, metadata) {
    if (this.aborted) {
      return;
    }
    this.reporter.reportMetadata(tag, metadata);
  }
""",1)

# guard onAllTestResults
s=s.replace("""  onAllTestResults() {
    log.info(`Browser ${this.name()} finished all tests.`, this.singleRun);
    this.onEnd();
  }
""", """  onAllTestResults() {
    if (this.aborted) {
      return;
    }
    log.info(`Browser ${this.name()} finished all tests.`, this.singleRun);
    this.onEnd();
  }
""",1)

# guard onGlobalError
s=s.replace("""  onGlobalError(msg, url, line) {
    let message = `${msg} at ${url}, line ${line}\\n`;
""", """  onGlobalError(msg, url, line) {
    if (this.aborted) {
      return;
    }
    let message = `${msg} at ${url}, line ${line}\\n`;
""",1)

# guard onDisconnect
s=s.replace("""  onDisconnect() {
    this.socket = null;
    if (this.finished) { return; }
""", """  onDisconnect() {
    this.socket = null;
    if (this.finished || this.aborted) { return; }
""",1)

# guard onProcessExit timer
s=s.replace("""    this.onProcessExitTimer = setTimeout(() => {
      if (this.finished) {
        return;
      }
""", """    this.onProcessExitTimer = setTimeout(() => {
      if (this.finished || this.aborted) {
        return;
      }
""",1)

# guard onProcessError
s=s.replace("""  onProcessError(err) {
    let browserProcess = this.process;
    this.process = null;

    if (this.finished) { return; }
""", """  onProcessError(err) {
    let browserProcess = this.process;
    this.process = null;

    if (this.finished || this.aborted) { return; }
""",1)

open(p,'w').write(s)
PY
node -c lib/runners/browser_test_runner.js && echo OK