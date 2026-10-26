cd /app && python3 - <<'PY'
p='lib/reporters/teamcity_reporter.js'
s=open(p).read()
s=s.replace("""    this.out.write(teamcityLine('message', {
      text: `Bail out! ${bailReason} (${failures} failures)`,
      status: 'ERROR'
    }));
""", """    this.out.write(teamcityLine('message', {
      text: `Bail out! ${bailReason}`,
      status: 'ERROR'
    }));
""",1)
open(p,'w').write(s)
PY
npx mocha tests/ci/reporter_tests.js 2>&1 | tail -12