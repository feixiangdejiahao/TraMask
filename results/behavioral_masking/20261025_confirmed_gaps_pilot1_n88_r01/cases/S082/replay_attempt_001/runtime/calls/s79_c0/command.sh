cd /app && python3 - <<'PY'
p='public/testem/qunit_adapter.js'
s=open(p).read()
s=s.replace("""  function signalAllTestResults() {
    if (!allTestResultsSignaled) {
      allTestResultsSignaled = true;
      emit('all-test-results');
    }
  }
""", """  function signalAllTestResults() {
    if (!allTestResultsSignaled) {
      allTestResultsSignaled = true;
      clearQUnitQueue();
      emit('all-test-results');
    }
  }
""",1)
open(p,'w').write(s)
PY
node -c public/testem/qunit_adapter.js && echo OK