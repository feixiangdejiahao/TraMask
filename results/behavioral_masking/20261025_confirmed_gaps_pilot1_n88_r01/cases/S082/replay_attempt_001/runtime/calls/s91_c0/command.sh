cd /app && python3 - <<'PY'
p='lib/runners/process_test_runner.js'
s=open(p).read()
s=s.replace("""  abort() {
    if (this.aborted) {
      return Bluebird.resolve();
    }
    this.aborted = true;

    if (this.process) {
      return this.process.kill();
    }

    this.finish();
    return Bluebird.resolve();
  }
""", """  abort() {
    if (this.aborted) {
      return Bluebird.resolve();
    }
    this.aborted = true;

    if (this.process) {
      let killPromise = this.process.kill();
      this.finish();
      return killPromise;
    }

    this.finish();
    return Bluebird.resolve();
  }
""",1)
open(p,'w').write(s)

p='lib/runners/tap_process_test_runner.js'
s=open(p).read()
s=s.replace("""  abort() {
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
""", """  abort() {
    if (this.aborted) {
      return Bluebird.resolve();
    }
    this.aborted = true;

    if (this.process) {
      let killPromise = this.process.kill();
      this.wrapUp();
      return killPromise;
    }

    this.wrapUp();
    return Bluebird.resolve();
  }
""",1)
open(p,'w').write(s)
PY
node -c lib/runners/process_test_runner.js && node -c lib/runners/tap_process_test_runner.js && echo OK