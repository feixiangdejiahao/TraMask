cd /app && python3 - <<'PY'
p='lib/app.js'
s=open(p).read()
s=s.replace("""    this.abortRunnersCalled = true;

    this.server.broadcastAbort();

    return Bluebird.all(this.runners.map(runner => {
""", """    this.abortRunnersCalled = true;

    if (this.server) {
      this.server.broadcastAbort();
    }

    return Bluebird.all(this.runners.map(runner => {
""",1)
open(p,'w').write(s)
PY
node -c lib/app.js && echo OK