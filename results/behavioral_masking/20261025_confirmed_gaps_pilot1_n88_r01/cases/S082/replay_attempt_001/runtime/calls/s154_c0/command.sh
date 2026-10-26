cd /app && python3 - <<'PY'
p='lib/utils/reporter.js'
s=open(p).read()
s=s.replace("""  hasPassed() {
    return this.total <= ((this.passed || 0) + (this.skipped || 0) + (this.todo || 0));
  }
""", """  hasPassed() {
    if (this.hasBailed()) {
      return false;
    }
    return this.total <= ((this.passed || 0) + (this.skipped || 0) + (this.todo || 0));
  }
""",1)
open(p,'w').write(s)
PY
node -c lib/utils/reporter.js && npx mocha tests/utils/reporter_tests.js 2>&1 | tail -8