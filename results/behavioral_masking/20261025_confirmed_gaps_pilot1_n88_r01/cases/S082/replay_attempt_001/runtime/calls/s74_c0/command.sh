cd /app && python3 - <<'PY'
p='public/testem/testem_client.js'
s=open(p).read()

# add aborted to object
s=s.replace("""var Testem = {
  emitMessageQueue: [],
  afterTestsQueue: [],
  console: {},
""", """var Testem = {
  emitMessageQueue: [],
  afterTestsQueue: [],
  aborted: false,
  console: {},
""",1)

# block emitMessage
s=s.replace("""  emitMessage: function() {
    if (this._noConnectionRequired) {
      return;
    }
""", """  emitMessage: function() {
    if (this._noConnectionRequired || this.aborted) {
      return;
    }
""",1)

# add handleAbortTests method before runAfterTests
s=s.replace("""  runAfterTests: function() {
    if (Testem.afterTestsQueue.length) {
""", """  handleAbortTests: function() {
    this.aborted = true;
    this.emit('abort-tests');
    this.emit('after-tests-complete');
  },
  runAfterTests: function() {
    if (Testem.afterTestsQueue.length) {
""",1)

# add case in listenTo switch
s=s.replace("""        case 'stop-run':
          self.emit('after-tests-complete');
          break;
""", """        case 'stop-run':
          self.emit('after-tests-complete');
          break;
        case 'abort-tests':
          self.handleAbortTests();
          break;
""",1)

open(p,'w').write(s)
PY
node -c public/testem/testem_client.js && echo OK