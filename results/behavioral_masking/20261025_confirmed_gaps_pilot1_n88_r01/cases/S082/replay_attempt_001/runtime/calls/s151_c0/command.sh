cd /app && python3 - <<'PY'
# browser_test_runner start
p='lib/runners/browser_test_runner.js'
s=open(p).read()
s=s.replace("""    this.finished = false;
    this.pending = true;

    return new Bluebird.Promise(resolve => {
""", """    this.finished = false;
    this.pending = true;
    this.aborted = false;

    return new Bluebird.Promise(resolve => {
""",1)
open(p,'w').write(s)

# tap_process_test_runner start
p='lib/runners/tap_process_test_runner.js'
s=open(p).read()
s=s.replace("""  start(onFinish) {
    this.onStart();
    this.finished = false;
""", """  start(onFinish) {
    this.onStart();
    this.finished = false;
    this.aborted = false;
""",1)
open(p,'w').write(s)
PY
node -c lib/runners/browser_test_runner.js && node -c lib/runners/tap_process_test_runner.js && echo OK