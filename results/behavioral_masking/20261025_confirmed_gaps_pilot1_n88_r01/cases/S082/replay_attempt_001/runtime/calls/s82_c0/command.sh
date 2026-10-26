cd /app && python3 - <<'PY'
p='lib/reporters/xunit_reporter.js'
s=open(p).read()
s=s.replace("""    rootNode.setAttribute('failures', `${this.failures()}`);
    rootNode.setAttribute('errors', `${this.errors()}`);
    rootNode.setAttribute('timestamp', new Date().toString());
""", """    rootNode.setAttribute('failures', `${this.failures()}`);
    if (this.hasBailed()) {
      rootNode.setAttribute('errors', `${this.errors()}`);
    }
    rootNode.setAttribute('timestamp', new Date().toString());
""",1)
open(p,'w').write(s)
PY
node -c lib/reporters/xunit_reporter.js && npx mocha tests/ci/reporter_tests.js 2>&1 | tail -10