cd /app && python3 - <<'PY'
p='public/testem/testem_client.js'
s=open(p).read()
s=s.replace("""  handleAbortTests: function() {
    this.aborted = true;
    this.emit('abort-tests');
    this.emitMessageToIframe(new Message(this, ['after-tests-complete']));
  },
""", """  handleAbortTests: function() {
    this.aborted = true;
    this.emitMessageQueue = [];
    this.emit('abort-tests');
    this.emitMessageToIframe(new Message(this, ['after-tests-complete']));
  },
""",1)
open(p,'w').write(s)
PY
node -c public/testem/testem_client.js && echo OK