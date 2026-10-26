cd /app && python3 - <<'PY'
# app.js
p='lib/app.js'
s=open(p).read()
s=s.replace("""    if (this.reporter.hasBailed()) {
      let bailReport = this.reporter.getBailReport();
""", """    if (typeof this.reporter.hasBailed === 'function' && this.reporter.hasBailed()) {
      let bailReport = this.reporter.getBailReport();
""",1)
s=s.replace("""    if (this.reporter) {
      this.reporter.resetBailState();
    }
""", """    if (this.reporter && typeof this.reporter.resetBailState === 'function') {
      this.reporter.resetBailState();
    }
""",1)
open(p,'w').write(s)

# displayutils.js
p='lib/utils/displayutils.js'
s=open(p).read()
s=s.replace("""  if (!app || !app.reporter || !app.reporter.hasBailed()) {
    return [];
  }
""", """  if (!app || !app.reporter || typeof app.reporter.hasBailed !== 'function' || !app.reporter.hasBailed()) {
    return [];
  }
""",1)
open(p,'w').write(s)

# teamcity_reporter.js
p='lib/reporters/teamcity_reporter.js'
s=open(p).read()
s=s.replace("""    if (!app || !app.reporter || !app.reporter.hasBailed()) {
      return;
    }
""", """    if (!app || !app.reporter || typeof app.reporter.hasBailed !== 'function' || !app.reporter.hasBailed()) {
      return;
    }
""",1)
open(p,'w').write(s)

# xunit_reporter.js
p='lib/reporters/xunit_reporter.js'
s=open(p).read()
s=s.replace("""  hasBailed() {
    return this.app && this.app.reporter && this.app.reporter.hasBailed();
  }
""", """  hasBailed() {
    return this.app && this.app.reporter && typeof this.app.reporter.hasBailed === 'function' && this.app.reporter.hasBailed();
  }
""",1)
open(p,'w').write(s)
PY
node -c lib/app.js && node -c lib/utils/displayutils.js && node -c lib/reporters/teamcity_reporter.js && node -c lib/reporters/xunit_reporter.js && echo OK