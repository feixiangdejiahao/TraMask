cd /app && python3 - <<'PY'
p='lib/runners/tap_process_test_runner.js'
s=open(p).read()

s=s.replace("""    this.launcherId = this.launcher.id;
    this.finished = false;
    log.info(this.launcher.name);
""", """    this.launcherId = this.launcher.id;
    this.finished = false;
    this.aborted = false;
    log.info(this.launcher.name);
""",1)

s=s.replace("""  exit() {
    if (!this.process) {
      return Bluebird.resolve();
    }

    return this.process.kill();
  }
""", """  abort() {
    if (this.aborted) {
      return Bluebird.resolve();
    }
    this.aborted = true;

    if (this.process) {
      return this.process.kill();
    }

    this.wrapUp();
    return Bluebird.resolve();
  }

  exit() {
    if (!this.process) {
      return Bluebird.resolve();
    }

    return this.process.kill();
  }
""",1)

s=s.replace("""  onTestResult(test) {
    test.launcherId = this.launcherId;
    this.reporter.report(this.launcher.name, test);
  }
""", """  onTestResult(test) {
    if (this.aborted) {
      return;
    }
    test.launcherId = this.launcherId;
    this.reporter.report(this.launcher.name, test);
  }
""",1)

s=s.replace("""  onProcessError(err) {
    var result = toResult(this.launcherId, err, 0, this.process);
    this.reporter.report(this.launcher.name, result);
    this.wrapUp();
  }
""", """  onProcessError(err) {
    if (this.aborted) {
      this.wrapUp();
      return;
    }
    var result = toResult(this.launcherId, err, 0, this.process);
    this.reporter.report(this.launcher.name, result);
    this.wrapUp();
  }
""",1)

open(p,'w').write(s)
PY
node -c lib/runners/tap_process_test_runner.js && echo OK