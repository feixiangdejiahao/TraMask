cd /app && python3 - <<'PY'
p='testem.js'
s=open(p).read()
s=s.replace("""  .option('-b, --bail_on_uncaught_error', 'Bail on any uncaught errors')
  .option('-R, --reporter [reporter]', 'Test reporter to use [tap|dot|xunit|teamcity]')
""", """  .option('-b, --bail_on_uncaught_error', 'Bail on any uncaught errors')
  .option('--bail_on_test_failure [n]', 'Bail on the Nth test failure', parseBailOnTestFailure)
  .option('-R, --reporter [reporter]', 'Test reporter to use [tap|dot|xunit|teamcity]')
""",1)

s=s.replace("""main();
function main() {
""", """function parseBailOnTestFailure(value) {
  if (value === true || value === 'true') {
    return true;
  }
  if (value === 'false') {
    return false;
  }
  let parsed = parseInt(value, 10);
  if (!isNaN(parsed)) {
    return parsed;
  }
  return value;
}

main();
function main() {
""",1)
open(p,'w').write(s)
PY
node -c testem.js && echo OK